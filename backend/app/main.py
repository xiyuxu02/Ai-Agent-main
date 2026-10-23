"""FastAPI application entrypoint with bounded, validated public APIs."""

import asyncio        #异步编程
import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
import uuid           #生成唯一id
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Path, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from .agent import evict_agent, get_or_create_agent
from .auth import (
    SESSION_COOKIE_NAME,
    AuthenticatedUser,
    ensure_auth_schema,
    issue_session_cookie,
    login_user,
    logout_user,
    register_user,
    require_current_user,
)
from .memory import get_memory_manager
from .tools import check_database_readiness
from .schemas import (
    CONVERSATION_ID_PATTERN,
    MAX_CONVERSATION_ID_LENGTH,
    ChatRequest,
    ChatResponse,
    ErrorResponse,
    HealthResponse,
    LoginRequest,
    RegisterRequest,
    UserResponse,
)

logger = logging.getLogger(__name__)
APP_VERSION = "3.0.0"
DEFAULT_CORS_ORIGINS = (
    "http://localhost:5173",
    "http://localhost:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:3000",
)


def _bounded_positive_int(name: str, default: int, maximum: int) -> int:
    try:
        return min(maximum, max(1, int(os.getenv(name, str(default)))))
    except ValueError:
        logger.warning("Ignoring invalid integer configuration for %s", name)
        return default


RATE_LIMIT_REQUESTS = _bounded_positive_int("RATE_LIMIT_REQUESTS", 30, 10_000)
RATE_LIMIT_WINDOW_SECONDS = _bounded_positive_int("RATE_LIMIT_WINDOW_SECONDS", 60, 3_600)
MAX_CONCURRENT_CHAT_REQUESTS = _bounded_positive_int("MAX_CONCURRENT_CHAT_REQUESTS", 8, 1_000)
AGENT_TIMEOUT_SECONDS = _bounded_positive_int("AGENT_TIMEOUT_SECONDS", 55, 600)
_rate_windows: dict[str, deque[float]] = defaultdict(deque)
_rate_limit_lock = asyncio.Lock()
_chat_semaphore = asyncio.Semaphore(MAX_CONCURRENT_CHAT_REQUESTS)

_configured_signing_secret = os.getenv("CONVERSATION_SIGNING_SECRET", "").strip()
if not _configured_signing_secret:
    _configured_signing_secret = secrets.token_urlsafe(32)
    logger.warning(
        "CONVERSATION_SIGNING_SECRET is unset; generated tokens will become invalid after restart"
    )
_conversation_signing_secret = _configured_signing_secret.encode("utf-8")


def create_conversation_token(conversation_id: str, user_id: str) -> str:
    digest = hmac.new(
        _conversation_signing_secret,
        f"{user_id}:{conversation_id}".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def require_conversation_access(
    conversation_id: str, token: Optional[str], user_id: str
) -> None:
    expected = create_conversation_token(conversation_id, user_id)
    if not token or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=403, detail="Conversation access denied.")


async def enforce_chat_rate_limit(request: Request) -> None:
    client_key = request.client.host if request.client else "unknown"
    now = time.monotonic()
    cutoff = now - RATE_LIMIT_WINDOW_SECONDS
    async with _rate_limit_lock:
        window = _rate_windows[client_key]
        while window and window[0] <= cutoff:
            window.popleft()
        if len(window) >= RATE_LIMIT_REQUESTS:
            raise HTTPException(status_code=429, detail="Too many chat requests. Please retry later.")
        window.append(now)


def cors_allow_origins() -> list[str]:
    """Return a comma-delimited origin allowlist; wildcards are never accepted."""
    configured = os.getenv("CORS_ALLOW_ORIGINS")
    candidates = configured.split(",") if configured else DEFAULT_CORS_ORIGINS
    origins: list[str] = []
    for raw_origin in candidates:
        origin = raw_origin.strip().rstrip("/")
        parsed = urlparse(origin)
        if (
            origin == "*"
            or parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.path
            or parsed.params
            or parsed.query
            or parsed.fragment
        ):
            logger.warning("Ignoring invalid CORS origin configuration")
            continue
        if origin not in origins:
            origins.append(origin)
    return origins


def require_safe_conversation_id(conversation_id: str) -> str:
    if (
        len(conversation_id) > MAX_CONVERSATION_ID_LENGTH
        or not CONVERSATION_ID_PATTERN.fullmatch(conversation_id)
    ):
        raise HTTPException(status_code=422, detail="Invalid conversation ID.")
    return conversation_id


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        await asyncio.to_thread(ensure_auth_schema)
    except Exception:
        logger.exception("Unable to initialize authentication tables")
    logger.info("AI Agent service started")
    yield
    logger.info("AI Agent service stopped")


app = FastAPI(
    title="AI Agent Customer Service",
    description="A bounded FastAPI service for an AI customer-service agent.",
    version=APP_VERSION,
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allow_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Conversation-Token"],
)


@app.get("/health", response_model=HealthResponse, tags=["health"])
async def health_check() -> HealthResponse:
    return HealthResponse(status="healthy", version=APP_VERSION, timestamp=datetime.now())


@app.get("/ready", tags=["health"])
async def readiness_check():
    """Check dependencies required for the complete demo workflow."""

    checks = {
        "llm_configured": bool(os.getenv("OPENAI_API_KEY", "").strip()),
        "database": False,
    }
    try:
        checks["database"] = await asyncio.wait_for(
            asyncio.to_thread(check_database_readiness),
            timeout=6,
        )
    except asyncio.TimeoutError:
        logger.warning("Database readiness check timed out")

    ready = all(checks.values())
    content = {"status": "ready" if ready else "not_ready", "checks": checks}
    if not ready:
        return JSONResponse(status_code=503, content=content)
    return content


@app.post("/api/auth/register", response_model=UserResponse, tags=["auth"])
async def register(payload: RegisterRequest, response: Response) -> UserResponse:
    try:
        user, raw_token = await asyncio.to_thread(
            register_user, payload.username, payload.password, payload.display_name
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    issue_session_cookie(response, raw_token)
    return UserResponse(**user.as_dict())


@app.post("/api/auth/login", response_model=UserResponse, tags=["auth"])
async def login(payload: LoginRequest, response: Response) -> UserResponse:
    try:
        user, raw_token = await asyncio.to_thread(login_user, payload.username, payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    issue_session_cookie(response, raw_token)
    return UserResponse(**user.as_dict())


@app.post("/api/auth/logout", tags=["auth"])
async def logout(
    response: Response,
    session_token: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE_NAME),
):
    await asyncio.to_thread(logout_user, response, session_token)
    return {"success": True}


@app.get("/api/auth/me", response_model=UserResponse, tags=["auth"])
async def current_user(
    user: AuthenticatedUser = Depends(require_current_user),
) -> UserResponse:
    return UserResponse(**user.as_dict())


@app.post("/api/chat", response_model=ChatResponse, tags=["chat"])
async def chat(
    payload: ChatRequest,
    request: Request,
    conversation_token: Optional[str] = Header(default=None, alias="X-Conversation-Token"),
    user: AuthenticatedUser = Depends(require_current_user),
) -> ChatResponse:
    await enforce_chat_rate_limit(request)
    conversation_id = payload.conversation_id or str(uuid.uuid4())
    if payload.conversation_id:
        require_conversation_access(conversation_id, conversation_token, user.user_id)
    issued_token = create_conversation_token(conversation_id, user.user_id)
    request_id = str(uuid.uuid4())
    try:
        agent = get_or_create_agent(conversation_id, user.user_id)
        async with _chat_semaphore:
            result = await asyncio.wait_for(
                asyncio.to_thread(agent.invoke, payload.message, request_id),
                timeout=AGENT_TIMEOUT_SECONDS,
            )
        if not result.get("success"):
            logger.warning("Agent invocation failed for conversation %s", conversation_id)
            raise HTTPException(status_code=502, detail="Unable to process the message.")
        return ChatResponse(
            message=result["message"],
            conversation_id=conversation_id,
            conversation_token=issued_token,
            request_id=request_id,
            tools_used=result.get("tool_used", []),
            timestamp=datetime.now(),
        )
    except asyncio.TimeoutError:
        logger.warning("Agent invocation timed out for conversation %s", conversation_id)
        raise HTTPException(status_code=504, detail="The agent timed out.")
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected chat failure for conversation %s", conversation_id)
        raise HTTPException(status_code=500, detail="Internal server error.")


async def stream_chat_response(
    message: str,
    conversation_id: str,
    conversation_token: str,
    request_id: str,
    user_id: str,
):
    """SSE 流式响应。

    Agent 的流式接口是同步生成器（内部为同步 LLM / DB / HTTP 调用），
    如果在事件循环里直接迭代，会阻塞整个服务。因此放到线程池中执行，
    通过 asyncio.Queue 把数据块转交回事件循环。
    """
    yield {
        "event": "conversation",
        "data": json.dumps(
            {
                "conversation_id": conversation_id,
                "conversation_token": conversation_token,
                "request_id": request_id,
            }
        ),
    }

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    _STREAM_DONE = object()

    def produce() -> None:
        try:
            agent = get_or_create_agent(conversation_id, user_id)
            for chunk in agent.stream(message, request_id):
                if chunk:
                    loop.call_soon_threadsafe(queue.put_nowait, chunk)
        except Exception:
            logger.exception("Streaming chat failed for conversation %s", conversation_id)
            loop.call_soon_threadsafe(queue.put_nowait, None)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, _STREAM_DONE)

    async with _chat_semaphore:
        loop.run_in_executor(None, produce)
        deadline = loop.time() + AGENT_TIMEOUT_SECONDS
        while True:
            try:
                item = await asyncio.wait_for(
                    queue.get(),
                    timeout=max(0.1, deadline - loop.time()),
                )
            except asyncio.TimeoutError:
                logger.warning("Streaming agent timed out for conversation %s", conversation_id)
                yield {"event": "error", "data": json.dumps({"error": "Agent 响应超时。"})}
                break
            if item is _STREAM_DONE:
                break
            if item is None:
                yield {"event": "error", "data": json.dumps({"error": "暂时无法处理这条消息。"})}
                break
            yield {"event": "message", "data": json.dumps({"delta": item}, ensure_ascii=False)}

    yield {"event": "done", "data": json.dumps({"request_id": request_id})}


@app.post("/api/chat/stream", tags=["chat"])
async def chat_stream_post(
    payload: ChatRequest,
    request: Request,
    conversation_token: Optional[str] = Header(default=None, alias="X-Conversation-Token"),
    user: AuthenticatedUser = Depends(require_current_user),
):
    await enforce_chat_rate_limit(request)
    conversation_id = payload.conversation_id or str(uuid.uuid4())
    if payload.conversation_id:
        require_conversation_access(conversation_id, conversation_token, user.user_id)
    issued_token = create_conversation_token(conversation_id, user.user_id)
    request_id = str(uuid.uuid4())
    return EventSourceResponse(
        stream_chat_response(
            payload.message, conversation_id, issued_token, request_id, user.user_id
        )
    )


@app.get("/api/history/{conversation_id}", tags=["history"])
async def get_history(
    conversation_id: str = Path(..., max_length=MAX_CONVERSATION_ID_LENGTH),
    conversation_token: Optional[str] = Header(default=None, alias="X-Conversation-Token"),
    user: AuthenticatedUser = Depends(require_current_user),
):
    safe_conversation_id = require_safe_conversation_id(conversation_id)
    require_conversation_access(safe_conversation_id, conversation_token, user.user_id)
    try:
        history = get_memory_manager().get_history(safe_conversation_id)
        return {"conversation_id": safe_conversation_id, "messages": history, "count": len(history)}
    except Exception:
        logger.exception("History lookup failed for conversation %s", safe_conversation_id)
        raise HTTPException(status_code=500, detail="Internal server error.")


@app.delete("/api/history/{conversation_id}", tags=["history"])
async def clear_history(
    conversation_id: str = Path(..., max_length=MAX_CONVERSATION_ID_LENGTH),
    conversation_token: Optional[str] = Header(default=None, alias="X-Conversation-Token"),
    user: AuthenticatedUser = Depends(require_current_user),
):
    safe_conversation_id = require_safe_conversation_id(conversation_id)
    require_conversation_access(safe_conversation_id, conversation_token, user.user_id)
    try:
        success = get_memory_manager().clear_memory(safe_conversation_id)
        evict_agent(safe_conversation_id, user.user_id)
        return {
            "success": success,
            "conversation_id": safe_conversation_id,
            "message": "Conversation history cleared." if success else "Conversation history does not exist.",
        }
    except Exception:
        logger.exception("History cleanup failed for conversation %s", safe_conversation_id)
        raise HTTPException(status_code=500, detail="Internal server error.")


@app.exception_handler(HTTPException)
async def http_exception_handler(_: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(error=str(exc.detail), timestamp=datetime.now()).model_dump(mode="json"),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_: Request, exc: RequestValidationError):
    logger.info("Request validation failed: %s error(s)", len(exc.errors()))
    return JSONResponse(
        status_code=422,
        content=ErrorResponse(error="Invalid request.", timestamp=datetime.now()).model_dump(mode="json"),
    )


@app.exception_handler(Exception)
async def general_exception_handler(_: Request, exc: Exception):
    logger.exception("Unhandled application error", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(error="Internal server error.", timestamp=datetime.now()).model_dump(mode="json"),
    )


@app.get("/", tags=["root"])
async def root():
    return {"message": "AI Agent Customer Service", "version": APP_VERSION, "docs": "/docs", "health": "/health"}

import type { AuthUser, ConversationSession, MessageRole } from "../types";

export const MAX_MESSAGE_LENGTH = 4_000;

const CHAT_TIMEOUT_MS = 60_000;
const STANDARD_TIMEOUT_MS = 8_000;
const rawApiUrl = import.meta.env.VITE_API_URL?.trim() || "http://localhost:8000";

export const API_BASE_URL = rawApiUrl.replace(/\/+$/, "");

export type ApiErrorKind =
  | "http"
  | "network"
  | "timeout"
  | "aborted"
  | "invalid-response";

export class ApiClientError extends Error {
  readonly kind: ApiErrorKind;
  readonly status?: number;

  constructor(kind: ApiErrorKind, message: string, status?: number) {
    super(message);
    this.name = "ApiClientError";
    this.kind = kind;
    this.status = status;
  }
}

export interface ChatResponse {
  message: string;
  conversation_id: string;
  conversation_token: string;
  request_id: string;
  tools_used: string[];
  timestamp: string;
}

export interface HistoryMessage {
  role: MessageRole | "system";
  content: string;
  timestamp: string;
}

export interface HistoryResponse {
  conversation_id: string;
  messages: HistoryMessage[];
  count: number;
}

export interface DeleteHistoryResponse {
  success: boolean;
  conversation_id: string;
  message: string;
}

export interface HealthResponse {
  status: string;
  version: string;
  timestamp: string;
}

interface RequestOptions {
  signal?: AbortSignal;
  timeoutMs?: number;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function readErrorMessage(payload: unknown, fallback: string): string {
  if (!isRecord(payload)) {
    return fallback;
  }

  if (typeof payload.error === "string" && payload.error.trim()) {
    return payload.error;
  }

  if (typeof payload.detail === "string" && payload.detail.trim()) {
    return payload.detail;
  }

  return fallback;
}

async function readJson(response: Response): Promise<unknown> {
  const text = await response.text();

  if (!text) {
    return null;
  }

  try {
    return JSON.parse(text) as unknown;
  } catch {
    throw new ApiClientError(
      "invalid-response",
      "服务返回了无法解析的数据。",
      response.status
    );
  }
}

async function requestJson(
  path: string,
  init: RequestInit,
  options: RequestOptions = {}
): Promise<unknown> {
  const controller = new AbortController();
  let abortKind: "timeout" | "aborted" | null = null;

  const abortFromCaller = () => {
    if (!controller.signal.aborted) {
      abortKind = "aborted";
      controller.abort();
    }
  };

  if (options.signal?.aborted) {
    abortFromCaller();
  } else {
    options.signal?.addEventListener("abort", abortFromCaller, { once: true });
  }

  const timeoutId = window.setTimeout(() => {
    if (!controller.signal.aborted) {
      abortKind = "timeout";
      controller.abort();
    }
  }, options.timeoutMs ?? STANDARD_TIMEOUT_MS);

  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      credentials: "include",
      signal: controller.signal,
    });
    const payload = await readJson(response);

    if (!response.ok) {
      throw new ApiClientError(
        "http",
        readErrorMessage(payload, `请求失败（HTTP ${response.status}）。`),
        response.status
      );
    }

    return payload;
  } catch (error) {
    if (error instanceof ApiClientError) {
      throw error;
    }

    if (controller.signal.aborted) {
      throw new ApiClientError(
        abortKind ?? "aborted",
        abortKind === "timeout" ? "请求超时。" : "请求已取消。"
      );
    }

    throw new ApiClientError(
      "network",
      error instanceof Error ? error.message : "网络请求失败。"
    );
  } finally {
    window.clearTimeout(timeoutId);
    options.signal?.removeEventListener("abort", abortFromCaller);
  }
}

function assertAuthUser(value: unknown): AuthUser {
  if (
    !isRecord(value) ||
    typeof value.user_id !== "string" ||
    typeof value.username !== "string" ||
    typeof value.display_name !== "string"
  ) {
    throw new ApiClientError("invalid-response", "登录响应格式不正确。");
  }
  return value as unknown as AuthUser;
}

export async function register(
  username: string,
  password: string,
  displayName: string
): Promise<AuthUser> {
  const payload = await requestJson("/api/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password, display_name: displayName || null }),
  });
  return assertAuthUser(payload);
}

export async function login(username: string, password: string): Promise<AuthUser> {
  const payload = await requestJson("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  return assertAuthUser(payload);
}

export async function logout(): Promise<void> {
  await requestJson("/api/auth/logout", { method: "POST" });
}

export async function getCurrentUser(signal?: AbortSignal): Promise<AuthUser> {
  const payload = await requestJson(
    "/api/auth/me",
    { method: "GET" },
    { signal }
  );
  return assertAuthUser(payload);
}

function sessionHeaders(session: ConversationSession | null): HeadersInit {
  return session
    ? { "X-Conversation-Token": session.conversationToken }
    : {};
}

function assertChatResponse(value: unknown): ChatResponse {
  if (
    !isRecord(value) ||
    typeof value.message !== "string" ||
    typeof value.conversation_id !== "string" ||
    typeof value.conversation_token !== "string" ||
    typeof value.request_id !== "string" ||
    !Array.isArray(value.tools_used) ||
    !value.tools_used.every((tool) => typeof tool === "string") ||
    typeof value.timestamp !== "string" ||
    !value.conversation_id ||
    !value.conversation_token ||
    !value.request_id
  ) {
    throw new ApiClientError("invalid-response", "聊天响应缺少必要字段。");
  }

  return value as unknown as ChatResponse;
}

function isHistoryMessage(value: unknown): value is HistoryMessage {
  return (
    isRecord(value) &&
    (value.role === "user" || value.role === "assistant" || value.role === "system") &&
    typeof value.content === "string" &&
    typeof value.timestamp === "string"
  );
}

function assertHistoryResponse(value: unknown): HistoryResponse {
  if (
    !isRecord(value) ||
    typeof value.conversation_id !== "string" ||
    !Array.isArray(value.messages) ||
    !value.messages.every(isHistoryMessage) ||
    typeof value.count !== "number"
  ) {
    throw new ApiClientError("invalid-response", "历史记录响应格式不正确。");
  }

  return value as unknown as HistoryResponse;
}

function assertDeleteResponse(value: unknown): DeleteHistoryResponse {
  if (
    !isRecord(value) ||
    typeof value.success !== "boolean" ||
    typeof value.conversation_id !== "string" ||
    typeof value.message !== "string"
  ) {
    throw new ApiClientError("invalid-response", "清理会话响应格式不正确。");
  }

  return value as unknown as DeleteHistoryResponse;
}

function assertHealthResponse(value: unknown): HealthResponse {
  if (
    !isRecord(value) ||
    typeof value.status !== "string" ||
    typeof value.version !== "string" ||
    typeof value.timestamp !== "string"
  ) {
    throw new ApiClientError("invalid-response", "健康检查响应格式不正确。");
  }

  return value as unknown as HealthResponse;
}

export async function sendChatMessage(
  message: string,
  session: ConversationSession | null,
  signal?: AbortSignal
): Promise<ChatResponse> {
  const payload = await requestJson(
    "/api/chat",
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...sessionHeaders(session),
      },
      body: JSON.stringify({
        message,
        conversation_id: session?.conversationId ?? null,
      }),
    },
    { signal, timeoutMs: CHAT_TIMEOUT_MS }
  );
  const response = assertChatResponse(payload);

  if (session && response.conversation_id !== session.conversationId) {
    throw new ApiClientError("invalid-response", "服务返回了不匹配的会话标识。");
  }

  return response;
}

export interface ChatStreamHandlers {
  onConversation: (session: ConversationSession, requestId: string) => void;
  onDelta: (delta: string) => void;
  onDone?: (requestId: string) => void;
}

export async function streamChatMessage(
  message: string,
  session: ConversationSession | null,
  handlers: ChatStreamHandlers,
  signal?: AbortSignal
): Promise<void> {
  const controller = new AbortController();
  let abortKind: "timeout" | "aborted" | null = null;
  const abortFromCaller = () => {
    abortKind = "aborted";
    controller.abort();
  };
  if (signal?.aborted) abortFromCaller();
  else signal?.addEventListener("abort", abortFromCaller, { once: true });

  const timeoutId = window.setTimeout(() => {
    abortKind = "timeout";
    controller.abort();
  }, CHAT_TIMEOUT_MS);

  try {
    const response = await fetch(`${API_BASE_URL}/api/chat/stream`, {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
        ...sessionHeaders(session),
      },
      body: JSON.stringify({
        message,
        conversation_id: session?.conversationId ?? null,
      }),
      signal: controller.signal,
    });

    if (!response.ok) {
      const payload = await readJson(response);
      throw new ApiClientError(
        "http",
        readErrorMessage(payload, `请求失败（HTTP ${response.status}）。`),
        response.status
      );
    }
    if (!response.body) {
      throw new ApiClientError("invalid-response", "浏览器没有收到流式响应。");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    const dispatch = (block: string) => {
      let eventName = "message";
      const dataLines: string[] = [];
      for (const rawLine of block.split(/\r?\n/)) {
        if (rawLine.startsWith("event:")) eventName = rawLine.slice(6).trim();
        if (rawLine.startsWith("data:")) dataLines.push(rawLine.slice(5).trimStart());
      }
      if (dataLines.length === 0) return;
      const rawData = dataLines.join("\n");
      let payload: unknown;
      try {
        payload = JSON.parse(rawData) as unknown;
      } catch {
        throw new ApiClientError("invalid-response", "流式响应包含无效数据。");
      }

      if (eventName === "conversation") {
        if (
          !isRecord(payload) ||
          typeof payload.conversation_id !== "string" ||
          typeof payload.conversation_token !== "string" ||
          typeof payload.request_id !== "string"
        ) {
          throw new ApiClientError("invalid-response", "会话事件缺少必要字段。");
        }
        if (session && payload.conversation_id !== session.conversationId) {
          throw new ApiClientError("invalid-response", "服务返回了不匹配的会话标识。");
        }
        handlers.onConversation(
          {
            conversationId: payload.conversation_id,
            conversationToken: payload.conversation_token,
          },
          payload.request_id
        );
      } else if (eventName === "message") {
        if (!isRecord(payload) || typeof payload.delta !== "string") {
          throw new ApiClientError("invalid-response", "消息事件缺少文本片段。");
        }
        handlers.onDelta(payload.delta);
      } else if (eventName === "done") {
        if (isRecord(payload) && typeof payload.request_id === "string") {
          handlers.onDone?.(payload.request_id);
        }
      } else if (eventName === "error") {
        throw new ApiClientError(
          "http",
          readErrorMessage(payload, "Agent 暂时无法完成该请求。"),
          502
        );
      }
    };

    let streamComplete = false;
    while (!streamComplete) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      const blocks = buffer.split(/\r?\n\r?\n/);
      buffer = blocks.pop() ?? "";
      blocks.forEach(dispatch);
      streamComplete = done;
    }
    if (buffer.trim()) dispatch(buffer);
  } catch (error) {
    if (error instanceof ApiClientError) throw error;
    if (controller.signal.aborted) {
      throw new ApiClientError(
        abortKind ?? "aborted",
        abortKind === "timeout" ? "请求超时。" : "请求已取消。"
      );
    }
    throw new ApiClientError(
      "network",
      error instanceof Error ? error.message : "网络请求失败。"
    );
  } finally {
    window.clearTimeout(timeoutId);
    signal?.removeEventListener("abort", abortFromCaller);
  }
}

export async function getConversationHistory(
  session: ConversationSession,
  signal?: AbortSignal
): Promise<HistoryResponse> {
  const payload = await requestJson(
    `/api/history/${encodeURIComponent(session.conversationId)}`,
    {
      method: "GET",
      headers: sessionHeaders(session),
    },
    { signal }
  );

  return assertHistoryResponse(payload);
}

export async function deleteConversationHistory(
  session: ConversationSession,
  signal?: AbortSignal
): Promise<DeleteHistoryResponse> {
  const payload = await requestJson(
    `/api/history/${encodeURIComponent(session.conversationId)}`,
    {
      method: "DELETE",
      headers: sessionHeaders(session),
    },
    { signal }
  );

  return assertDeleteResponse(payload);
}

export async function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const payload = await requestJson(
    "/health",
    { method: "GET" },
    { signal, timeoutMs: 5_000 }
  );

  return assertHealthResponse(payload);
}

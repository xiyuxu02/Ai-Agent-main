"""Database-backed authentication with opaque HttpOnly session cookies."""

import base64
import hashlib
import hmac
import os
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Cookie, HTTPException, Response
from mysql.connector import IntegrityError

from .tools import _get_mysql_connection


SESSION_COOKIE_NAME = "ai_agent_session"
SESSION_DAYS = max(1, int(os.getenv("AUTH_SESSION_DAYS", "7")))
PASSWORD_ITERATIONS = max(210_000, int(os.getenv("AUTH_PASSWORD_ITERATIONS", "600000")))
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_\u4e00-\u9fff]{3,32}$")


def ensure_auth_schema() -> None:
    """Create auth tables for both fresh and already-initialized databases."""
    connection = _get_mysql_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id VARCHAR(64) NOT NULL PRIMARY KEY,
                username VARCHAR(32) NOT NULL UNIQUE,
                password_hash VARCHAR(255) NOT NULL,
                display_name VARCHAR(64) NOT NULL,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
                updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                    ON UPDATE CURRENT_TIMESTAMP(6)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS user_sessions (
                session_token_hash CHAR(64) NOT NULL PRIMARY KEY,
                user_id VARCHAR(64) NOT NULL,
                expires_at DATETIME(6) NOT NULL,
                created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
                last_seen_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
                KEY idx_user_sessions_user (user_id),
                KEY idx_user_sessions_expiry (expires_at),
                CONSTRAINT fk_user_sessions_user FOREIGN KEY (user_id)
                    REFERENCES users (user_id) ON UPDATE CASCADE ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
            """
        )
        cursor.execute("DELETE FROM user_sessions WHERE expires_at <= UTC_TIMESTAMP(6)")
        connection.commit()
    finally:
        cursor.close()
        connection.close()


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: str
    username: str
    display_name: str

    def as_dict(self) -> dict[str, str]:
        return {
            "user_id": self.user_id,
            "username": self.username,
            "display_name": self.display_name,
        }


def normalize_username(username: str) -> str:
    normalized = username.strip()
    if not USERNAME_PATTERN.fullmatch(normalized):
        raise ValueError("用户名需为 3-32 位中文、字母、数字或下划线。")
    return normalized


def validate_password(password: str) -> None:
    if len(password) < 8 or len(password) > 128:
        raise ValueError("密码长度需为 8-128 位。")
    if password.isspace():
        raise ValueError("密码不能只包含空白字符。")


def hash_password(password: str) -> str:
    validate_password(password)
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS
    )
    return "pbkdf2_sha256${}${}${}".format(
        PASSWORD_ITERATIONS,
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations_raw, salt_raw, expected_raw = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_raw)
        salt = base64.urlsafe_b64decode(salt_raw.encode("ascii"))
        expected = base64.urlsafe_b64decode(expected_raw.encode("ascii"))
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def _session_digest(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _set_session_cookie(response: Response, raw_token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=raw_token,
        max_age=SESSION_DAYS * 24 * 60 * 60,
        httponly=True,
        secure=os.getenv("AUTH_COOKIE_SECURE", "false").lower() in {"1", "true", "yes"},
        samesite="lax",
        path="/",
    )


def _create_session(cursor, user_id: str) -> str:
    raw_token = secrets.token_urlsafe(48)
    expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=SESSION_DAYS)
    cursor.execute(
        """
        INSERT INTO user_sessions (session_token_hash, user_id, expires_at)
        VALUES (%s, %s, %s)
        """,
        (_session_digest(raw_token), user_id, expires_at),
    )
    return raw_token


def register_user(username: str, password: str, display_name: Optional[str]) -> tuple[AuthenticatedUser, str]:
    username = normalize_username(username)
    validate_password(password)
    clean_display_name = (display_name or username).strip()
    if not clean_display_name or len(clean_display_name) > 64:
        raise ValueError("昵称长度需为 1-64 位。")

    connection = _get_mysql_connection()
    cursor = connection.cursor()
    user_id = f"USR{uuid.uuid4().hex[:29].upper()}"
    try:
        cursor.execute(
            """
            INSERT INTO users (user_id, username, password_hash, display_name)
            VALUES (%s, %s, %s, %s)
            """,
            (user_id, username, hash_password(password), clean_display_name),
        )
        raw_token = _create_session(cursor, user_id)
        connection.commit()
    except IntegrityError as exc:
        connection.rollback()
        raise ValueError("该用户名已被注册。") from exc
    finally:
        cursor.close()
        connection.close()
    return AuthenticatedUser(user_id, username, clean_display_name), raw_token


def login_user(username: str, password: str) -> tuple[AuthenticatedUser, str]:
    try:
        username = normalize_username(username)
    except ValueError as exc:
        raise ValueError("用户名或密码错误。") from exc

    connection = _get_mysql_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT user_id, username, display_name, password_hash
            FROM users WHERE username = %s AND is_active = TRUE LIMIT 1
            """,
            (username,),
        )
        row = cursor.fetchone()
        if not row or not verify_password(password, row["password_hash"]):
            raise ValueError("用户名或密码错误。")
        raw_token = _create_session(cursor, row["user_id"])
        connection.commit()
        return AuthenticatedUser(row["user_id"], row["username"], row["display_name"]), raw_token
    finally:
        cursor.close()
        connection.close()


def issue_session_cookie(response: Response, raw_token: str) -> None:
    _set_session_cookie(response, raw_token)


def logout_user(response: Response, raw_token: Optional[str]) -> None:
    if raw_token:
        connection = _get_mysql_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                "DELETE FROM user_sessions WHERE session_token_hash = %s",
                (_session_digest(raw_token),),
            )
            connection.commit()
        finally:
            cursor.close()
            connection.close()
    response.delete_cookie(SESSION_COOKIE_NAME, path="/", samesite="lax")


def require_current_user(
    session_token: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> AuthenticatedUser:
    if not session_token:
        raise HTTPException(status_code=401, detail="请先登录。")

    connection = _get_mysql_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT u.user_id, u.username, u.display_name
            FROM user_sessions s
            JOIN users u ON u.user_id = s.user_id
            WHERE s.session_token_hash = %s
              AND s.expires_at > UTC_TIMESTAMP(6)
              AND u.is_active = TRUE
            LIMIT 1
            """,
            (_session_digest(session_token),),
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=401, detail="登录已过期，请重新登录。")
        cursor.execute(
            "UPDATE user_sessions SET last_seen_at = UTC_TIMESTAMP(6) WHERE session_token_hash = %s",
            (_session_digest(session_token),),
        )
        connection.commit()
        return AuthenticatedUser(row["user_id"], row["username"], row["display_name"])
    finally:
        cursor.close()
        connection.close()

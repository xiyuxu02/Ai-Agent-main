"""
数据模型定义
定义聊天请求、响应和消息的数据结构
"""

import re

from pydantic import BaseModel, Field, field_validator
from typing import List, Optional
from datetime import datetime


MAX_MESSAGE_LENGTH = 4_000
MAX_CONVERSATION_ID_LENGTH = 128
CONVERSATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


class ChatRequest(BaseModel):
    """聊天请求模型"""
    message: str = Field(..., description="用户消息", min_length=1)
    conversation_id: Optional[str] = Field(default=None, description="对话ID，用于追踪对话历史")


    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Message must not be blank.")
        if len(value) > MAX_MESSAGE_LENGTH:
            raise ValueError("Message exceeds the maximum length.")
        return value

    @field_validator("conversation_id")
    @classmethod
    def validate_conversation_id(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if len(value) > MAX_CONVERSATION_ID_LENGTH or not CONVERSATION_ID_PATTERN.fullmatch(value):
            raise ValueError("Conversation ID contains unsupported characters.")
        return value


class ChatResponse(BaseModel):
    """聊天响应模型"""
    message: str = Field(..., description="AI回复消息")
    conversation_id: str = Field(..., description="对话ID")
    conversation_token: str = Field(..., description="后续访问该会话所需的令牌")
    request_id: str = Field(..., description="请求追踪ID")
    tools_used: List[str] = Field(default_factory=list, description="本轮实际调用的工具")
    timestamp: datetime = Field(default_factory=datetime.now, description="时间戳")


class HealthResponse(BaseModel):
    """健康检查响应模型"""
    status: str = Field(default="healthy", description="服务状态")
    version: str = Field(default="3.0.0", description="版本号")
    timestamp: datetime = Field(default_factory=datetime.now, description="检查时间")


class ErrorResponse(BaseModel):
    """错误响应模型"""
    error: str = Field(..., description="错误信息")
    detail: Optional[str] = Field(default=None, description="错误详情")
    timestamp: datetime = Field(default_factory=datetime.now, description="错误发生时间")


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=32)
    password: str = Field(..., min_length=8, max_length=128)


class RegisterRequest(LoginRequest):
    display_name: Optional[str] = Field(default=None, min_length=1, max_length=64)


class UserResponse(BaseModel):
    user_id: str
    username: str
    display_name: str

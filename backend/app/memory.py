"""
对话记忆模块。

管理进程内会话缓存，并以原子文件替换的方式持久化聊天历史。
"""

import json
import logging
import os
import tempfile
import uuid
from collections import OrderedDict
from datetime import datetime
from threading import RLock
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def _bounded_positive_int(name: str, default: int, minimum: int = 1) -> int:
    """Read a configured limit while retaining a safe default on invalid input."""
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def _current_timestamp() -> str:
    return datetime.now().isoformat()


MAX_CACHED_CONVERSATIONS = _bounded_positive_int("MEMORY_CACHE_MAX_CONVERSATIONS", 100)
MAX_MESSAGES_PER_CONVERSATION = _bounded_positive_int("MEMORY_MAX_MESSAGES", 100, minimum=2)


class ConversationMemoryManager:
    """线程安全的对话记忆管理器。"""

    def __init__(self, storage_dir: str = "./conversation_history"):
        """
        初始化记忆管理器。

        Args:
            storage_dir: 记忆存储目录
        """
        self.storage_dir = storage_dir
        self.memory_store: OrderedDict[str, List[Dict]] = OrderedDict()
        self._lock = RLock()
        os.makedirs(storage_dir, exist_ok=True)

    def _get_memory_file_path(self, conversation_id: str) -> str:
        """获取对话记忆文件路径。"""
        return os.path.join(self.storage_dir, f"{conversation_id}.json")

    def _load_messages_from_file(self, conversation_id: str) -> List[Dict]:
        """从文件加载并规范化消息历史。调用方必须持有 ``self._lock``。"""
        file_path = self._get_memory_file_path(conversation_id)
        if not os.path.exists(file_path):
            return []

        try:
            with open(file_path, "r", encoding="utf-8") as file_handle:
                data = json.load(file_handle)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Unable to load conversation history %s: %s", conversation_id, exc)
            return []

        messages = data.get("messages", [])
        if not isinstance(messages, list):
            return []

        fallback_timestamp = data.get("updated_at")
        if not isinstance(fallback_timestamp, str) or not fallback_timestamp:
            fallback_timestamp = _current_timestamp()

        normalized_messages: List[Dict] = []
        for item in messages[-MAX_MESSAGES_PER_CONVERSATION:]:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            content = item.get("content")
            if role not in {"user", "assistant", "system"} or not isinstance(content, str):
                continue
            timestamp = item.get("timestamp")
            if not isinstance(timestamp, str) or not timestamp:
                timestamp = fallback_timestamp
            normalized_messages.append(
                {"role": role, "content": content, "timestamp": timestamp}
            )

        return normalized_messages

    def _save_messages_to_file(self, conversation_id: str, messages: List[Dict]) -> None:
        """
        原子保存消息历史。调用方必须持有 ``self._lock``。

        临时文件与目标文件位于同一目录，关闭并 fsync 后再通过
        ``os.replace`` 替换，避免进程中断留下半截 JSON。
        """
        file_path = self._get_memory_file_path(conversation_id)
        temporary_path: Optional[str] = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.storage_dir,
                prefix=".conversation-",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_path = temporary_file.name
                json.dump(
                    {
                        "conversation_id": conversation_id,
                        "updated_at": _current_timestamp(),
                        "messages": messages,
                    },
                    temporary_file,
                    ensure_ascii=False,
                    indent=2,
                )
                temporary_file.flush()
                os.fsync(temporary_file.fileno())

            os.replace(temporary_path, file_path)
            temporary_path = None
        finally:
            if temporary_path is not None:
                try:
                    os.remove(temporary_path)
                except FileNotFoundError:
                    pass

    @staticmethod
    def _message(role: str, content: str, timestamp: str) -> Dict:
        return {"role": role, "content": content, "timestamp": timestamp}

    def _get_or_create_memory_locked(
        self, conversation_id: Optional[str] = None
    ) -> tuple[str, List[Dict]]:
        if conversation_id is None:
            conversation_id = str(uuid.uuid4())

        memory = self.memory_store.get(conversation_id)
        if memory is None:
            memory = self._load_messages_from_file(conversation_id)

            self.memory_store[conversation_id] = memory
            while len(self.memory_store) > MAX_CACHED_CONVERSATIONS:
                self.memory_store.popitem(last=False)
        else:
            self.memory_store.move_to_end(conversation_id)

        return conversation_id, memory

    def get_or_create_memory(
        self, conversation_id: Optional[str] = None
    ) -> tuple[str, List[Dict]]:
        """获取或创建对话记忆，并刷新其 LRU 位置。"""
        with self._lock:
            return self._get_or_create_memory_locked(conversation_id)

    def _persist_memory_locked(self, conversation_id: str) -> None:
        memory = self.memory_store.get(conversation_id)
        if memory is None:
            return

        if len(memory) > MAX_MESSAGES_PER_CONVERSATION:
            del memory[:-MAX_MESSAGES_PER_CONVERSATION]
        self._save_messages_to_file(conversation_id, memory)

    def _append_and_persist_locked(self, conversation_id: str, messages: list) -> None:
        _, memory = self._get_or_create_memory_locked(conversation_id)
        original_messages = list(memory)
        try:
            memory.extend(messages)
            self._persist_memory_locked(conversation_id)
        except Exception:
            memory[:] = original_messages
            raise

    def add_user_message(self, conversation_id: str, message: str) -> None:
        """添加并持久化一条用户消息。"""
        with self._lock:
            self._append_and_persist_locked(
                conversation_id,
                [self._message("user", message, _current_timestamp())],
            )

    def add_ai_message(self, conversation_id: str, message: str) -> None:
        """添加并持久化一条 AI 消息。"""
        with self._lock:
            self._append_and_persist_locked(
                conversation_id,
                [self._message("assistant", message, _current_timestamp())],
            )

    def add_turn(
        self,
        conversation_id: str,
        user_message: str,
        ai_message: str,
    ) -> None:
        """在同一临界区内追加并一次性持久化完整的一轮对话。"""
        with self._lock:
            self._append_and_persist_locked(
                conversation_id,
                [
                    self._message("user", user_message, _current_timestamp()),
                    self._message("assistant", ai_message, _current_timestamp()),
                ],
            )

    def get_history(self, conversation_id: str) -> List[Dict]:
        """获取对话历史。"""
        with self._lock:
            _, memory = self._get_or_create_memory_locked(conversation_id)
            return [dict(message) for message in memory]

    def _persist_memory(self, conversation_id: str) -> None:
        """将当前内存快照持久化，失败时恢复原内存状态。"""
        with self._lock:
            memory = self.memory_store.get(conversation_id)
            original_messages = list(memory) if memory else None
            try:
                self._persist_memory_locked(conversation_id)
            except Exception:
                if memory is not None and original_messages is not None:
                    memory[:] = original_messages
                raise

    def clear_memory(self, conversation_id: str) -> bool:
        """清除缓存和持久化历史，包括尚未载入缓存的冷会话。"""
        with self._lock:
            existed = conversation_id in self.memory_store
            file_path = self._get_memory_file_path(conversation_id)
            try:
                os.remove(file_path)
                existed = True
            except FileNotFoundError:
                pass

            memory = self.memory_store.pop(conversation_id, None)
            if memory is not None:
                memory.clear()
            return existed


_memory_manager: Optional[ConversationMemoryManager] = None
_memory_manager_lock = RLock()


def get_memory_manager() -> ConversationMemoryManager:
    """线程安全地获取全局记忆管理器实例。"""
    global _memory_manager
    if _memory_manager is None:
        with _memory_manager_lock:
            if _memory_manager is None:
                _memory_manager = ConversationMemoryManager()
    return _memory_manager

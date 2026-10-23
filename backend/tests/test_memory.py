import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from app.memory import ConversationMemoryManager


class ConversationMemoryManagerTests(unittest.TestCase):
    """记忆管理器的确定性单元测试（不依赖 LLM / 数据库）。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(dir=os.path.dirname(__file__))
        self.manager = ConversationMemoryManager(storage_dir=self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_add_and_reload_roundtrip_preserves_timestamps(self):
        self.manager.add_turn("conv1", "你好", "你好！有什么可以帮您？")

        history = self.manager.get_history("conv1")
        self.assertEqual([message["role"] for message in history], ["user", "assistant"])
        self.assertEqual(history[0]["content"], "你好")
        self.assertTrue(history[0]["timestamp"])
        self.assertTrue(history[1]["timestamp"])

        # 模拟服务重启：时间戳和内容都必须原样恢复。
        reloaded = ConversationMemoryManager(storage_dir=self._tmp.name)
        self.assertEqual(reloaded.get_history("conv1"), history)

    def test_add_turn_persists_once(self):
        with patch.object(
            self.manager,
            "_save_messages_to_file",
            wraps=self.manager._save_messages_to_file,
        ) as save:
            self.manager.add_turn("conv2", "查询订单", "订单信息...")

        self.assertEqual(save.call_count, 1)
        history = self.manager.get_history("conv2")
        self.assertEqual(
            [(item["role"], item["content"]) for item in history],
            [("user", "查询订单"), ("assistant", "订单信息...")],
        )

    def test_clear_memory_removes_warm_store_and_file(self):
        self.manager.add_user_message("conv3", "会被清除的消息")

        self.assertTrue(self.manager.clear_memory("conv3"))
        self.assertFalse(self.manager.clear_memory("conv3"))
        self.assertEqual(self.manager.get_history("conv3"), [])

    def test_clear_memory_removes_cold_file(self):
        self.manager.add_turn("cold", "用户消息", "助手回复")
        memory_file = self.manager._get_memory_file_path("cold")
        self.assertTrue(os.path.exists(memory_file))

        reloaded = ConversationMemoryManager(storage_dir=self._tmp.name)
        self.assertNotIn("cold", reloaded.memory_store)
        self.assertTrue(reloaded.clear_memory("cold"))
        self.assertFalse(os.path.exists(memory_file))
        self.assertFalse(reloaded.clear_memory("cold"))

    def test_missing_history_returns_empty(self):
        self.assertEqual(self.manager.get_history("no_such_conversation"), [])

    def test_concurrent_turns_do_not_interleave_or_corrupt_file(self):
        def add_turn(index: int) -> None:
            self.manager.add_turn(
                "shared",
                f"user-{index}",
                f"assistant-{index}",
            )

        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(add_turn, range(20)))

        history = self.manager.get_history("shared")
        self.assertEqual(len(history), 40)
        for index in range(0, len(history), 2):
            user_message = history[index]
            assistant_message = history[index + 1]
            self.assertEqual(user_message["role"], "user")
            self.assertEqual(assistant_message["role"], "assistant")
            self.assertEqual(
                user_message["content"].removeprefix("user-"),
                assistant_message["content"].removeprefix("assistant-"),
            )

        reloaded = ConversationMemoryManager(storage_dir=self._tmp.name)
        self.assertEqual(reloaded.get_history("shared"), history)

    def test_failed_atomic_replace_keeps_previous_file_and_memory(self):
        self.manager.add_turn("atomic", "before", "saved")
        history_before = self.manager.get_history("atomic")
        file_path = self.manager._get_memory_file_path("atomic")
        with open(file_path, "rb") as file_handle:
            file_before = file_handle.read()

        with patch("app.memory.os.replace", side_effect=OSError("replace failed")):
            with self.assertRaises(OSError):
                self.manager.add_turn("atomic", "after", "not saved")

        self.assertEqual(self.manager.get_history("atomic"), history_before)
        with open(file_path, "rb") as file_handle:
            self.assertEqual(file_handle.read(), file_before)

    def test_memory_cache_is_lru_bounded(self):
        with patch("app.memory.MAX_CACHED_CONVERSATIONS", 2):
            self.manager.get_history("first")
            self.manager.get_history("second")
            self.manager.get_history("first")
            self.manager.get_history("third")

        self.assertEqual(list(self.manager.memory_store), ["first", "third"])


if __name__ == "__main__":
    unittest.main()

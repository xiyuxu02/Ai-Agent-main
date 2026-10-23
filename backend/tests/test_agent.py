import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from langchain_core.messages import AIMessage, AIMessageChunk

from app import agent as agent_module


class _RecordingMemory:
    def __init__(self):
        self.turns = []

    def get_history(self, conversation_id):
        history = []
        for saved_conversation_id, user_message, ai_message in self.turns:
            if saved_conversation_id == conversation_id:
                history.extend(
                    [
                        {"role": "user", "content": user_message},
                        {"role": "assistant", "content": ai_message},
                    ]
                )
        return history

    def add_turn(self, conversation_id, user_message, ai_message):
        self.turns.append((conversation_id, user_message, ai_message))


class _ConcurrencyProbeExecutor:
    def __init__(self):
        self._state_lock = threading.Lock()
        self.active = 0
        self.max_active = 0

    def _enter(self):
        with self._state_lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)

    def _exit(self):
        with self._state_lock:
            self.active -= 1

    def invoke(self, payload, config=None):
        self._enter()
        try:
            time.sleep(0.05)
            user_text = payload["messages"][-1].content
            return {"messages": [*payload["messages"], AIMessage(content=f"reply:{user_text}")]}
        finally:
            self._exit()

    def stream(self, payload, **_kwargs):
        self._enter()
        try:
            time.sleep(0.05)
            user_text = payload["messages"][-1].content
            yield AIMessageChunk(content=f"reply:{user_text}"), {}
        finally:
            self._exit()


class CustomerServiceAgentConcurrencyTests(unittest.TestCase):
    def _build_agent(self, executor, memory):
        with patch.object(agent_module, "get_llm", return_value=object()), patch.object(
            agent_module, "get_all_tools", return_value=[]
        ), patch.object(
            agent_module.CustomerServiceAgent,
            "_create_agent",
            return_value=executor,
        ):
            return agent_module.CustomerServiceAgent(
                conversation_id="shared",
                user_id="TEST_USER",
                memory_manager=memory,
            )

    def test_invoke_and_stream_are_serialized_for_one_conversation(self):
        executor = _ConcurrencyProbeExecutor()
        memory = _RecordingMemory()
        first_agent = self._build_agent(executor, memory)
        second_agent = self._build_agent(executor, memory)
        start = threading.Barrier(3)

        def invoke():
            start.wait()
            return first_agent.invoke("normal")

        def stream():
            start.wait()
            return list(second_agent.stream("stream"))

        with ThreadPoolExecutor(max_workers=2) as pool:
            invoke_future = pool.submit(invoke)
            stream_future = pool.submit(stream)
            start.wait()
            invoke_result = invoke_future.result()
            stream_result = stream_future.result()

        self.assertTrue(invoke_result["success"])
        self.assertEqual(stream_result, ["reply:stream"])
        self.assertEqual(executor.max_active, 1)
        self.assertCountEqual(
            memory.turns,
            [
                ("shared", "normal", "reply:normal"),
                ("shared", "stream", "reply:stream"),
            ],
        )


class AgentCacheTests(unittest.TestCase):
    def setUp(self):
        with agent_module._agent_cache_lock:
            agent_module._agent_cache.clear()

    def tearDown(self):
        with agent_module._agent_cache_lock:
            agent_module._agent_cache.clear()

    @staticmethod
    def _factory(created):
        def create(*, conversation_id, user_id):
            value = object()
            created.append((conversation_id, user_id, value))
            return value

        return create

    def test_cache_uses_lru_eviction(self):
        created = []
        with patch.object(agent_module, "_AGENT_CACHE_MAX_SIZE", 2), patch.object(
            agent_module, "_AGENT_CACHE_TTL_SECONDS", 1000
        ), patch.object(
            agent_module,
            "CustomerServiceAgent",
            side_effect=self._factory(created),
        ), patch.object(
            agent_module.time,
            "monotonic",
            side_effect=[0.0, 1.0, 2.0, 3.0],
        ):
            first = agent_module.get_or_create_agent("first", "TEST_USER")
            agent_module.get_or_create_agent("second", "TEST_USER")
            self.assertIs(agent_module.get_or_create_agent("first", "TEST_USER"), first)
            agent_module.get_or_create_agent("third", "TEST_USER")

        self.assertEqual(
            list(agent_module._agent_cache),
            ["TEST_USER:first", "TEST_USER:third"],
        )

    def test_cache_recreates_expired_agent(self):
        created = []
        with patch.object(agent_module, "_AGENT_CACHE_TTL_SECONDS", 10), patch.object(
            agent_module,
            "CustomerServiceAgent",
            side_effect=self._factory(created),
        ), patch.object(
            agent_module.time,
            "monotonic",
            side_effect=[0.0, 10.0],
        ):
            original = agent_module.get_or_create_agent("conversation", "TEST_USER")
            replacement = agent_module.get_or_create_agent("conversation", "TEST_USER")

        self.assertIsNot(original, replacement)
        self.assertEqual(len(created), 2)


if __name__ == "__main__":
    unittest.main()

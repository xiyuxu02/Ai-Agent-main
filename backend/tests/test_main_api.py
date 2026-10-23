import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from app.auth import AuthenticatedUser, require_current_user
from app.main import APP_VERSION, app, create_conversation_token


class ChatApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.user = AuthenticatedUser("TEST_USER", "tester", "测试用户")
        app.dependency_overrides[require_current_user] = lambda: cls.user
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()

    def test_health_exposes_current_version(self):
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["version"], APP_VERSION)

    @patch("app.main.get_or_create_agent")
    def test_first_chat_issues_conversation_credentials_and_tool_trace(self, get_agent):
        agent = Mock()
        agent.invoke.return_value = {
            "success": True,
            "message": "订单正在处理中。",
            "tool_used": ["get_order_status"],
        }
        get_agent.return_value = agent

        response = self.client.post("/api/chat", json={"message": "查询订单"})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["conversation_id"])
        self.assertTrue(body["conversation_token"])
        self.assertTrue(body["request_id"])
        self.assertEqual(body["tools_used"], ["get_order_status"])
        agent.invoke.assert_called_once()

    def test_existing_conversation_requires_matching_token(self):
        response = self.client.post(
            "/api/chat",
            json={"message": "继续", "conversation_id": "conversation-1"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"], "Conversation access denied.")

    @patch("app.main.get_or_create_agent")
    def test_existing_conversation_accepts_matching_token(self, get_agent):
        agent = Mock()
        agent.invoke.return_value = {
            "success": True,
            "message": "已继续。",
            "tool_used": [],
        }
        get_agent.return_value = agent
        conversation_id = "conversation-1"

        response = self.client.post(
            "/api/chat",
            headers={"X-Conversation-Token": create_conversation_token(conversation_id, self.user.user_id)},
            json={"message": "继续", "conversation_id": conversation_id},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["conversation_id"], conversation_id)

    @patch("app.main.get_or_create_agent")
    def test_streaming_chat_emits_token_events(self, get_agent):
        agent = Mock()
        agent.stream.return_value = iter(["你", "好"])
        get_agent.return_value = agent

        response = self.client.post("/api/chat/stream", json={"message": "你好"})

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/event-stream", response.headers["content-type"])
        self.assertIn("event: conversation", response.text)
        self.assertIn('"delta": "你"', response.text)
        self.assertIn('"delta": "好"', response.text)
        self.assertIn("event: done", response.text)


if __name__ == "__main__":
    unittest.main()

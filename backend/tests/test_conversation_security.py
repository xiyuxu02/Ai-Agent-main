import unittest

from fastapi import HTTPException

from app.main import create_conversation_token, require_conversation_access


class ConversationAccessTests(unittest.TestCase):
    def test_token_is_stable_for_the_same_conversation(self):
        first = create_conversation_token("conversation-1", "user-1")
        second = create_conversation_token("conversation-1", "user-1")
        self.assertEqual(first, second)
        self.assertNotEqual(first, create_conversation_token("conversation-2", "user-1"))
        self.assertNotEqual(first, create_conversation_token("conversation-1", "user-2"))

    def test_valid_token_grants_access(self):
        token = create_conversation_token("conversation-1", "user-1")
        self.assertIsNone(require_conversation_access("conversation-1", token, "user-1"))

    def test_missing_or_wrong_token_is_rejected(self):
        for token in (None, "invalid-token"):
            with self.subTest(token=token):
                with self.assertRaises(HTTPException) as raised:
                    require_conversation_access("conversation-1", token, "user-1")
                self.assertEqual(raised.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()

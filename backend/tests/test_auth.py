import unittest

from app.auth import hash_password, normalize_username, validate_password, verify_password


class PasswordSecurityTests(unittest.TestCase):
    def test_password_hash_is_salted_and_verifiable(self):
        first = hash_password("SafePass123!")
        second = hash_password("SafePass123!")
        self.assertNotEqual(first, second)
        self.assertNotIn("SafePass123!", first)
        self.assertTrue(verify_password("SafePass123!", first))
        self.assertFalse(verify_password("wrong-password", first))

    def test_account_input_validation(self):
        self.assertEqual(normalize_username("  test_user  "), "test_user")
        with self.assertRaises(ValueError):
            normalize_username("a b")
        with self.assertRaises(ValueError):
            validate_password("short")


if __name__ == "__main__":
    unittest.main()

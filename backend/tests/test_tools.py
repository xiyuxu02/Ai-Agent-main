import unittest

from app.tools import UnsafeExpressionError, safe_calculate


class SafeCalculateTests(unittest.TestCase):
    def test_evaluates_supported_arithmetic(self):
        self.assertEqual(safe_calculate("(10 + 20) * 3 / 2"), 45)
        self.assertEqual(safe_calculate("-2.5 + 4"), 1.5)

    def test_rejects_python_execution_features(self):
        for expression in (
            "__import__('os').system('whoami')",
            "(lambda: 1)()",
            "2 ** 20",
            "[1, 2, 3]",
        ):
            with self.subTest(expression=expression):
                with self.assertRaises(UnsafeExpressionError):
                    safe_calculate(expression)

    def test_rejects_excessively_complex_expression(self):
        with self.assertRaises(UnsafeExpressionError):
            safe_calculate("+".join(["1"] * 80))


if __name__ == "__main__":
    unittest.main()

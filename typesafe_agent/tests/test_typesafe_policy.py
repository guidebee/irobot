import unittest

from typesafe_agent.policy import TypeSafePolicy


class TypeSafePolicyImportGuardTests(unittest.TestCase):
    def test_raises_a_clear_error_without_the_sdk_installed(self):
        try:
            import typesafe_sdk  # noqa: F401
        except ImportError:
            pass
        else:
            self.skipTest("typesafe-sdk is installed in this environment")
        with self.assertRaisesRegex(RuntimeError, "typesafe-sdk is not installed"):
            TypeSafePolicy()


if __name__ == "__main__":
    unittest.main()

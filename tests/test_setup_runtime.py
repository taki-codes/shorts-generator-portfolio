import importlib.util
import unittest
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "scripts/check_runtime.py"
spec = importlib.util.spec_from_file_location("runtime_preflight", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class RuntimeCompatibilityTests(unittest.TestCase):
    def test_regular_supported_python_is_accepted(self):
        for version in ((3, 11, 9), (3, 12, 14), (3, 13, 0)):
            self.assertTrue(module.compatibility(version, False, 64)[0])

    def test_free_threaded_is_rejected_even_if_gil_enabled_at_runtime(self):
        # Py_GIL_DISABLED reflects the binary ABI, not a runtime -X gil switch.
        self.assertFalse(module.compatibility((3, 13, 0), True, 64)[0])

    def test_unsupported_version_or_architecture_is_rejected(self):
        for version, bits in (((3, 10, 0), 64), ((3, 14, 0), 64), ((3, 13, 0), 32)):
            self.assertFalse(module.compatibility(version, False, bits)[0])


if __name__ == "__main__":
    unittest.main()

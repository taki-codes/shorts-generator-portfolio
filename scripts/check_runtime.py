"""Setup preflight. Reject incompatible binaries before any dependency build."""
import json
import struct
import sys
import sysconfig

SUPPORTED = ((3, 13), (3, 12), (3, 11))


def compatibility(version, free_threaded, bits):
    if tuple(version[:2]) not in SUPPORTED:
        return False, "Use standard CPython 3.11, 3.12, or 3.13."
    if free_threaded:
        return False, "Free-threaded Python is not supported by this setup. Select the regular binary."
    if bits != 64:
        return False, "Use a 64-bit Python installation."
    return True, "compatible"


def main():
    version = sys.version_info[:3]
    free_threaded = bool(sysconfig.get_config_var("Py_GIL_DISABLED"))
    bits = struct.calcsize("P") * 8
    ok, reason = compatibility(version, free_threaded, bits)
    print(json.dumps({"compatible": ok, "reason": reason, "version": list(version),
                      "free_threaded": free_threaded, "bits": bits, "executable": sys.executable}))
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())

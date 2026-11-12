import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_repo import FORBIDDEN, ROOT, check_pins, env  # noqa: E402


class CheckRepoTests(unittest.TestCase):
    def setUp(self):
        self.values = env(ROOT / "config/kernel.env")

    def test_repository_pins_are_valid(self):
        patches = sorted((ROOT / "patches").glob("*.patch"))
        self.assertEqual(check_pins(self.values, patches), [])

    def test_moving_or_malformed_pins_are_rejected(self):
        for key, value in (("RUBY_SHA", "main"), ("DXB_SHA", "abc"), ("RUBY_PATCHSET_SHA256", "0" * 63),
                           ("BASE_REPO", "http://github.com/a/b"), ("XCODE_VERSION", "latest"),
                           ("KERNEL_EXPECT_EXEC_DATA", "nothex")):
            with self.subTest(key=key):
                self.assertTrue(check_pins({**self.values, key: value}, []))

    def test_unknown_and_missing_keys(self):
        self.assertTrue(check_pins({**self.values, "EXTRA": "1"}, []))
        missing = dict(self.values)
        missing.pop("DXB_SHA")
        self.assertTrue(check_pins(missing, []))

    def test_k0_gate_equals_ruby_until_a_g54_patch_exists(self):
        changed = {**self.values, "G54_PATCHSET_SHA256": "1" * 64}
        self.assertTrue(check_pins(changed, []))
        self.assertEqual(check_pins(changed, [Path("patches/0001-g54.patch")]), [])

    def test_forbidden_material(self):
        for name in ("boot.img", "iPhone.ipsw", "KDK_13.5.kdk", "x.dmg", "dump.bin", "a.dtb", "key.pem"):
            with self.subTest(name=name):
                self.assertTrue(FORBIDDEN.search(name))
        self.assertIsNone(FORBIDDEN.search("0001-g54-framebuffer.patch"))


if __name__ == "__main__":
    unittest.main()

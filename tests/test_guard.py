"""Guard tests. Fake addresses and tokens are assembled at runtime so none of them is ever
committed as a literal (the guard itself would, correctly, reject this file otherwise).
Run: python3 -m unittest -v tests.test_guard"""
import os
import random
import string
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))
import guard  # noqa: E402

rnd = random.Random(1570)
alnum = string.ascii_letters + string.digits


def r(n, chars=alnum):
    return "".join(rnd.choice(chars) for _ in range(n))


def dotted(*parts):
    return ".".join(map(str, parts))


def kinds(text):
    return [k for _, k, _ in guard.scan_text(text)]


class Guard(unittest.TestCase):
    def test_rejects_any_unknown_ipv4(self):
        for ip in (dotted(198, 51, 100, 23), dotted(203, 0, 113, 7), dotted(10, 0, 0, 1), dotted(84, 1, 2, 3)):
            self.assertEqual(kinds(f"server = {ip}:8080"), ["ipv4 address"], ip)

    def test_allows_loopback_and_github_pages(self):
        for ip in (dotted(127, 0, 0, 1), dotted(0, 0, 0, 0), dotted(185, 199, 108, 153)):
            self.assertEqual(kinds(f"host {ip}"), [], ip)

    def test_ignores_versions_and_prices(self):
        self.assertEqual(kinds("lightweight-charts@4.2.3, v1.0.9, price 78639.57,79019.86 and 999.1.1.1"), [])

    def test_rejects_token_patterns(self):
        cases = {
            "github token": "gh" + "p_" + r(36),
            "github fine-grained token": "github" + "_pat_" + r(82, alnum + "_"),
            "slack token": "xo" + "xb-" + r(12, string.digits) + "-" + r(24),
            "aws access key id": "AK" + "IA" + r(16, string.ascii_uppercase + string.digits),
            "api key (sk-)": "s" + "k-proj-" + "Ab1" + r(45),
            "telegram bot token": r(9, string.digits) + ":A" + "A" + r(33, alnum + "_-"),
            "private key": "-----BEGIN RSA " + "PRIVATE KEY-----",
        }
        for kind, tok in cases.items():
            self.assertIn(kind, kinds(f"x = '{tok}'"), kind)

    def test_word_slugs_are_not_keys(self):
        self.assertEqual(kinds("article sk-hynix-recontracting-to-repricing"), [])

    def test_values_are_masked_in_output(self):
        ip = dotted(198, 51, 100, 23)
        (_, _, shown), = guard.scan_text(ip)
        self.assertNotIn(ip, shown)

    def test_cli_rejects_a_file_and_passes_a_clean_one(self):
        with tempfile.TemporaryDirectory() as d:
            bad, good = os.path.join(d, "bad.txt"), os.path.join(d, "good.txt")
            with open(bad, "w") as f:
                f.write("token " + "gh" + "p_" + r(36) + "\nhost " + dotted(198, 51, 100, 23) + "\n")
            with open(good, "w") as f:
                f.write("nothing to see\n")
            run = lambda p: subprocess.run([sys.executable, os.path.join(HERE, "tools", "guard.py"), p], capture_output=True, text=True)
            b, g = run(bad), run(good)
            self.assertEqual(b.returncode, 1)
            self.assertIn("2 hits: REJECTED", b.stdout)
            self.assertEqual(g.returncode, 0)


if __name__ == "__main__":
    unittest.main()

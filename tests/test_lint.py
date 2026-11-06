"""The code passes ruff's correctness checks (ruff.toml): undefined names, unused imports, syntax errors."""

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@unittest.skipUnless(importlib.util.find_spec('ruff'), 'ruff is not installed (pip install -r requirements-dev.txt)')
class LintTest(unittest.TestCase):
    def test_ruff_correctness_checks_pass(self):
        result = subprocess.run(
            [sys.executable, '-m', 'ruff', 'check', 'src', 'tests', '--output-format', 'concise'],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()

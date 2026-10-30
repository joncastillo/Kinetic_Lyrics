"""Subprocess helpers: plain commands, and Python modules from src/ run in a child process."""
from __future__ import annotations
import os
import subprocess
import sys

from core.paths import SRC_ROOT


def run(command):
    return subprocess.run(command, check=True, capture_output=True, text=True,
                          encoding='utf-8', errors='replace').stdout


def module_command(module, *args, python=None):
    """`python -u -P -m module args`; pass `env=module_env()` so the child can import from src/.

    -P keeps the working directory off the import path, so a project folder that happens to hold
    a `models` or `render` folder can never shadow these packages.
    """
    return [str(python or sys.executable), '-u', '-P', '-m', module, *map(str, args)]


def module_env(env=None):
    """The environment (default: this process's) with src/ first on PYTHONPATH."""
    env = dict(os.environ if env is None else env)
    env['PYTHONPATH'] = os.pathsep.join([str(SRC_ROOT)]+([env['PYTHONPATH']] if env.get('PYTHONPATH') else []))
    return env

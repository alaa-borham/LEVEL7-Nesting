import os
import subprocess
import sys

from conftest import SCB


def test_cli_info_on_non_utf8_console():
    """Regression: Windows consoles (cp1252) crashed on Arabic part names."""
    env = dict(os.environ, PYTHONIOENCODING="cp1252")
    r = subprocess.run([sys.executable, "-m", "level7.cli", "info", SCB], capture_output=True, env=env)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")
    assert "front" in r.stdout.decode("utf-8", "replace")

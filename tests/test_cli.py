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


def test_scb_missing_sizes_are_loaded_from_model(tmp_path):
    import shutil
    from level7 import service
    from conftest import MDL, SCB
    proj, _ = service.open_any(SCB)
    for p in proj.pieces:                      # simulate a GRAFIS SCB that stores only the nested size
        for s in list(p.sizes):
            if s != "44":
                del p.sizes[s]
    assert service.missing_geometry(proj, ["40"])
    shutil.copy(SCB, tmp_path / "m.scb")
    shutil.copy(MDL, tmp_path / "other name.mdl")      # MODEL name inside the SCB differs: found by part IDs
    mdl = service.find_model_file(str(tmp_path / "m.scb"), proj)
    assert mdl and mdl.endswith("other name.mdl")
    assert service.supplement_from_model(proj, mdl) > 0
    assert not service.missing_geometry(proj, ["40", "44"])

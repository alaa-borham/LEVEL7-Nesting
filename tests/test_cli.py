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


def test_several_order_models_in_one_marker(tmp_path):
    """LEVEL7 MTM: orders of one customer on the same fabric nested together (nest A --with B SIZE=QTY); every
    piece says its order, also in the cutting files."""
    import json
    import shutil
    from collections import Counter
    from conftest import MDL
    from level7.project_storage.store import load_project
    a, b = tmp_path / "Order-x__9-53-1_2.mdl", tmp_path / "Order-x__9-53-2_2.mdl"
    shutil.copy(MDL, a)
    shutil.copy(MDL, b)                                 # two orders of the same measurements: still two jobs
    out = tmp_path / "both.l7n"
    r = subprocess.run([sys.executable, "-m", "level7.cli", "nest", str(a), "--width", "1500", "--time", "3",
                        "--engine", "builtin", "--sizes", "44=1", "--with", str(b), "44=2", "-o", str(out)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    m = load_project(str(out)).markers[-1]
    by = Counter(pl.size for pl in m.placements if pl.placed)
    assert set(by) == {"9-53-1_2:44", "9-53-2_2:44"} and by["9-53-2_2:44"] == 2 * by["9-53-1_2:44"]
    proj = load_project(str(out))
    texts = {lb.text for p in proj.pieces for g in p.sizes.values() for lb in g.labels}
    assert {"9-53-1/2", "9-53-2/2"} <= texts                # the order on each piece (no "_" in the plotter font)
    info = subprocess.run([sys.executable, "-m", "level7.cli", "info", "--json", str(a)], capture_output=True,
                          text=True)
    assert "with" in json.loads(info.stdout)["features"]
    plt = tmp_path / "both.plt"
    assert subprocess.run([sys.executable, "-m", "level7.cli", "export", str(out), "--format", "plt",
                           "--plt-preset", "algotex_grafis", "-o", str(plt)]).returncode == 0 and plt.exists()


def test_a_base_size_belongs_to_its_model_in_a_session_of_several():
    """Order models have one base size ("base:__HN49_0"); in a session it is "base:<tag>:__HN49_0" — it was
    taken for another model's and nothing was nested."""
    from types import SimpleNamespace
    from level7.service import of_model
    p = SimpleNamespace(model="9-53-1_2")
    assert of_model(p, "base:9-53-1_2:__HN49_0") and of_model(p, "9-53-1_2:44")
    assert not of_model(p, "base:9-53-2_2:__HN49_0") and not of_model(p, "9-53-2_2:44")
    assert of_model(SimpleNamespace(model=""), "44")

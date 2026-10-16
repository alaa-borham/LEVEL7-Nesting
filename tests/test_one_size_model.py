"""A GRAFIS model with only its base size (e.g. an order model written by LEVEL7 MTM) lists that size, so a
marker saved from it can be nested again from the window."""
import json
import os
import zipfile

import pytest

from level7.project_storage.store import load_project
from level7.readers.grafis import read_grafis


def _one_size_mdl(tmp_path):
    """The sample MDL with its #GRDTAB reduced to the base entry (same container, text block rewritten)."""
    from level7.formats.grafis.container import read_container
    from level7.formats.grafis.writer import ENC, rebuild_container
    src = next((os.path.join(d, f) for d in ("samples", "examples") if os.path.isdir(d)
                for f in os.listdir(d) if f.lower().endswith(".mdl")), None)
    if src is None:
        pytest.skip("no sample MDL")
    data = open(src, "rb").read()
    cont = read_container(src)
    tb = cont.by_id()[(2, 1, 0, 0)]
    text = tb.payload.rstrip(b"\0").decode(ENC)
    lines, out, in_grd, kept = text.split("\r\n"), [], False, False
    for ln in lines:
        if ln.startswith("#"):
            in_grd = ln.strip() == "#GRDTAB"
            out.append(ln)
            continue
        if in_grd and ln.strip().startswith(">"):
            if "__" in ln and not kept:
                out.append(ln.split("=>")[0].rstrip())
                kept = True
            continue
        out.append(ln)
    if not kept:
        pytest.skip("sample MDL has no __ base entry")
    new = rebuild_container(data, cont, {(2, 1, 0, 0): "\r\n".join(out).encode(ENC) + b"\0"})
    p = tmp_path / "one-size.mdl"
    p.write_bytes(new)
    return str(p)


def test_one_size_model_lists_its_base_size(tmp_path):
    r = read_grafis(_one_size_mdl(tmp_path))
    proj = r.project
    assert len(proj.size_names) == 1 and proj.size_names[0].startswith("base:__")


def test_old_l7n_without_size_names_gets_the_size_of_its_order(tmp_path):
    from level7.model import Project
    from level7.project_storage.store import save_project
    p = tmp_path / "old.l7n"
    save_project(Project(name="x"), str(p))
    z = zipfile.ZipFile(p)
    d = json.loads(z.read("project.json"))
    d["project"]["size_names"] = []
    d["project"]["cut_order"] = {"size_quantities": {"base:__HN40_0": 1}, "piece_counts": {}}
    with zipfile.ZipFile(p, "w") as z2:
        z2.writestr("project.json", json.dumps(d))
    assert load_project(str(p)).size_names == ["base:__HN40_0"]

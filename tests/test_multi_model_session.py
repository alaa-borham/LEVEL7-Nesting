"""Several model files in one session: sizes are prefixed with their model, quantities apply per model, and
pieces of all models are nested into one valid marker."""
import os

from conftest import SCB

from level7 import service
from level7.model import FabricSettings, NestSettings
from level7.nesting.engine import build_items
from level7.project_storage.store import load_project, save_project

HERE = os.path.dirname(os.path.abspath(__file__))
VEST = os.path.join(HERE, "..", "samples", "vest2027", "OUT vest2027-M1-M.scb")


def session():
    p, _ = service.open_any(SCB)
    service.add_model(p, VEST)
    return p


def test_sizes_are_prefixed_per_model_and_markers_kept():
    p = session()
    tags = service.model_tags(p)
    assert tags == ["Neay blue pants-44", "OUT vest2027-M1-M"]
    assert "Neay blue pants-44:44" in p.size_names and "OUT vest2027-M1-M:M" in p.size_names
    assert all(k.startswith(pc.model + ":") or k.startswith("base:" + pc.model + ":")
               for pc in p.pieces for k in pc.sizes)
    assert len(p.markers) == 2 and all(pl.size.split(":")[0] in tags for m in p.markers for pl in m.placements)
    assert service.size_label(tags, "OUT vest2027-M1-M:M") == "2·M"


def test_quantities_apply_to_their_own_model_only():
    p = session()
    co = p.cut_order
    q = {s: 0 for s in p.size_names}
    q["Neay blue pants-44:44"] = 1
    q["OUT vest2027-M1-M:M"] = 1
    items, unplaced, _ = build_items(p, q, co.piece_counts, FabricSettings(width=1500.0), NestSettings(), None, "O")
    assert not unplaced                                  # no "size of the other model not available"
    models = {p.piece(it.piece_uid).model for it in items}
    assert models == {"Neay blue pants-44", "OUT vest2027-M1-M"} and len(items) == 27


def test_one_marker_from_two_models_valid_and_saved(tmp_path):
    p = session()
    co = p.cut_order
    co.size_quantities = {s: 0 for s in p.size_names}
    co.size_quantities["Neay blue pants-44:44"] = 1
    co.size_quantities["OUT vest2027-M1-M:M"] = 1
    co.material = "O"
    m, info = service.run_nesting(p, FabricSettings(width=1500.0), NestSettings(time_limit=6, seed=1), workers=1)
    assert info["validation"].ok and all(pl.placed for pl in m.placements) and len(m.placements) == 27
    p.markers.append(m)
    f = tmp_path / "s.l7n"
    save_project(p, str(f))
    q = load_project(str(f))
    assert service.model_tags(q) == service.model_tags(p) and len(q.markers) == 3


def test_limit_and_duplicate():
    p = session()
    try:
        service.add_model(p, VEST)
        raise AssertionError("same model twice must be refused")
    except ValueError as e:
        assert "already" in str(e)

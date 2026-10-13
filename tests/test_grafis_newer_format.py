"""Newer GRAFIS files (user model vest2027): '>' flagged TLIST lines with the model path after the ID,
alphabetical GRDTAB without references (base entry '__HN44_0' last), more material codes."""
import os

import pytest

from level7.readers.grafis import read_grafis
from level7.validation.checker import validate_marker

HERE = os.path.dirname(os.path.abspath(__file__))
VEST = os.path.join(HERE, "..", "samples", "vest2027")
SCB = os.path.join(VEST, "OUT vest2027-M1-M.scb")
MDL = os.path.join(VEST, "vest2027-M1.mdl")


@pytest.fixture(scope="module")
def scb():
    return read_grafis(SCB)


def test_tlist_with_marker_flag_and_model_path(scb):
    p = scb.project
    assert len(p.pieces) == 24 and sum(1 for x in p.pieces if x.sizes) == 23
    assert not scb.issues
    names = {x.number: x.name for x in p.pieces}
    assert names[14] == "بنضه الامام" and names[22] == "الظهر خارجي"
    mats = sorted({x.material for x in p.pieces if x.production})
    assert mats == ["E", "F", "O", "S"]


def test_base_entry_found_by_name_and_garment_size_order(scb):
    p = scb.project
    assert p.size_names == ["XS", "S", "M", "L", "XL", "2XL", "3XL", "4XL"]
    piece = next(x for x in p.pieces if x.number == 14)
    assert "base:__HN44_0" in piece.sizes and "2XL" in piece.sizes


def test_marker_reproduced_and_valid(scb):
    p = scb.project
    m = p.markers[0]
    assert len(m.placements) == 13 and all(pl.size == "M" for pl in m.placements)
    assert scb.checks["bbox_mismatch"] == [] and scb.checks["area_mismatch"] == []
    assert validate_marker(p, m).ok


def test_mdl_names_with_merged_number_columns():
    p = read_grafis(MDL).project
    assert next(x for x in p.pieces if x.number == 2).name == "basic"
    assert p.size_names == ["XS", "S", "M", "L", "XL", "2XL", "3XL", "4XL"]


def test_unknown_layout_is_reported_not_silently_dropped(tmp_path):
    """A future GRAFIS version: unknown signature variant and an unknown piece-list line give COMPAT notes,
    and everything that is still understood is read."""
    from level7.formats.grafis.textsections import parse_text
    ts = parse_text("#VERSION\r\n1000\r\n#TLIST\r\n ~ 001   name   1 1 O  x O 01 01 ID=0060FB8A01DD5AA1 NEW=\"x\"\r\n"
                    "%% something new %%\r\n".encode("cp1256"))
    assert len(ts.tlist) == 1 and ts.tlist[0].name == "name"          # any flag char, any key="value" after ID
    assert ts.unparsed == {"TLIST": ["%% something new %%"]}
    data = bytearray(open(SCB, "rb").read())
    i = data.find(b"GRAFIS-Modelldatei") + len(b"GRAFIS-Modelldatei")
    data[i:i + 2] = b"VZ"
    f = tmp_path / "future.scb"
    f.write_bytes(bytes(data))
    r = read_grafis(str(f))
    assert any(x.startswith("COMPAT:") and "VZ" in x for x in r.issues)
    assert len(r.project.markers[0].placements) == 13                   # still fully read

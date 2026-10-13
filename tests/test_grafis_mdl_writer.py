"""GRAFIS MDL writer: material / production / copies of the parts, everything else unchanged."""
import os
import struct

import pytest
from conftest import MDL

from level7.formats.grafis.container import grafis_check, read_container
from level7.formats.grafis.mdl_writer import MdlWriteError, decode_material, material_record, write_mdl
from level7.readers.grafis import read_grafis
from level7.service import open_any

VEST = os.path.join(os.path.dirname(MDL), "vest2027", "vest2027-M1.mdl")


@pytest.mark.parametrize("src", [MDL, VEST])
def test_unchanged_session_writes_the_same_file(src, tmp_path):
    proj, _ = open_any(src)
    write_mdl(src, proj, str(tmp_path / "x.mdl"))
    assert (tmp_path / "x.mdl").read_bytes() == open(src, "rb").read()


@pytest.mark.parametrize("src", [MDL, VEST])
def test_material_and_copies_written(src, tmp_path):
    proj, _ = open_any(src)
    co = proj.cut_order
    new = next(p for p in proj.pieces if not p.production and p.material == "O")
    new.material = "F"
    co.piece_counts[new.uid] = (2, 1)
    off = next(p for p in proj.pieces if p.production)
    co.piece_counts[off.uid] = (0, 0)
    out = str(tmp_path / "x.mdl")
    info = write_mdl(src, proj, out)
    assert sorted(info["parts_changed"]) == sorted([new.number, off.number])
    r = read_grafis(out)
    t = {e.number: e for e in r.text.tlist}
    assert (t[new.number].production, t[new.number].material, t[new.number].count, t[new.number].mirrored) == \
        (True, "F", 2, 1)
    assert not t[off.number].production
    a, b = read_container(src).by_id(), read_container(out).by_id()
    assert {k for k in a if a[k].payload != b[k].payload} == \
        {(2, 1, 0, 0), (3, new.number, 6, 6), (3, off.number, 6, 6)}
    rec = decode_material(material_record(b[(3, new.number, 6, 6)].payload, 0))
    assert rec["production"] and (rec["material"], rec["total"], rec["mirrored"], rec["name"]) == \
        ("F", 3, 1, "lining")
    # the part no longer produced keeps its material (GRAFIS keeps it for parts not produced too)
    assert next(p for p in r.project.pieces if p.number == off.number).material == off.material
    data = open(out, "rb").read()
    assert grafis_check(b"\0\0\0\0" + data[4:80]) == struct.unpack_from("<I", data, 0)[0]
    for bid in ((2, 1, 0, 0), (3, new.number, 6, 6), (3, off.number, 6, 6)):
        blk = read_container(out).get(*bid)
        assert grafis_check(b"\0\0\0\0" + data[blk.offset + 4:blk.offset + blk.size]) == blk.check


def test_unknown_material_is_refused(tmp_path):
    proj, _ = open_any(MDL)
    p = next(p for p in proj.pieces if p.production)
    p.material = "D"
    with pytest.raises(MdlWriteError, match="not used by any part"):
        write_mdl(MDL, proj, str(tmp_path / "x.mdl"))
    assert not (tmp_path / "x.mdl").exists()


def test_produced_part_needs_a_material(tmp_path):
    proj, _ = open_any(MDL)
    p = next(p for p in proj.pieces if p.production)
    p.material = None
    with pytest.raises(MdlWriteError, match="needs a material"):
        write_mdl(MDL, proj, str(tmp_path / "x.mdl"))

"""File I/O robustness: Arabic job names in ISO, tolerant project loading, batch file names, CLI errors."""
import json
import os
import zipfile

from conftest import SCB

from level7.service import export_marker, open_any


def test_iso_with_arabic_name_is_written(tmp_path):
    from level7.exporters.iso import ISO_PRESETS
    proj, _ = open_any(SCB)
    path = str(tmp_path / "بنطلون.iso")
    export_marker(proj, proj.markers[0], "iso", path, ISO_PRESETS["bullmer_grafis"]())
    text = open(path, encoding="ascii").read()
    assert text.startswith("H1*") and text.rstrip().endswith("M15*D4*M00*")
    assert not os.path.exists(path + ".part")


def test_iso_empty_marker_ends_job(tmp_path):
    from dataclasses import replace

    from level7.exporters.iso import ISO_PRESETS
    proj, _ = open_any(SCB)
    m = replace(proj.markers[0], placements=[])
    path = str(tmp_path / "empty.iso")
    export_marker(proj, m, "iso", path, ISO_PRESETS["bullmer_grafis"]())
    assert open(path, encoding="ascii").read().rstrip().endswith("M15*D4*M00*")


def test_project_with_unknown_fields_still_loads(tmp_path):
    from level7.project_storage.store import load_project, save_project
    proj, _ = open_any(SCB)
    path = str(tmp_path / "p.l7n")
    save_project(proj, path)
    with zipfile.ZipFile(path) as z:
        doc = json.loads(z.read("project.json"))
    doc["project"]["markers"][0]["fabric"]["future_option"] = 1
    doc["project"]["markers"][0]["placements"][0]["future_flag"] = True
    doc["project"]["nest_settings"]["future_setting"] = "x"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("project.json", json.dumps(doc))
    p2 = load_project(path)
    assert len(p2.markers[0].placements) == len(proj.markers[0].placements)


def test_batch_output_names_unique_and_new_columns(tmp_path):
    from level7 import batch
    lst = tmp_path / "orders.csv"
    lst.write_text("marker,file,size,qty,width,formats,time,بفر طول,انكماش طول\n"
                   f"A/B,{SCB},44,1,1500,plt,3,4,2\nA:B,{SCB},44,1,1500,plt,3,,\n", encoding="utf-8")
    orders = batch.parse_orders(str(lst))
    assert orders[0].buffer_x == 4 and orders[0].shrink_x == 2
    batch.run_batch(orders, str(tmp_path / "out"), default_time=3)
    assert [o.status for o in orders] == ["done", "done"], [o.message for o in orders]
    stems = {os.path.basename(x) for o in orders for x in o.outputs}
    assert {"A_B.l7n", "A_B_2.l7n"} <= stems


def test_cli_export_without_marker_reports_error(tmp_path, capsys):
    from level7.cli import main
    from level7.project_storage.store import save_project
    proj, _ = open_any(SCB)
    proj.markers = []
    path = str(tmp_path / "p.l7n")
    save_project(proj, path)
    assert main(["export", path, "--format", "plt", "-o", str(tmp_path / "x.plt")]) == 1
    assert "marker" in capsys.readouterr().out

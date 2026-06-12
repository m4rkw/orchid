import json
import os

from orchid.store.registry import Registry, new_project_id


def test_add_list_remove(tmp_path):
    reg = Registry(tmp_path / "registry.json")
    assert reg.list() == []
    root = tmp_path / "proj"
    root.mkdir()
    entry = reg.add("prj_a", root)
    assert entry["root"] == str(root.resolve())
    assert len(reg.list()) == 1
    assert reg.find("prj_a") == entry
    assert reg.remove("prj_a") is True
    assert reg.remove("prj_a") is False
    assert reg.list() == []


def test_dedupes_by_resolved_root(tmp_path):
    reg = Registry(tmp_path / "registry.json")
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    os.symlink(real, link)
    first = reg.add("prj_a", real)
    second = reg.add("prj_b", link)  # other spelling of the same dir
    assert second["id"] == "prj_a"
    assert len(reg.list()) == 1
    assert reg.find_by_root(link)["id"] == "prj_a"
    assert first == second


def test_corrupt_file_recovery(tmp_path):
    path = tmp_path / "registry.json"
    path.write_text("{not json")
    reg = Registry(path)
    assert reg.list() == []
    assert path.with_suffix(".json.bad").exists()
    reg.add("prj_a", tmp_path)
    assert json.loads(path.read_text())["projects"][0]["id"] == "prj_a"


def test_new_project_id_shape():
    pid = new_project_id()
    assert pid.startswith("prj_") and len(pid) == 16

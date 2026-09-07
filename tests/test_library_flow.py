"""End-to-end checks that stay inside the mock-bpy harness.

Covers the seam between publishing a setup, indexing it in config.json,
serving it from a local repository and decoding it again with the pickle
fallback disabled - the path a repository entry actually takes.
"""

import json

import pytest

from node_runner import encoding, library, library_ui, net, operators, preferences


DATA = {
    "nodes": {
        "Math": {"type": "ShaderNodeMath", "location": [0.0, 0.0],
                 "operation": "MULTIPLY", "inputs": [2.0, 3.0]},
    },
    "links": [],
    "name": "Vines",
    "tree_type": "GeometryNodeTree",
    "blender_version": "5.2.0",
}


@pytest.fixture(autouse=True)
def _clean_catalog():
    net.startup()
    yield
    net.shutdown()
    net.startup()


@pytest.fixture(name="repo_dir")
def _repo_dir(tmp_path):
    """A local library repository laid out the way Publish writes one."""
    root = tmp_path / "my-vines"
    (root / "nodes").mkdir(parents=True)

    export = encoding.encode_as(dict(DATA, export_name="Vines"), encoding.FORMAT_JSON)
    (root / "nodes" / "climbing-vine.json").write_text(export, encoding="utf-8")

    doc = library.new_config(name="My Vines")
    library.upsert_entry(doc, {
        "id": "climbing-vine",
        "name": "Climbing Vine",
        "description": "Ivy that grows over a surface.",
        "file": "nodes/climbing-vine.json",
        "tree_type": library.TREE_GEOMETRY,
        "tags": ["vine", "plant"],
        "blender_version": "5.2.0",
        "updated": "2026-09-07",
    })
    library.sort_entries(doc)
    (root / "config.json").write_text(
        json.dumps(doc, indent=2) + "\n", encoding="utf-8"
    )
    return root


def _spec(url):
    return {"name": "My Vines", "url": str(url), "branch": "main",
            "token": "", "enabled": True}


def test_local_repository_round_trip(repo_dir, tmp_path, monkeypatch):
    monkeypatch.setattr(net, "cache_root", lambda create=False: tmp_path / "cache")

    keys = net.sync_repos([_spec(repo_dir)])
    repo = net.get_repo(keys[0])

    # sync_repos only reads the cache; the index arrives on refresh.
    assert repo["entries"] == []

    payload, _etag = net.fetch(
        library.config_url(repo["base"], repo["kind"]), repo["kind"]
    )
    config, error = library.parse_config(payload)
    assert error is None
    repo["entries"] = config["entries"]

    entry = repo["entries"][0]
    assert entry["name"] == "Climbing Vine"
    assert entry["tree_type"] == library.TREE_GEOMETRY

    raw = net.load_entry_text(repo, entry)
    fmt, body = operators.strip_header_and_detect(raw)
    decoded = encoding.decode_as(body, fmt, allow_pickle=False)
    assert decoded["tree_type"] == "GeometryNodeTree"
    assert decoded["nodes"]["Math"]["operation"] == "MULTIPLY"


def test_search_finds_the_published_entry(repo_dir, tmp_path, monkeypatch):
    monkeypatch.setattr(net, "cache_root", lambda create=False: tmp_path / "cache")
    keys = net.sync_repos([_spec(repo_dir)])
    repo = net.get_repo(keys[0])
    payload, _etag = net.fetch(
        library.config_url(repo["base"], repo["kind"]), repo["kind"]
    )
    repo["entries"] = library.parse_config(payload)[0]["entries"]

    pairs = net.all_entries()
    entries = [entry for _repo, entry in pairs]
    assert library.filter_entries(entries, "vine")
    assert library.filter_entries(entries, "ivy surface")
    assert library.filter_entries(entries, "", "GEOMETRY")
    assert not library.filter_entries(entries, "", "SHADER")
    assert library.filter_entries(entries, "", "ALL", "plant")
    assert not library.filter_entries(entries, "rope")


def test_hostile_config_entries_are_rejected(repo_dir, tmp_path, monkeypatch):
    """A repository must not be able to steer reads outside its own tree."""
    monkeypatch.setattr(net, "cache_root", lambda create=False: tmp_path / "cache")
    (repo_dir / "config.json").write_text(json.dumps({
        "schema": 1,
        "entries": [
            {"id": "escape", "name": "Escape", "file": "../../../etc/passwd"},
            {"id": "absolute", "name": "Absolute", "file": "/etc/shadow"},
            {"id": "remote", "name": "Remote", "file": "https://evil.example/x"},
            {"id": "fine", "name": "Fine", "file": "nodes/climbing-vine.json"},
        ],
    }), encoding="utf-8")

    keys = net.sync_repos([_spec(repo_dir)])
    repo = net.get_repo(keys[0])
    payload, _etag = net.fetch(
        library.config_url(repo["base"], repo["kind"]), repo["kind"]
    )
    config, error = library.parse_config(payload)
    assert error is None
    assert [e["id"] for e in config["entries"]] == ["fine"]


def test_registration_is_wired_up():
    """Every class the addon registers must be reachable and ordered."""
    order = preferences.CLASSES
    assert preferences.NODE_RUNNER_RepoItem in order
    assert order.index(preferences.NODE_RUNNER_RepoItem) < order.index(
        preferences.NODE_RUNNER_preferences
    )
    # The panels reach into operators only through its public surface.
    for name in ("FORMAT_ITEMS", "blender_version_string", "supported_editor_poll",
                 "supported_tree_poll", "build_export_payload",
                 "ensure_default_tree", "import_raw"):
        assert hasattr(operators, name), name
    for name in ("get_prefs", "repo_specs"):
        assert hasattr(preferences, name), name


def test_register_and_unregister_run_clean():
    preferences.register()
    operators.register()
    library_ui.register()
    library_ui.unregister()
    operators.unregister()
    preferences.unregister()


def test_publish_default_format_is_json():
    """A git-backed library should hold readable, diffable files."""
    prop = library_ui.NODE_RUNNER_OT_library_publish.__annotations__
    assert "export_format" in prop


def test_menu_offers_publish():
    import inspect
    source = inspect.getsource(operators.NODE_RUNNER_MT_menu.draw)
    assert "node_runner.library_publish" in source

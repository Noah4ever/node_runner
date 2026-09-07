"""Tests for the pure library logic: URLs, config.json, search, slugs."""

import json

import pytest

from node_runner import library


# URL normalization


@pytest.mark.parametrize(
    "url,branch,expected",
    [
        # owner/repo shorthand
        ("tonis2/vines", "main", "https://raw.githubusercontent.com/tonis2/vines/main"),
        ("tonis2/vines.git", "main", "https://raw.githubusercontent.com/tonis2/vines/main"),
        ("tonis2/vines", "dev", "https://raw.githubusercontent.com/tonis2/vines/dev"),
        # github.com page URLs
        ("https://github.com/tonis2/vines", "main",
         "https://raw.githubusercontent.com/tonis2/vines/main"),
        ("https://github.com/tonis2/vines/", "dev",
         "https://raw.githubusercontent.com/tonis2/vines/dev"),
        ("https://www.github.com/tonis2/vines", "main",
         "https://raw.githubusercontent.com/tonis2/vines/main"),
        ("https://github.com/tonis2/vines.git", "main",
         "https://raw.githubusercontent.com/tonis2/vines/main"),
        # a ref in the URL beats the branch field
        ("https://github.com/tonis2/vines/tree/release", "main",
         "https://raw.githubusercontent.com/tonis2/vines/release"),
        ("https://github.com/tonis2/vines/tree/dev/library", "main",
         "https://raw.githubusercontent.com/tonis2/vines/dev/library"),
        # a blob URL names a file; its folder is the repository base
        ("https://github.com/tonis2/vines/blob/main/nodes/vine.json", "main",
         "https://raw.githubusercontent.com/tonis2/vines/main/nodes"),
        ("https://github.com/tonis2/vines/blob/main/config.json", "main",
         "https://raw.githubusercontent.com/tonis2/vines/main"),
        # already-raw URLs pass through, with config.json trimmed
        ("https://raw.githubusercontent.com/tonis2/vines/main/", "main",
         "https://raw.githubusercontent.com/tonis2/vines/main"),
        ("https://raw.githubusercontent.com/tonis2/vines/main/config.json", "main",
         "https://raw.githubusercontent.com/tonis2/vines/main"),
        # GitLab
        ("https://gitlab.com/tonis2/vines", "main",
         "https://gitlab.com/tonis2/vines/-/raw/main"),
        ("https://gitlab.com/grp/sub/vines/-/raw/dev/lib", "main",
         "https://gitlab.com/grp/sub/vines/-/raw/dev/lib"),
        # arbitrary static hosts are used verbatim
        ("https://example.com/nodes/", "main", "https://example.com/nodes"),
        ("https://example.com/nodes/config.json", "main", "https://example.com/nodes"),
        ("http://192.168.1.5:8080/lib", "main", "http://192.168.1.5:8080/lib"),
    ],
)
def test_normalize_repo_url_http(url, branch, expected):
    base, kind, error = library.normalize_repo_url(url, branch)
    assert error is None
    assert kind == library.KIND_HTTP
    assert base == expected


@pytest.mark.parametrize(
    "url",
    ["/tmp/vines", "/tmp/vines/", "/tmp/vines/config.json", "file:///tmp/vines"],
)
def test_normalize_repo_url_local(url):
    base, kind, error = library.normalize_repo_url(url)
    assert error is None
    assert kind == library.KIND_LOCAL
    assert base == "/tmp/vines"


def test_normalize_repo_url_expands_home():
    base, kind, error = library.normalize_repo_url("~/my-vines")
    assert error is None
    assert kind == library.KIND_LOCAL
    assert not base.startswith("~")


def test_normalize_repo_url_windows_drive_is_local():
    _base, kind, error = library.normalize_repo_url(r"C:\Users\t\vines")
    assert error is None
    assert kind == library.KIND_LOCAL


@pytest.mark.parametrize(
    "url", ["", "   ", "ftp://host/path", "ssh://git@host/repo", "javascript:alert(1)"]
)
def test_normalize_repo_url_rejected(url):
    base, kind, error = library.normalize_repo_url(url)
    assert base is None and kind is None
    assert error


def test_normalize_repo_url_blank_branch_defaults_to_main():
    base, _kind, error = library.normalize_repo_url("tonis2/vines", "")
    assert error is None
    assert base.endswith("/main")


def test_normalize_repo_url_incomplete_github():
    _base, _kind, error = library.normalize_repo_url("https://github.com/tonis2")
    assert error and "owner" in error


# URL joining


def test_entry_url_quotes_and_keeps_base_segments():
    base = "https://raw.githubusercontent.com/a/b/main/lib"
    assert library.entry_url(base, library.KIND_HTTP, "nodes/my file.json") == (
        "https://raw.githubusercontent.com/a/b/main/lib/nodes/my%20file.json"
    )


def test_entry_url_local_uses_os_join():
    joined = library.entry_url("/tmp/vines", library.KIND_LOCAL, "nodes/vine.json")
    assert joined.endswith("vine.json")
    assert "/tmp/vines" in joined


def test_config_url():
    assert library.config_url("https://x/y", library.KIND_HTTP) == "https://x/y/config.json"


# Private repositories route through the GitHub Contents API


def test_split_raw_github():
    base = "https://raw.githubusercontent.com/tonis2/vines/main"
    assert library.split_raw_github(base) == ("tonis2", "vines", "main", "")
    assert library.split_raw_github(base + "/lib/sub") == (
        "tonis2", "vines", "main", "lib/sub",
    )
    assert library.split_raw_github("https://example.com/x") is None
    assert library.split_raw_github("") is None


def test_content_url_without_token_stays_on_raw():
    base = "https://raw.githubusercontent.com/tonis2/vines/main"
    url = library.content_url(base, library.KIND_HTTP, "nodes/v.json", has_token=False)
    assert url.startswith("https://raw.githubusercontent.com/")
    assert not library.is_github_api_url(url)


def test_content_url_with_token_uses_contents_api():
    base = "https://raw.githubusercontent.com/tonis2/vines/main"
    url = library.content_url(base, library.KIND_HTTP, "nodes/v.json", has_token=True)
    assert url == (
        "https://api.github.com/repos/tonis2/vines/contents/nodes/v.json?ref=main"
    )
    assert library.is_github_api_url(url)


def test_content_url_with_token_includes_subfolder_prefix():
    base = "https://raw.githubusercontent.com/tonis2/vines/main/library"
    url = library.content_url(base, library.KIND_HTTP, "nodes/v.json", has_token=True)
    assert "contents/library/nodes/v.json" in url


def test_content_url_non_github_ignores_token():
    url = library.content_url(
        "https://gitlab.com/a/b/-/raw/main", library.KIND_HTTP, "c.json", has_token=True
    )
    assert url == "https://gitlab.com/a/b/-/raw/main/c.json"


def test_content_url_local_ignores_token():
    url = library.content_url("/tmp/v", library.KIND_LOCAL, "n/v.json", has_token=True)
    assert url.endswith("v.json")
    assert "api.github.com" not in url


# Path traversal guards


@pytest.mark.parametrize("path", ["nodes/a.json", "a.json", "a/b/c/d.json", "a-b_c.json"])
def test_is_safe_relpath_accepts(path):
    assert library.is_safe_relpath(path)


@pytest.mark.parametrize(
    "path",
    [
        "../x", "a/../../b", "..", "a/..", "/etc/passwd", "\\etc\\passwd",
        "~/secrets", "C:/Windows", r"C:\Windows", "//host/share",
        "https://evil.example/x", "", "   ", None, 42,
    ],
)
def test_is_safe_relpath_rejects(path):
    assert not library.is_safe_relpath(path)


# Slugs and tags


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Climbing Vine", "climbing-vine"),
        ("Vine Ärt", "vine-art"),
        ("  Foo__Bar  ", "foo-bar"),
        ("GN_FenceBuilder", "gn-fencebuilder"),
        ("a---b", "a-b"),
        ("100% Wool", "100-wool"),
    ],
)
def test_slugify(text, expected):
    assert library.slugify(text) == expected


@pytest.mark.parametrize("text", ["", "   ", "!!!", "日本語", None, 7])
def test_slugify_falls_back(text):
    assert library.slugify(text) == library.DEFAULT_SLUG


def test_slugify_custom_fallback():
    assert library.slugify("", fallback="") == ""


def test_parse_tags():
    assert library.parse_tags("vine, plant ,organic") == ["vine", "plant", "organic"]
    assert library.parse_tags("a,,b,a") == ["a", "b"]
    assert not library.parse_tags("")
    assert not library.parse_tags(None)
    assert library.parse_tags(["x", " y ", 3]) == ["x", "y"]


# config.json parsing


def _config(**overrides):
    entry = {
        "id": "climbing-vine",
        "name": "Climbing Vine",
        "description": "Ivy over a surface.",
        "file": "nodes/vine_nodes.json",
        "tree_type": "GeometryNodeTree",
        "tags": ["vine", "plant"],
    }
    entry.update(overrides)
    return json.dumps({"schema": 1, "name": "Lib", "entries": [entry]})


def test_parse_config_valid():
    config, error = library.parse_config(_config())
    assert error is None
    assert config["name"] == "Lib"
    assert len(config["entries"]) == 1
    entry = config["entries"][0]
    assert entry["id"] == "climbing-vine"
    assert entry["tree_type"] == "GeometryNodeTree"
    assert entry["tags"] == ["vine", "plant"]
    assert entry["thumbnail"] is None


def test_parse_config_accepts_bytes():
    config, error = library.parse_config(_config().encode("utf-8"))
    assert error is None and len(config["entries"]) == 1


def test_parse_config_rejects_bad_utf8():
    _config_out, error = library.parse_config(b"\xff\xfe not utf8")
    assert error and "UTF-8" in error


@pytest.mark.parametrize(
    "raw", ["not json", "[1,2,3]", '"a string"', '{"name": "x"}', "{}"]
)
def test_parse_config_errors(raw):
    config, error = library.parse_config(raw)
    assert config is None and error


def test_parse_config_future_schema_still_reads(caplog):
    raw = json.dumps({"schema": 99, "entries": []})
    config, error = library.parse_config(raw)
    assert error is None
    assert config["schema"] == 99


def test_parse_config_missing_schema_defaults():
    config, error = library.parse_config(json.dumps({"entries": []}))
    assert error is None
    assert config["schema"] == library.SCHEMA_VERSION


@pytest.mark.parametrize(
    "override",
    [
        {"id": ""},
        {"name": ""},
        {"file": ""},
        {"file": "../../etc/passwd"},
        {"file": "/etc/passwd"},
        {"id": "!!!"},
    ],
)
def test_parse_config_skips_bad_entry_without_failing(override):
    config, error = library.parse_config(_config(**override))
    assert error is None
    assert config["entries"] == []


def test_parse_config_one_bad_entry_keeps_the_good_ones():
    raw = json.dumps({
        "schema": 1,
        "entries": [
            {"id": "good", "name": "Good", "file": "a.json"},
            {"id": "bad", "name": "Bad"},
            "not even an object",
            {"id": "also-good", "name": "Also", "file": "b.json"},
        ],
    })
    config, error = library.parse_config(raw)
    assert error is None
    assert [e["id"] for e in config["entries"]] == ["good", "also-good"]


def test_parse_config_dedupes_ids():
    raw = json.dumps({
        "schema": 1,
        "entries": [
            {"id": "vine", "name": "First", "file": "a.json"},
            {"id": "Vine", "name": "Second", "file": "b.json"},
        ],
    })
    config, _error = library.parse_config(raw)
    assert len(config["entries"]) == 1
    assert config["entries"][0]["name"] == "First"


def test_parse_config_normalizes_id_to_a_slug():
    config, _error = library.parse_config(_config(id="Climbing_Vine"))
    assert config["entries"][0]["id"] == "climbing-vine"


def test_parse_config_unknown_tree_type_becomes_none():
    config, _error = library.parse_config(_config(tree_type="CompositorNodeTree"))
    assert config["entries"][0]["tree_type"] is None


def test_parse_config_ignores_unknown_keys():
    config, error = library.parse_config(_config(license="CC0", future_field=[1, 2]))
    assert error is None
    assert len(config["entries"]) == 1


def test_parse_config_tolerates_odd_optional_types():
    config, _error = library.parse_config(_config(tags="single", description=None))
    entry = config["entries"][0]
    assert entry["tags"] == ["single"]
    assert entry["description"] == ""


def test_parse_config_keeps_thumbnail_string():
    config, _error = library.parse_config(_config(thumbnail="thumbs/vine.png"))
    assert config["entries"][0]["thumbnail"] == "thumbs/vine.png"


# Search and filtering


def _entries():
    return [
        {"id": "vine", "name": "Climbing Vine", "description": "Ivy on a wall",
         "tree_type": library.TREE_GEOMETRY, "tags": ["plant", "organic"]},
        {"id": "rope", "name": "Rope", "description": "Twisted strands",
         "tree_type": library.TREE_GEOMETRY, "tags": ["prop"]},
        {"id": "rust", "name": "Rusty Metal", "description": "Weathered surface",
         "tree_type": library.TREE_SHADER, "tags": ["metal", "organic"]},
        {"id": "mystery", "name": "Mystery", "description": "",
         "tree_type": None, "tags": []},
    ]


def test_filter_entries_empty_search_returns_all():
    assert len(library.filter_entries(_entries(), "")) == 4


def test_filter_entries_matches_name_case_insensitively():
    found = library.filter_entries(_entries(), "CLIMBING")
    assert [e["id"] for e in found] == ["vine"]


def test_filter_entries_matches_description_and_id_and_tags():
    assert [e["id"] for e in library.filter_entries(_entries(), "strands")] == ["rope"]
    assert [e["id"] for e in library.filter_entries(_entries(), "rust")] == ["rust"]
    assert [e["id"] for e in library.filter_entries(_entries(), "metal")] == ["rust"]


def test_filter_entries_requires_every_term():
    assert library.filter_entries(_entries(), "rusty weathered")
    assert not library.filter_entries(_entries(), "rusty ivy")


def test_filter_entries_type_filter():
    geo = library.filter_entries(_entries(), "", "GEOMETRY")
    assert {e["id"] for e in geo} == {"vine", "rope", "mystery"}
    shader = library.filter_entries(_entries(), "", "SHADER")
    assert {e["id"] for e in shader} == {"rust", "mystery"}


def test_filter_entries_unknown_type_stays_visible():
    for name in ("ALL", "GEOMETRY", "SHADER"):
        ids = {e["id"] for e in library.filter_entries(_entries(), "", name)}
        assert "mystery" in ids


def test_filter_entries_tag_filter():
    found = library.filter_entries(_entries(), "", "ALL", "organic")
    assert {e["id"] for e in found} == {"vine", "rust"}


def test_filter_entries_combines_filters():
    found = library.filter_entries(_entries(), "", "GEOMETRY", "organic")
    assert [e["id"] for e in found] == ["vine"]


def test_type_for_filter():
    assert library.type_for_filter("ALL") is None
    assert library.type_for_filter("geometry") == library.TREE_GEOMETRY
    assert library.type_for_filter("SHADER") == library.TREE_SHADER
    assert library.type_for_filter("nonsense") is None


def test_entry_matches_accepts_a_raw_tree_type():
    entry = _entries()[0]
    assert library.entry_matches(entry, (), library.TREE_GEOMETRY)
    assert not library.entry_matches(entry, (), library.TREE_SHADER)


def test_collect_tags():
    assert library.collect_tags(_entries()) == ["metal", "organic", "plant", "prop"]


def test_search_terms():
    assert library.search_terms("  Foo   BAR ") == ["foo", "bar"]
    assert library.search_terms("") == []
    assert library.search_terms(None) == []


# Cache keys


def test_cache_key_is_stable_and_url_specific():
    a = library.cache_key_for("https://x/y", "main")
    assert a == library.cache_key_for("https://x/y", "main")
    assert a != library.cache_key_for("https://x/y", "dev")
    assert a != library.cache_key_for("https://x/z", "main")
    assert len(a) == 16


def test_entry_hash_tracks_staleness_fields():
    entry = {"id": "a", "file": "a.json", "updated": "2026-01-01",
             "blender_version": "5.2.0", "name": "A"}
    base = library.entry_hash(entry)
    assert base == library.entry_hash(dict(entry, name="Renamed"))
    assert base != library.entry_hash(dict(entry, updated="2026-02-01"))
    assert base != library.entry_hash(dict(entry, file="b.json"))


# Authoring


def test_new_config():
    doc = library.new_config(name="Mine", description="d")
    assert doc == {"schema": 1, "name": "Mine", "description": "d", "entries": []}


def test_upsert_entry_adds():
    doc = library.new_config()
    action, error = library.upsert_entry(doc, {"id": "a", "name": "A"})
    assert (action, error) == ("added", None)
    assert doc["entries"] == [{"id": "a", "name": "A"}]


def test_upsert_entry_refuses_duplicate_without_overwrite():
    doc = {"entries": [{"id": "a", "name": "Old"}]}
    action, error = library.upsert_entry(doc, {"id": "a", "name": "New"})
    assert action is None
    assert "already exists" in error
    assert doc["entries"][0]["name"] == "Old"


def test_upsert_entry_overwrite_preserves_unmanaged_keys_and_position():
    doc = {"entries": [
        {"id": "first", "name": "First"},
        {"id": "a", "name": "Old", "license": "CC0", "curated": True},
        {"id": "last", "name": "Last"},
    ]}
    action, error = library.upsert_entry(
        doc, {"id": "a", "name": "New", "file": "a.json"}, overwrite=True
    )
    assert (action, error) == ("updated", None)
    updated = doc["entries"][1]
    assert updated["name"] == "New"
    assert updated["file"] == "a.json"
    # Hand-authored keys the addon does not manage must survive.
    assert updated["license"] == "CC0"
    assert updated["curated"] is True


def test_upsert_entry_rejects_bad_entries_list():
    action, error = library.upsert_entry({"entries": "nope"}, {"id": "a"})
    assert action is None and error


def test_upsert_entry_skips_non_dict_rows():
    doc = {"entries": ["junk", {"id": "a", "name": "Old"}]}
    action, _error = library.upsert_entry(
        doc, {"id": "a", "name": "New"}, overwrite=True
    )
    assert action == "updated"


def test_sort_entries():
    doc = {"entries": [{"name": "b"}, {"name": "A"}, {"name": "c"}]}
    library.sort_entries(doc)
    assert [e["name"] for e in doc["entries"]] == ["A", "b", "c"]


def test_sort_entries_tolerates_junk():
    doc = {"entries": [{"name": "b"}, "junk", {}]}
    library.sort_entries(doc)
    assert len(doc["entries"]) == 3


def test_publish_then_parse_round_trip():
    """What the Publish operator writes must parse back cleanly."""
    doc = library.new_config(name="Mine")
    entry = {
        "id": library.slugify("Climbing Vine"),
        "name": "Climbing Vine",
        "description": "Ivy over a surface.",
        "file": "nodes/climbing-vine.json",
        "tree_type": library.TREE_GEOMETRY,
        "tags": library.parse_tags("vine, plant"),
        "blender_version": "5.2.0",
        "updated": "2026-09-07",
    }
    assert library.upsert_entry(doc, entry) == ("added", None)
    library.sort_entries(doc)
    config, error = library.parse_config(json.dumps(doc))
    assert error is None
    assert config["entries"][0]["id"] == "climbing-vine"
    assert config["entries"][0]["tags"] == ["vine", "plant"]

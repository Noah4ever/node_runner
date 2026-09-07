"""Tests for fetching, the disk cache and the in-memory catalog."""

import io
import json
import urllib.error
import urllib.request

import pytest

from node_runner import library, net


class FakeResponse(io.BytesIO):
    """Minimal stand-in for the object urlopen returns."""

    def __init__(self, payload=b"", headers=None):
        super().__init__(payload)
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()
        return False


@pytest.fixture(name="captured")
def _captured(monkeypatch):
    """Capture the Request urlopen was handed, and serve a canned reply."""
    seen = {}

    def _urlopen(request, timeout=None):
        seen["request"] = request
        seen["timeout"] = timeout
        if isinstance(seen.get("raise"), Exception):
            raise seen["raise"]
        return FakeResponse(seen.get("payload", b"{}"), seen.get("headers", {}))

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)
    return seen


@pytest.fixture(autouse=True)
def _clean_catalog():
    net.startup()
    yield
    net.shutdown()
    net.startup()


# Fetching


def test_fetch_sets_user_agent_and_no_auth_without_a_token(captured):
    captured["payload"] = b"hello"
    payload, _etag = net.fetch("https://example.com/config.json")
    assert payload == b"hello"
    request = captured["request"]
    assert request.get_header("User-agent") == net.USER_AGENT
    assert request.get_header("Authorization") is None


def test_fetch_sends_bearer_token(captured):
    net.fetch("https://example.com/config.json", token="secret-pat")
    assert captured["request"].get_header("Authorization") == "Bearer secret-pat"


def test_fetch_asks_the_github_api_for_raw_bytes(captured):
    url = "https://api.github.com/repos/a/b/contents/c.json?ref=main"
    net.fetch(url, token="t")
    request = captured["request"]
    assert request.get_header("Accept") == "application/vnd.github.raw"
    assert request.get_header("X-github-api-version")


def test_fetch_uses_a_plain_accept_for_raw_urls(captured):
    net.fetch("https://raw.githubusercontent.com/a/b/main/c.json", token="t")
    assert captured["request"].get_header("Accept") == "*/*"


def test_fetch_forwards_the_timeout(captured):
    net.fetch("https://example.com/x", timeout=42)
    assert captured["timeout"] == 42


def test_fetch_sends_if_none_match_and_reports_304(captured):
    captured["raise"] = urllib.error.HTTPError(
        "https://example.com/x", 304, "Not Modified", {}, None
    )
    payload, etag = net.fetch("https://example.com/x", etag='W/"abc"')
    assert payload is None
    assert etag == 'W/"abc"'
    assert captured["request"].get_header("If-none-match") == 'W/"abc"'


def test_fetch_returns_the_etag(captured):
    captured["headers"] = {"ETag": 'W/"xyz"'}
    _payload, etag = net.fetch("https://example.com/x")
    assert etag == 'W/"xyz"'


def test_fetch_rejects_an_oversized_body(captured):
    captured["payload"] = b"x" * 4096
    with pytest.raises(net.LibraryError, match="larger than"):
        net.fetch("https://example.com/x", max_bytes=1024)


@pytest.mark.parametrize(
    "code,needle",
    [
        (404, "config.json not found"),
        (401, "Access denied"),
        (403, "Access denied"),
        (429, "Rate limited"),
        (500, "HTTP 500"),
    ],
)
def test_fetch_http_errors_are_readable(captured, code, needle):
    captured["raise"] = urllib.error.HTTPError(
        "https://example.com/config.json", code, "boom", {}, None
    )
    with pytest.raises(net.LibraryError, match=needle):
        net.fetch("https://example.com/config.json", is_config=True)


def test_fetch_404_for_a_node_file_is_not_the_config_message(captured):
    captured["raise"] = urllib.error.HTTPError(
        "https://example.com/n.json", 404, "boom", {}, None
    )
    with pytest.raises(net.LibraryError, match="Not found"):
        net.fetch("https://example.com/n.json", is_config=False)


def test_fetch_unreachable_host(captured):
    captured["raise"] = urllib.error.URLError("name resolution failed")
    with pytest.raises(net.LibraryError, match="Could not reach"):
        net.fetch("https://example.invalid/x")


def test_fetch_never_leaks_the_token_into_an_error(captured):
    token = "ghp_supersecrettoken"
    captured["raise"] = urllib.error.URLError(f"proxy rejected {token}")
    with pytest.raises(net.LibraryError) as excinfo:
        net.fetch("https://example.com/x", token=token)
    assert token not in str(excinfo.value)
    assert "***" in str(excinfo.value)


# Local repositories


def test_fetch_reads_a_local_file(tmp_path):
    target = tmp_path / "config.json"
    target.write_text('{"schema": 1, "entries": []}', encoding="utf-8")
    payload, etag = net.fetch(str(target), library.KIND_LOCAL)
    assert json.loads(payload)["schema"] == 1
    assert etag == ""


def test_fetch_missing_local_file(tmp_path):
    with pytest.raises(net.LibraryError, match="does not exist"):
        net.fetch(str(tmp_path / "nope.json"), library.KIND_LOCAL)


def test_fetch_local_respects_the_size_cap(tmp_path):
    target = tmp_path / "big.json"
    target.write_text("x" * 4096, encoding="utf-8")
    with pytest.raises(net.LibraryError, match="larger than"):
        net.fetch(str(target), library.KIND_LOCAL, max_bytes=1024)


# Disk cache


def test_cache_root_falls_back_for_a_legacy_addon_install():
    # This checkout lives in scripts/addons, so __package__ is "node_runner"
    # and extension_path_user is not usable.
    root = net.cache_root(create=False)
    assert "node_runner" in str(root)


def test_write_text_atomic_leaves_no_temp_file(tmp_path):
    target = tmp_path / "sub" / "out.json"
    net.write_text_atomic(target, "hello")
    assert target.read_text(encoding="utf-8") == "hello"
    assert not list(tmp_path.rglob("*.tmp"))


def test_write_text_atomic_overwrites(tmp_path):
    target = tmp_path / "out.json"
    net.write_text_atomic(target, "one")
    net.write_text_atomic(target, "two")
    assert target.read_text(encoding="utf-8") == "two"


# Catalog


def _spec(url, name="Lib", branch="main", token="", enabled=True):
    return {"name": name, "url": url, "branch": branch,
            "token": token, "enabled": enabled}


def test_sync_repos_builds_the_catalog(monkeypatch, tmp_path):
    monkeypatch.setattr(net, "cache_root", lambda create=False: tmp_path)
    keys = net.sync_repos([_spec("tonis2/vines")])
    assert len(keys) == 1
    repo = net.get_repo(keys[0])
    assert repo["base"] == "https://raw.githubusercontent.com/tonis2/vines/main"
    assert repo["kind"] == library.KIND_HTTP
    assert repo["status"] == "Never fetched - press Refresh"


def test_sync_repos_records_a_bad_url_as_an_error(monkeypatch, tmp_path):
    monkeypatch.setattr(net, "cache_root", lambda create=False: tmp_path)
    keys = net.sync_repos([_spec("ftp://nope/x")])
    repo = net.get_repo(keys[0])
    assert repo["error"]
    assert repo["entries"] == []


def test_sync_repos_drops_repositories_that_were_removed(monkeypatch, tmp_path):
    monkeypatch.setattr(net, "cache_root", lambda create=False: tmp_path)
    net.sync_repos([_spec("a/one", name="One"), _spec("b/two", name="Two")])
    assert len(net.repos()) == 2
    net.sync_repos([_spec("a/one", name="One")])
    assert [r["name"] for r in net.repos()] == ["One"]


def test_sync_repos_keeps_preferences_order(monkeypatch, tmp_path):
    monkeypatch.setattr(net, "cache_root", lambda create=False: tmp_path)
    net.sync_repos([_spec("a/z", name="Z"), _spec("b/a", name="A")])
    assert [r["name"] for r in net.repos()] == ["Z", "A"]


def test_sync_repos_loads_a_cached_index(monkeypatch, tmp_path):
    monkeypatch.setattr(net, "cache_root", lambda create=False: tmp_path)
    base = "https://raw.githubusercontent.com/tonis2/vines/main"
    key = library.cache_key_for(base, "main")
    directory = tmp_path / "repos" / key
    directory.mkdir(parents=True)
    (directory / "config.json").write_text(json.dumps({
        "schema": 1,
        "entries": [{"id": "vine", "name": "Vine", "file": "vine.json"}],
    }), encoding="utf-8")
    (directory / "repo.json").write_text(
        json.dumps({"fetched": 1234.0, "etag": 'W/"e"'}), encoding="utf-8"
    )

    net.sync_repos([_spec("tonis2/vines")])
    repo = net.get_repo(key)
    assert [e["id"] for e in repo["entries"]] == ["vine"]
    assert repo["fetched"] == 1234.0
    assert repo["etag"] == 'W/"e"'


def test_find_entry_and_all_entries(monkeypatch, tmp_path):
    monkeypatch.setattr(net, "cache_root", lambda create=False: tmp_path)
    keys = net.sync_repos([_spec("tonis2/vines")])
    repo = net.get_repo(keys[0])
    repo["entries"] = [{"id": "vine", "name": "Vine"}]

    found_repo, entry = net.find_entry(keys[0], "vine")
    assert found_repo is repo and entry["name"] == "Vine"
    assert net.find_entry(keys[0], "missing") == (repo, None)
    assert net.find_entry("nope", "vine") == (None, None)
    assert len(net.all_entries()) == 1
    assert len(net.all_entries(keys[0])) == 1
    assert not net.all_entries("some-other-key")


def test_all_entries_skips_disabled_repositories(monkeypatch, tmp_path):
    monkeypatch.setattr(net, "cache_root", lambda create=False: tmp_path)
    keys = net.sync_repos([_spec("tonis2/vines", enabled=False)])
    net.get_repo(keys[0])["entries"] = [{"id": "vine", "name": "Vine"}]
    assert not net.all_entries()


def test_errors_reports_per_repository(monkeypatch, tmp_path):
    monkeypatch.setattr(net, "cache_root", lambda create=False: tmp_path)
    net.sync_repos([_spec("ftp://bad/x", name="Broken")])
    reported = net.errors()
    assert len(reported) == 1
    assert reported[0][0] == "Broken"


# Applying an entry end to end against a local repository


def test_load_entry_text_from_a_local_repo_and_cache_it(monkeypatch, tmp_path):
    repo_dir = tmp_path / "clone"
    (repo_dir / "nodes").mkdir(parents=True)
    (repo_dir / "nodes" / "vine.json").write_text('{"nodes": {}}', encoding="utf-8")
    cache = tmp_path / "cache"
    monkeypatch.setattr(net, "cache_root", lambda create=False: cache)

    keys = net.sync_repos([_spec(str(repo_dir))])
    repo = net.get_repo(keys[0])
    entry = {"id": "vine", "file": "nodes/vine.json", "updated": "", "blender_version": ""}

    assert net.load_entry_text(repo, entry) == '{"nodes": {}}'

    cached = cache / "repos" / repo["key"] / "files" / "vine.json"
    assert cached.is_file()

    # A second call is served from the cache, so removing the source is fine.
    (repo_dir / "nodes" / "vine.json").unlink()
    assert net.load_entry_text(repo, entry) == '{"nodes": {}}'


def test_load_entry_text_redownloads_when_the_entry_changed(monkeypatch, tmp_path):
    repo_dir = tmp_path / "clone"
    repo_dir.mkdir()
    source = repo_dir / "vine.json"
    source.write_text("first", encoding="utf-8")
    cache = tmp_path / "cache"
    monkeypatch.setattr(net, "cache_root", lambda create=False: cache)

    keys = net.sync_repos([_spec(str(repo_dir))])
    repo = net.get_repo(keys[0])
    entry = {"id": "vine", "file": "vine.json", "updated": "2026-01-01",
             "blender_version": ""}
    assert net.load_entry_text(repo, entry) == "first"

    source.write_text("second", encoding="utf-8")
    # Same entry metadata: the cached copy is still considered current.
    assert net.load_entry_text(repo, entry) == "first"
    # Bumping "updated" invalidates it.
    entry["updated"] = "2026-02-01"
    assert net.load_entry_text(repo, entry) == "second"


def test_load_entry_text_refuses_an_unsafe_path(monkeypatch, tmp_path):
    monkeypatch.setattr(net, "cache_root", lambda create=False: tmp_path / "c")
    keys = net.sync_repos([_spec(str(tmp_path))])
    repo = net.get_repo(keys[0])
    entry = {"id": "evil", "file": "../../../etc/passwd", "updated": "",
             "blender_version": ""}
    with pytest.raises(net.LibraryError, match="unsafe path"):
        net.load_entry_text(repo, entry)


def test_load_entry_text_caches_under_the_entry_id_not_the_remote_path(
    monkeypatch, tmp_path
):
    """The cache file name must never be derived from repository content."""
    repo_dir = tmp_path / "clone"
    (repo_dir / "deep" / "nested").mkdir(parents=True)
    (repo_dir / "deep" / "nested" / "x.json").write_text("{}", encoding="utf-8")
    cache = tmp_path / "cache"
    monkeypatch.setattr(net, "cache_root", lambda create=False: cache)

    keys = net.sync_repos([_spec(str(repo_dir))])
    repo = net.get_repo(keys[0])
    net.load_entry_text(
        repo,
        {"id": "vine", "file": "deep/nested/x.json", "updated": "",
         "blender_version": ""},
    )
    files = cache / "repos" / repo["key"] / "files"
    assert (files / "vine.json").is_file()
    assert not (files / "deep").exists()


# Refresh scheduling


def test_refresh_skips_repositories_with_a_bad_url(monkeypatch, tmp_path):
    monkeypatch.setattr(net, "cache_root", lambda create=False: tmp_path)
    net.sync_repos([_spec("ftp://bad/x")])
    assert net.refresh() == 0


def test_refresh_skips_disabled_repositories(monkeypatch, tmp_path):
    monkeypatch.setattr(net, "cache_root", lambda create=False: tmp_path)
    net.sync_repos([_spec("tonis2/vines", enabled=False)])
    assert net.refresh() == 0


def test_refresh_refuses_when_online_access_is_off(monkeypatch, tmp_path):
    monkeypatch.setattr(net, "cache_root", lambda create=False: tmp_path)
    monkeypatch.setattr(net, "online_access", lambda: False)
    keys = net.sync_repos([_spec("tonis2/vines")])
    assert net.refresh() == 0
    assert "Online access is disabled" in net.get_repo(keys[0])["error"]


def test_submit_deduplicates_an_in_flight_job():
    calls = []

    def _slow():
        calls.append(1)
        return b"x"

    assert net.submit(("config", "k"), _slow) is True
    # The key stays in flight until the timer drains it.
    assert net.submit(("config", "k"), _slow) is False
    assert net.is_busy()


def test_submit_is_a_noop_after_shutdown():
    net.shutdown()
    assert net.submit(("config", "k"), lambda: b"") is False


def test_prune_removes_orphaned_repositories(monkeypatch, tmp_path):
    monkeypatch.setattr(net, "cache_root", lambda create=False: tmp_path)
    repos = tmp_path / "repos"
    (repos / "keep").mkdir(parents=True)
    (repos / "drop" / "files").mkdir(parents=True)
    (repos / "drop" / "files" / "a.json").write_text("{}", encoding="utf-8")

    net.prune({"keep"})
    assert (repos / "keep").is_dir()
    assert not (repos / "drop").exists()


def test_clear_cache_empties_the_catalog(monkeypatch, tmp_path):
    monkeypatch.setattr(net, "cache_root", lambda create=False: tmp_path)
    keys = net.sync_repos([_spec("tonis2/vines")])
    repo = net.get_repo(keys[0])
    repo["entries"] = [{"id": "vine"}]
    repo["fetched"] = 1.0
    (tmp_path / "repos" / repo["key"]).mkdir(parents=True)

    net.clear_cache()
    assert repo["entries"] == []
    assert repo["fetched"] == 0.0
    assert not (tmp_path / "repos").exists()

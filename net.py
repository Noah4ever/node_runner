"""
Fetching, disk cache and the in-memory catalog for the Node Runner library.

Network work happens on daemon worker threads which must never touch
``bpy``; results are handed back to the main thread through a queue drained
by a ``bpy.app.timers`` callback. Everything that reads or writes Blender
data therefore runs on the main thread, which is the only place it is legal.
"""

import json
import logging
import os
import queue
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import library

log = logging.getLogger(__name__)

USER_AGENT = "NodeRunner-Blender-Addon"

# Config indexes are small; node exports in practice run 25 KB - 250 KB.
CONFIG_TIMEOUT = 15
FILE_TIMEOUT = 60
MAX_CONFIG_BYTES = 2 * 1024 * 1024
MAX_FILE_BYTES = 32 * 1024 * 1024

_POLL_INTERVAL = 0.2

# repo key -> repo state dict. Written only on the main thread.
_catalog = {}
_catalog_order = []

_results = queue.Queue()
_inflight = set()
_state = {"shutdown": False}


class LibraryError(Exception):
    """A fetch or cache operation failed with a user-facing message."""


# Errors


def _scrub(message, token):
    """Keep an access token out of anything the user or log can see."""
    text = str(message)
    if token:
        text = text.replace(token, "***")
    return text


def _http_message(exc, url, is_config):
    """Turn an HTTPError into something worth showing in the panel."""
    if exc.code == 404:
        if is_config:
            return f"{library.CONFIG_NAME} not found - check the URL and branch"
        return f"Not found: {url}"
    if exc.code in (401, 403):
        return (
            f"Access denied ({exc.code}) - a private repository needs a valid "
            "access token"
        )
    if exc.code == 429:
        return "Rate limited by the server - try again in a few minutes"
    return f"HTTP {exc.code} fetching {url}"


# Fetching (worker threads - no bpy in here)


def _headers(token, is_api):
    headers = {"User-Agent": USER_AGENT}
    if is_api:
        # Asks the Contents API for file bytes rather than a JSON envelope.
        headers["Accept"] = "application/vnd.github.raw"
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    else:
        headers["Accept"] = "*/*"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _read_capped(handle, max_bytes, what):
    payload = handle.read(max_bytes + 1)
    if len(payload) > max_bytes:
        raise LibraryError(
            f"{what} is larger than {max_bytes // (1024 * 1024)} MB - "
            "refusing to download it"
        )
    return payload


def _read_local(path, max_bytes):
    try:
        with open(path, "rb") as handle:
            return _read_capped(handle, max_bytes, os.path.basename(path))
    except FileNotFoundError as exc:
        raise LibraryError(f"{path} does not exist") from exc
    except OSError as exc:
        raise LibraryError(f"Could not read {path}: {exc}") from exc


def fetch(location, kind=library.KIND_HTTP, token="", etag="",
          timeout=CONFIG_TIMEOUT, max_bytes=MAX_CONFIG_BYTES, is_config=False):
    """Fetch *location* and return ``(payload, etag)``.

    *payload* is ``None`` when the server answered 304 Not Modified, which
    means the cached copy is still current. Runs on a worker thread.
    """
    if kind == library.KIND_LOCAL:
        return _read_local(location, max_bytes), ""

    is_api = library.is_github_api_url(location)
    headers = _headers(token, is_api)
    if etag:
        headers["If-None-Match"] = etag
    request = urllib.request.Request(location, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = _read_capped(response, max_bytes, location)
            return payload, response.headers.get("ETag", "") or ""
    except urllib.error.HTTPError as exc:
        if exc.code == 304:
            return None, etag
        raise LibraryError(_scrub(_http_message(exc, location, is_config), token)) from exc
    except urllib.error.URLError as exc:
        raise LibraryError(
            _scrub(f"Could not reach {location}: {exc.reason}", token)
        ) from exc
    except (OSError, ValueError) as exc:
        raise LibraryError(_scrub(f"Could not fetch {location}: {exc}", token)) from exc


# Disk cache (main thread for reads at register; worker threads write)


def cache_root(create=False):
    """Directory the downloaded catalog and node files live under.

    ``extension_path_user`` only works for a ``bl_ext.*`` package. A legacy
    ``scripts/addons`` install falls back to the user data directory rather
    than writing inside the addon folder, which here is a git checkout.
    """
    import bpy  # noqa: PLC0415 - bpy is unavailable outside Blender

    package = __package__ or ""
    if package.startswith("bl_ext."):
        try:
            return Path(
                bpy.utils.extension_path_user(package, path="cache", create=create)
            )
        except (AttributeError, ValueError, TypeError):
            pass
    return Path(
        bpy.utils.user_resource("DATAFILES", path="node_runner/cache", create=create)
    )


def repo_cache_dir(repo, create=False):
    directory = cache_root(create=create) / "repos" / repo["key"]
    if create:
        (directory / "files").mkdir(parents=True, exist_ok=True)
    return directory


def write_text_atomic(path, text):
    """Write *text* via a temporary file so a crash cannot corrupt *path*."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.replace(tmp, target)


def _read_meta(directory):
    try:
        with open(directory / "repo.json", "r", encoding="utf-8") as handle:
            meta = json.load(handle)
    except (OSError, ValueError):
        return {}
    return meta if isinstance(meta, dict) else {}


def prune(live_keys):
    """Delete cached repositories that are no longer configured."""
    try:
        root = cache_root(create=False) / "repos"
        if not root.is_dir():
            return
        for child in root.iterdir():
            if child.is_dir() and child.name not in live_keys:
                _remove_tree(child)
    except OSError as exc:
        log.warning("Could not prune the library cache: %s", exc)


def _remove_tree(directory):
    for base, dirs, files in os.walk(directory, topdown=False):
        for name in files:
            try:
                os.remove(os.path.join(base, name))
            except OSError:
                pass
        for name in dirs:
            try:
                os.rmdir(os.path.join(base, name))
            except OSError:
                pass
    try:
        os.rmdir(directory)
    except OSError:
        pass


def clear_cache():
    """Drop every cached file so the next refresh re-downloads everything."""
    try:
        root = cache_root(create=False) / "repos"
    except (AttributeError, RuntimeError) as exc:
        raise LibraryError(f"Cache is unavailable: {exc}") from exc
    if root.is_dir():
        _remove_tree(root)
    for repo in repos():
        repo["entries"] = []
        repo["fetched"] = 0.0
        repo["etag"] = ""
        repo["status"] = "Cache cleared - press Refresh"


# Catalog


def repos():
    """Configured repositories, in preferences order."""
    return [_catalog[key] for key in _catalog_order if key in _catalog]


def get_repo(key):
    return _catalog.get(key)


def find_entry(repo_key, entry_id):
    """Return ``(repo, entry)``; either may be ``None`` if it went away."""
    repo = _catalog.get(repo_key)
    if repo is None:
        return None, None
    for entry in repo.get("entries", []):
        if entry["id"] == entry_id:
            return repo, entry
    return repo, None


def all_entries(repo_filter="ALL"):
    """``(repo, entry)`` pairs across every enabled repository."""
    pairs = []
    for repo in repos():
        if not repo.get("enabled"):
            continue
        if repo_filter not in ("ALL", "", repo["key"]):
            continue
        for entry in repo.get("entries", []):
            pairs.append((repo, entry))
    return pairs


def is_busy():
    return bool(_inflight)


def errors():
    """Per-repository error messages currently worth showing."""
    return [
        (repo.get("name") or repo["key"], repo["error"])
        for repo in repos()
        if repo.get("error")
    ]


def sync_repos(repo_specs):
    """Rebuild the catalog from preferences and load each repo from cache.

    *repo_specs* are plain dicts read off ``AddonPreferences`` on the main
    thread, so nothing here needs a Blender context.
    """
    seen = []
    for spec in repo_specs:
        base, kind, error = library.normalize_repo_url(spec["url"], spec["branch"])
        key = library.cache_key_for(base or spec["url"], spec["branch"])
        if key in seen:
            continue
        repo = _catalog.get(key)
        if repo is None:
            repo = {
                "key": key, "entries": [], "status": "", "error": "",
                "fetched": 0.0, "etag": "",
            }
            _catalog[key] = repo
        repo.update({
            "name": spec["name"] or (base or spec["url"]),
            "url": spec["url"],
            "branch": spec["branch"],
            "token": spec["token"],
            "enabled": spec["enabled"],
            "base": base,
            "kind": kind,
        })
        if error:
            repo["error"] = error
            repo["entries"] = []
        elif not repo["fetched"]:
            _load_cached(repo)
        seen.append(key)

    for key in list(_catalog):
        if key not in seen:
            del _catalog[key]
    _catalog_order[:] = seen
    return seen


def _load_cached(repo):
    """Populate a repository from its disk cache. No network."""
    try:
        directory = repo_cache_dir(repo)
    except (AttributeError, RuntimeError) as exc:
        log.warning("Library cache unavailable: %s", exc)
        return
    config_path = directory / library.CONFIG_NAME
    if not config_path.is_file():
        repo["status"] = "Never fetched - press Refresh"
        return
    try:
        raw = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        repo["error"] = f"Could not read the cached index: {exc}"
        return
    config, error = library.parse_config(raw, source=repo.get("name", ""))
    if error:
        repo["error"] = error
        return
    meta = _read_meta(directory)
    repo["entries"] = config["entries"]
    repo["error"] = ""
    repo["status"] = ""
    repo["etag"] = meta.get("etag", "") or ""
    try:
        repo["fetched"] = float(meta.get("fetched", 0.0))
    except (TypeError, ValueError):
        repo["fetched"] = 0.0


# Background jobs


def online_access():
    """Whether Blender currently permits network access."""
    import bpy  # noqa: PLC0415

    return bool(getattr(bpy.app, "online_access", True))


def submit(key, func, *args, **kwargs):
    """Run *func* on a worker thread. Main thread only.

    Returns ``False`` when a job with the same key is already running, which
    is what makes a double-clicked Refresh a no-op.
    """
    if _state["shutdown"] or key in _inflight:
        return False
    _inflight.add(key)

    def _worker():
        try:
            _results.put((key, func(*args, **kwargs), None))
        except Exception as exc:  # pylint: disable=broad-exception-caught
            # A worker must never die silently; the panel shows this.
            _results.put((key, None, exc))

    threading.Thread(target=_worker, daemon=True).start()
    _ensure_timer()
    return True


def refresh(repo_keys=None):
    """Start a background index fetch for the enabled repositories."""
    started = 0
    for repo in repos():
        if not repo.get("enabled") or not repo.get("base"):
            continue
        if repo_keys is not None and repo["key"] not in repo_keys:
            continue
        if repo["kind"] == library.KIND_HTTP and not online_access():
            repo["error"] = "Online access is disabled in Preferences > System"
            continue
        url = library.content_url(
            repo["base"], repo["kind"], library.CONFIG_NAME, bool(repo.get("token"))
        )
        started_job = submit(
            ("config", repo["key"]), fetch, url, repo["kind"],
            repo.get("token", ""), repo.get("etag", ""),
            CONFIG_TIMEOUT, MAX_CONFIG_BYTES, True,
        )
        if started_job:
            repo["status"] = "Refreshing..."
            repo["error"] = ""
            started += 1
    return started


def load_entry_text(repo, entry, force=False):
    """Return the node export text for *entry*, downloading if needed.

    Runs on the main thread: the click has to produce a result, and the
    deserialize that follows has to happen here anyway. Raises
    ``LibraryError`` with a message fit for ``operator.report``.
    """
    digest = library.entry_hash(entry)
    cached = stamp = None
    try:
        directory = repo_cache_dir(repo, create=True)
        cached = directory / "files" / f"{entry['id']}.json"
        stamp = directory / "files" / f"{entry['id']}.hash"
    except (AttributeError, OSError, RuntimeError) as exc:
        log.warning("Library cache unavailable: %s", exc)

    if not force and cached is not None and cached.is_file() and stamp.is_file():
        try:
            if stamp.read_text(encoding="utf-8").strip() == digest:
                return cached.read_text(encoding="utf-8")
        except OSError:
            pass

    if not library.is_safe_relpath(entry["file"]):
        raise LibraryError(f"Refusing to fetch unsafe path {entry['file']!r}")
    if repo["kind"] == library.KIND_HTTP and not online_access():
        raise LibraryError("Online access is disabled in Preferences > System")

    url = library.content_url(
        repo["base"], repo["kind"], entry["file"], bool(repo.get("token"))
    )
    payload, _etag = fetch(
        url, repo["kind"], repo.get("token", ""), "",
        FILE_TIMEOUT, MAX_FILE_BYTES, False,
    )
    if payload is None:
        raise LibraryError(f"Server returned no content for {entry['file']}")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LibraryError(f"{entry['file']} is not valid UTF-8") from exc

    if cached is not None:
        try:
            write_text_atomic(cached, text)
            write_text_atomic(stamp, digest)
        except OSError as exc:
            log.warning("Could not cache %s: %s", entry["id"], exc)
    return text


# Main-thread result pump


def _store_config(repo, result):
    payload, etag = result
    if payload is None:
        # 304 Not Modified - the cached index is still current.
        repo["fetched"] = time.time()
        return
    try:
        raw = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        repo["error"] = f"{library.CONFIG_NAME} is not valid UTF-8: {exc}"
        return
    config, error = library.parse_config(raw, source=repo.get("name", ""))
    if error:
        repo["error"] = error
        return
    repo["entries"] = config["entries"]
    repo["error"] = ""
    repo["fetched"] = time.time()
    repo["etag"] = etag or ""
    try:
        directory = repo_cache_dir(repo, create=True)
        write_text_atomic(directory / library.CONFIG_NAME, raw)
        write_text_atomic(directory / "repo.json", json.dumps({
            "url": repo["url"],
            "base": repo["base"],
            "branch": repo["branch"],
            "fetched": repo["fetched"],
            "etag": repo["etag"],
        }, indent=2) + "\n")
    except (AttributeError, OSError, RuntimeError) as exc:
        log.warning("Could not write the library cache: %s", exc)


def _dispatch(key, result, exc):
    kind, repo_key = key
    repo = _catalog.get(repo_key)
    if repo is None:
        return
    repo["status"] = ""
    if exc is not None:
        repo["error"] = str(exc) or exc.__class__.__name__
        log.error("Node Runner library: %s", repo["error"])
        return
    if kind == "config":
        _store_config(repo, result)


def _tag_redraw():
    import bpy  # noqa: PLC0415

    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type in ("VIEW_3D", "NODE_EDITOR"):
                    area.tag_redraw()
    except (AttributeError, RuntimeError, TypeError):
        pass


def _drain():
    """Timer callback. Blender drops a timer whose callback raises, so this
    swallows everything and logs instead."""
    try:
        while True:
            try:
                key, result, exc = _results.get_nowait()
            except queue.Empty:
                break
            _inflight.discard(key)
            _dispatch(key, result, exc)
        _tag_redraw()
    except Exception:  # pylint: disable=broad-exception-caught
        log.exception("Node Runner library timer failed")
    if _state["shutdown"]:
        return None
    return _POLL_INTERVAL if _inflight else None


def _ensure_timer():
    import bpy  # noqa: PLC0415

    if _state["shutdown"]:
        return
    try:
        if not bpy.app.timers.is_registered(_drain):
            bpy.app.timers.register(_drain, first_interval=_POLL_INTERVAL)
    except (AttributeError, TypeError) as exc:
        log.warning("Could not start the library timer: %s", exc)


def startup():
    """Reset module state so a disable/enable cycle works."""
    _state["shutdown"] = False


def shutdown():
    """Stop the timer, drop pending results and clear the catalog."""
    _state["shutdown"] = True
    try:
        import bpy  # noqa: PLC0415

        if bpy.app.timers.is_registered(_drain):
            bpy.app.timers.unregister(_drain)
    except (ImportError, ValueError, AttributeError, TypeError):
        pass
    while True:
        try:
            _results.get_nowait()
        except queue.Empty:
            break
    _inflight.clear()
    _catalog.clear()
    _catalog_order[:] = []

"""
Pure logic for the Node Runner network library.

Repository URL normalization, ``config.json`` parsing and validation,
search / filtering and slug handling all live here. Nothing in this module
imports ``bpy``, so it can be unit tested outside Blender under the mock
harness in the root ``conftest.py``.
"""

import hashlib
import json
import logging
import os
import re
import unicodedata
import urllib.parse
import urllib.request

log = logging.getLogger(__name__)

# Highest config.json schema this addon understands.
SCHEMA_VERSION = 1

# The index file every repository is expected to publish.
CONFIG_NAME = "config.json"

TREE_GEOMETRY = "GeometryNodeTree"
TREE_SHADER = "ShaderNodeTree"
KNOWN_TREE_TYPES = frozenset({TREE_GEOMETRY, TREE_SHADER})

# How a repository is reached. Local repositories make the publish flow
# testable end to end without pushing anything.
KIND_HTTP = "http"
KIND_LOCAL = "local"

# Maps the panel's type dropdown onto tree_type values.
TYPE_FILTERS = {"ALL": None, "GEOMETRY": TREE_GEOMETRY, "SHADER": TREE_SHADER}

DEFAULT_SLUG = "node-setup"

_SHORTHAND_RE = re.compile(r"^[\w.-]+/[\w.-]+$")
_SLUG_STRIP_RE = re.compile(r"[^a-z0-9]+")
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")
_LOCAL_PREFIXES = ("~", "/", "./", "../", ".\\", "..\\", "\\\\")


# Slugs and tags


def slugify(text, fallback=DEFAULT_SLUG):
    """Return a lowercase kebab-case slug that is safe as a file name.

    Accents are folded to ASCII so ``"Vine Ärt"`` becomes ``"vine-art"``.
    Text that reduces to nothing (e.g. pure CJK) yields *fallback*.
    """
    if not isinstance(text, str):
        text = ""
    folded = unicodedata.normalize("NFKD", text)
    ascii_only = folded.encode("ascii", "ignore").decode("ascii")
    slug = _SLUG_STRIP_RE.sub("-", ascii_only.lower()).strip("-")
    return slug or fallback


def parse_tags(text):
    """Split a comma separated tag string into a clean list."""
    if isinstance(text, (list, tuple)):
        parts = text
    else:
        parts = (text or "").split(",")
    seen = []
    for part in parts:
        if not isinstance(part, str):
            continue
        tag = part.strip()
        if tag and tag not in seen:
            seen.append(tag)
    return seen


# Repository URL normalization


def _strip_git(segment):
    """Drop a trailing ``.git`` from a repository name."""
    return segment[:-4] if segment.lower().endswith(".git") else segment


def _drop_config(segments):
    """Drop a trailing ``config.json`` from a list of path segments."""
    if segments and segments[-1].lower() == CONFIG_NAME:
        return list(segments[:-1])
    return list(segments)


def _looks_local(raw):
    """True when *raw* reads as a filesystem path rather than a URL."""
    if raw.startswith(_LOCAL_PREFIXES):
        return True
    return bool(_WINDOWS_DRIVE_RE.match(raw))


def _local_base(path):
    """Normalize a local repository folder path."""
    expanded = os.path.expanduser(path.strip()).rstrip("/\\")
    if os.path.basename(expanded).lower() == CONFIG_NAME:
        expanded = os.path.dirname(expanded)
    return expanded


def _github_base(segments, branch):
    """Build a raw.githubusercontent.com base from a github.com path."""
    if len(segments) < 2:
        return None, None, "GitHub URL must include an owner and a repository"
    owner, repo = segments[0], _strip_git(segments[1])
    rest = list(segments[2:])
    ref, sub = branch, []
    if rest and rest[0] in ("tree", "blob"):
        if len(rest) < 2:
            return None, None, "GitHub URL is missing a branch or tag name"
        kind, ref, sub = rest[0], rest[1], list(rest[2:])
        if kind == "blob" and sub:
            # A blob URL names a file; the repository base is its folder.
            sub.pop()
    else:
        sub = _drop_config(rest)
    parts = [owner, repo, ref] + sub
    return "https://raw.githubusercontent.com/" + "/".join(parts), KIND_HTTP, None


def _gitlab_base(segments, branch):
    """Build a gitlab.com raw base from a gitlab.com path."""
    if len(segments) < 2:
        return None, None, "GitLab URL must include an owner and a repository"
    if "-" in segments:
        marker = segments.index("-")
        project = list(segments[:marker])
        rest = list(segments[marker + 1:])
        ref, sub = branch, []
        if rest and rest[0] in ("raw", "blob", "tree"):
            kind, rest = rest[0], rest[1:]
            if rest:
                ref, sub = rest[0], _drop_config(rest[1:])
            if kind == "blob" and sub:
                sub.pop()
    else:
        project = [_strip_git(seg) for seg in _drop_config(segments)]
        ref, sub = branch, []
    parts = project + ["-", "raw", ref] + sub
    return "https://gitlab.com/" + "/".join(parts), KIND_HTTP, None


def _http_base(parsed, branch):
    """Normalize an http(s) repository URL to a raw content base."""
    host = parsed.netloc.lower()
    segments = [seg for seg in parsed.path.split("/") if seg]

    if host in ("github.com", "www.github.com"):
        return _github_base(segments, branch)
    if host in ("gitlab.com", "www.gitlab.com"):
        return _gitlab_base(segments, branch)

    # raw.githubusercontent.com and any other static host: already raw.
    segments = _drop_config(segments)
    base = urllib.parse.urlunparse(
        (parsed.scheme, parsed.netloc, "/".join(segments), "", "", "")
    )
    return base.rstrip("/"), KIND_HTTP, None


def normalize_repo_url(url, branch="main"):
    """Resolve a user-entered repository location.

    Accepts a github.com page URL, a raw URL, ``owner/repo`` shorthand, a
    GitLab URL, any other http(s) base URL, or a local folder path.

    Returns ``(base, kind, error)``. On failure *base* and *kind* are
    ``None`` and *error* carries a message suitable for the preferences UI.
    """
    raw = (url or "").strip()
    if not raw:
        return None, None, "No URL set"
    branch = (branch or "").strip() or "main"

    if raw.lower().startswith("file://"):
        parsed = urllib.parse.urlparse(raw)
        return _local_base(urllib.request.url2pathname(parsed.path)), KIND_LOCAL, None

    if _looks_local(raw):
        return _local_base(raw), KIND_LOCAL, None

    if _SHORTHAND_RE.match(raw):
        owner, repo = raw.split("/")
        return (
            f"https://raw.githubusercontent.com/{owner}/{_strip_git(repo)}/{branch}",
            KIND_HTTP,
            None,
        )

    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        scheme = parsed.scheme or "(none)"
        return None, None, (
            f"Unsupported URL scheme '{scheme}' - use an http(s) URL, "
            "owner/repo, or a local folder path"
        )
    if not parsed.netloc:
        return None, None, "URL is missing a host name"

    return _http_base(parsed, branch)


def entry_url(base, kind, relpath):
    """Join a repository *base* and a relative path into a fetch location."""
    rel = (relpath or "").strip().lstrip("/")
    if kind == KIND_LOCAL:
        return os.path.join(base, *[seg for seg in rel.split("/") if seg])
    return base.rstrip("/") + "/" + urllib.parse.quote(rel)


def config_url(base, kind):
    """Location of a repository's ``config.json``."""
    return entry_url(base, kind, CONFIG_NAME)



_RAW_GITHUB_PREFIX = "https://raw.githubusercontent.com/"


def split_raw_github(base):
    """Split a raw.githubusercontent.com base into its parts.

    Returns ``(owner, repo, ref, prefix)`` where *prefix* is the (possibly
    empty) subdirectory inside the repository, or ``None`` when *base* is
    not a raw GitHub URL.
    """
    if not base or not base.startswith(_RAW_GITHUB_PREFIX):
        return None
    segments = [seg for seg in base[len(_RAW_GITHUB_PREFIX):].split("/") if seg]
    if len(segments) < 3:
        return None
    owner, repo, ref = segments[0], segments[1], segments[2]
    return owner, repo, ref, "/".join(segments[3:])


def content_url(base, kind, relpath, has_token=False):
    """Location to fetch *relpath* from, honouring private-repo access.

    ``raw.githubusercontent.com`` does not accept an ``Authorization``
    header, so a private GitHub repository cannot be read through it. The
    documented route is the Contents API with the raw media type, which is
    what a repository with a token configured uses instead.
    """
    if kind == KIND_HTTP and has_token:
        parts = split_raw_github(base)
        if parts is not None:
            owner, repo, ref, prefix = parts
            path = "/".join(seg for seg in (prefix, relpath.strip("/")) if seg)
            quoted = urllib.parse.quote(path)
            return (
                f"https://api.github.com/repos/{owner}/{repo}/contents/"
                f"{quoted}?ref={urllib.parse.quote(ref, safe='')}"
            )
    return entry_url(base, kind, relpath)


def is_github_api_url(url):
    """True when *url* targets the GitHub Contents API."""
    return bool(url) and url.startswith("https://api.github.com/")

def cache_key_for(base, branch=""):
    """Stable, filesystem-safe cache directory name for a repository."""
    digest = hashlib.sha256(f"{base}\n{branch}".encode("utf-8")).hexdigest()
    return digest[:16]


def entry_hash(entry):
    """Hash the entry fields that decide whether a cached file is stale."""
    fields = ("id", "file", "updated", "blender_version")
    payload = json.dumps(
        {key: entry.get(key) for key in fields},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


# config.json parsing


def is_safe_relpath(path):
    """True when *path* is a plain relative path that stays inside the repo.

    Guards the cache against hostile ``file`` values such as
    ``"../../../.bashrc"`` or absolute paths.
    """
    if not isinstance(path, str):
        return False
    candidate = path.strip()
    if not candidate:
        return False
    if "://" in candidate or candidate.startswith("//"):
        return False
    if candidate.startswith(("/", "\\", "~")):
        return False
    if _WINDOWS_DRIVE_RE.match(candidate):
        return False
    return ".." not in re.split(r"[\\/]+", candidate)


def _clean_str(value):
    """Return a stripped string, or ``""`` for anything that isn't one."""
    return value.strip() if isinstance(value, str) else ""


def validate_entry(item):
    """Validate one ``entries`` element.

    Returns ``(entry, error)``. The returned entry is normalized: its ``id``
    is slugified because it doubles as a cache file name, and optional
    fields are filled in with safe defaults.
    """
    if not isinstance(item, dict):
        return None, "entry is not an object"

    raw_id = _clean_str(item.get("id"))
    if not raw_id:
        return None, "missing 'id'"
    entry_id = slugify(raw_id, fallback="")
    if not entry_id:
        return None, f"'id' {raw_id!r} contains no usable characters"

    name = _clean_str(item.get("name"))
    if not name:
        return None, f"entry {entry_id!r} is missing 'name'"

    relpath = _clean_str(item.get("file"))
    if not relpath:
        return None, f"entry {entry_id!r} is missing 'file'"
    if not is_safe_relpath(relpath):
        return None, f"entry {entry_id!r} has an unsafe 'file' path: {relpath!r}"

    tree_type = item.get("tree_type")
    if tree_type not in KNOWN_TREE_TYPES:
        tree_type = None

    thumbnail = item.get("thumbnail")
    return {
        "id": entry_id,
        "name": name,
        "description": _clean_str(item.get("description")),
        "file": relpath,
        "tree_type": tree_type,
        "tags": parse_tags(item.get("tags")),
        "author": _clean_str(item.get("author")),
        "blender_version": _clean_str(item.get("blender_version")),
        "updated": _clean_str(item.get("updated")),
        # Reserved for a future release; nothing renders it yet.
        "thumbnail": thumbnail if isinstance(thumbnail, str) else None,
    }, None


def parse_config(raw, source=""):
    """Parse a ``config.json`` document into a catalog dict.

    Returns ``(config, error)``. A single malformed entry is skipped with a
    warning rather than blanking the whole repository; only a document that
    cannot be read at all produces an error.
    """
    label = source or CONFIG_NAME
    if isinstance(raw, (bytes, bytearray)):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            return None, f"{CONFIG_NAME} is not valid UTF-8: {exc}"
    try:
        doc = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        return None, f"{CONFIG_NAME} is not valid JSON: {exc}"
    if not isinstance(doc, dict):
        return None, f"{CONFIG_NAME} must contain a JSON object"

    schema = doc.get("schema", SCHEMA_VERSION)
    if not isinstance(schema, int) or isinstance(schema, bool):
        schema = SCHEMA_VERSION
    if schema > SCHEMA_VERSION:
        log.warning(
            "%s declares schema %s but this version understands %s - "
            "reading it anyway", label, schema, SCHEMA_VERSION,
        )

    raw_entries = doc.get("entries")
    if not isinstance(raw_entries, list):
        return None, f"{CONFIG_NAME} has no 'entries' list"

    entries = []
    seen = set()
    for index, item in enumerate(raw_entries):
        entry, why = validate_entry(item)
        if entry is None:
            log.warning("Skipping entry %d in %s: %s", index, label, why)
            continue
        if entry["id"] in seen:
            log.warning("Skipping duplicate id %r in %s", entry["id"], label)
            continue
        seen.add(entry["id"])
        entries.append(entry)

    return {
        "schema": schema,
        "name": _clean_str(doc.get("name")),
        "description": _clean_str(doc.get("description")),
        "entries": entries,
    }, None


# Search and filtering


def search_terms(text):
    """Split a search box value into lowercase terms."""
    return [term for term in (text or "").lower().split() if term]


def type_for_filter(type_filter):
    """Map a panel type filter onto a tree_type, or ``None`` for all."""
    return TYPE_FILTERS.get((type_filter or "ALL").upper())


def entry_matches(entry, terms=(), tree_type=None, tag=""):
    """True when *entry* satisfies every active filter.

    All search terms must match (AND). Entries whose ``tree_type`` is
    unknown stay visible under every type filter rather than disappearing.
    """
    if tree_type is not None:
        entry_type = entry.get("tree_type")
        if entry_type is not None and entry_type != tree_type:
            return False

    tags = entry.get("tags") or []
    if tag:
        needle = tag.strip().lower()
        if needle and not any(needle in item.lower() for item in tags):
            return False

    if not terms:
        return True
    haystack = " ".join(
        [
            entry.get("name", ""),
            entry.get("description", ""),
            entry.get("id", ""),
            " ".join(tags),
        ]
    ).lower()
    return all(term in haystack for term in terms)


def filter_entries(entries, search="", type_filter="ALL", tag=""):
    """Filter a list of entries by free text, tree type and tag."""
    terms = search_terms(search)
    wanted = type_for_filter(type_filter)
    return [
        entry for entry in entries
        if entry_matches(entry, terms, wanted, tag)
    ]


def collect_tags(entries):
    """Sorted unique tags across *entries*."""
    tags = set()
    for entry in entries:
        for tag in entry.get("tags") or []:
            tags.add(tag)
    return sorted(tags, key=str.lower)


# Authoring helpers (used by the Publish operator)


def new_config(name="", description=""):
    """A fresh, empty config.json document."""
    return {
        "schema": SCHEMA_VERSION,
        "name": name,
        "description": description,
        "entries": [],
    }


def upsert_entry(doc, entry, overwrite=False):
    """Insert or replace *entry* in a raw config.json document.

    Operates on the raw parsed JSON rather than the validated catalog form
    so that keys this addon does not manage survive a round trip.

    Returns ``(action, error)`` where *action* is ``"added"`` or
    ``"updated"``.
    """
    entries = doc.setdefault("entries", [])
    if not isinstance(entries, list):
        return None, f"{CONFIG_NAME} 'entries' is not a list"

    for index, existing in enumerate(entries):
        if not isinstance(existing, dict):
            continue
        if existing.get("id") != entry["id"]:
            continue
        if not overwrite:
            return None, (
                f"Entry '{entry['id']}' already exists - "
                "enable Overwrite to replace it"
            )
        merged = dict(existing)
        merged.update(entry)
        entries[index] = merged
        return "updated", None

    entries.append(dict(entry))
    return "added", None


def sort_entries(doc):
    """Sort a config document's entries by name for stable git diffs."""
    entries = doc.get("entries")
    if isinstance(entries, list):
        entries.sort(
            key=lambda item: (item.get("name") or "").lower()
            if isinstance(item, dict) else ""
        )
    return doc

"""
Panels and operators for the Node Runner node library.

The catalog itself lives in :mod:`net` as plain Python data rather than in
an RNA collection: it is remote, cache-backed data that must not be
serialized into every ``.blend``. Only the search and filter fields are
registered properties, because ``layout.prop`` needs them to be.
"""

import json
import logging
import os
import textwrap
from datetime import date

import bpy

from . import encoding, library, net, operators, preferences

log = logging.getLogger(__name__)

# Characters of the title that fit beside the apply button in a grid cell.
GRID_TITLE_CHARS = 14

# Breathing room between result rows, in Blender separator units.
ROW_GAP = 0.4

# Height of the grid preview slot, in Blender UI units.
THUMB_SCALE = 3.0

# Built-in icon name -> numeric id, resolved lazily.
_ICON_VALUES = {}

_TREE_ICON = {
    library.TREE_GEOMETRY: "GEOMETRY_NODES",
    library.TREE_SHADER: "NODE_MATERIAL",
}

# A dynamic EnumProperty items callback must keep its strings alive on the
# Python side; returning a fresh list every call lets Blender dereference
# freed memory. Mutating and returning this one module-level list is the
# standard way around it.
_repo_items = [("ALL", "All", "Show entries from every repository")]


def _repo_filter_items(self, context):
    items = [("ALL", "All", "Show entries from every repository")]
    for repo in net.repos():
        if repo.get("enabled"):
            items.append(
                (repo["key"], repo.get("name") or repo["key"], repo.get("base") or "")
            )
    _repo_items[:] = items
    return _repo_items


def _reset_page(self, context):
    """Narrowing the results must not leave you stranded on a page that no
    longer exists."""
    self.page = 0


class NODE_RUNNER_LibraryProps(bpy.types.PropertyGroup):
    """Transient search state, kept on the WindowManager so it never ends
    up saved inside a .blend."""

    search: bpy.props.StringProperty(
        name="Search",
        description="Filter setups by name, description or tag",
        options={"TEXTEDIT_UPDATE"},
        update=_reset_page,
    )  # type: ignore
    repo_filter: bpy.props.EnumProperty(
        name="Repository",
        description="Limit results to one repository",
        items=_repo_filter_items,
        update=_reset_page,
    )  # type: ignore
    type_filter: bpy.props.EnumProperty(
        name="Type",
        description="Limit results to one kind of node tree",
        items=[
            ("ALL", "All", "Shader and Geometry node setups"),
            ("GEOMETRY", "Geometry", "Geometry node setups only"),
            ("SHADER", "Shader", "Shader node setups only"),
        ],
        default="ALL",
        update=_reset_page,
    )  # type: ignore
    tag_filter: bpy.props.StringProperty(
        name="Tag",
        description="Show only setups carrying this tag",
        update=_reset_page,
    )  # type: ignore
    page: bpy.props.IntProperty(
        name="Page",
        default=0,
        min=0,
    )  # type: ignore
    page_size: bpy.props.IntProperty(
        name="Per Page",
        description="How many setups to show at once",
        default=20,
        min=1,
        soft_max=100,
        max=500,
        update=_reset_page,
    )  # type: ignore
    view_mode: bpy.props.EnumProperty(
        name="View",
        description="How to lay the results out",
        items=[
            ("GRID", "Grid", "Thumbnails in a grid", "IMGDISPLAY", 0),
            ("LIST", "List", "One row per setup, with descriptions",
             "LONGDISPLAY", 1),
        ],
        default="GRID",
    )  # type: ignore
    grid_columns: bpy.props.IntProperty(
        name="Columns",
        description="Thumbnails per row in grid view",
        default=2,
        min=1,
        soft_max=6,
        max=8,
    )  # type: ignore


# Operators


class NODE_RUNNER_OT_library_refresh(bpy.types.Operator):
    """Re-download the index from every enabled repository"""

    bl_idname = "node_runner.library_refresh"
    bl_label = "Refresh Library"

    def execute(self, context):
        keys = net.sync_repos(preferences.repo_specs(context))
        net.prune(set(keys))
        started = net.refresh()
        if not started:
            if net.is_busy():
                self.report({"INFO"}, "Already refreshing")
            elif not keys:
                self.report({"WARNING"}, "No repositories configured")
            else:
                self.report({"WARNING"}, "No enabled repositories to refresh")
            return {"CANCELLED"}
        plural = "y" if started == 1 else "ies"
        self.report({"INFO"}, f"Refreshing {started} repositor{plural}")
        return {"FINISHED"}


class NODE_RUNNER_OT_library_clear_cache(bpy.types.Operator):
    """Delete every cached index and node file"""

    bl_idname = "node_runner.library_clear_cache"
    bl_label = "Clear Library Cache"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        try:
            net.clear_cache()
        except net.LibraryError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, "Library cache cleared")
        return {"FINISHED"}


class NODE_RUNNER_OT_library_set_tag(bpy.types.Operator):
    """Filter the library by this tag"""

    bl_idname = "node_runner.library_set_tag"
    bl_label = "Filter by Tag"
    bl_options = {"INTERNAL"}

    tag: bpy.props.StringProperty()  # type: ignore

    def execute(self, context):
        context.window_manager.node_runner_lib.tag_filter = self.tag
        return {"FINISHED"}


class NODE_RUNNER_OT_library_page(bpy.types.Operator):
    """Show a different page of results"""

    bl_idname = "node_runner.library_page"
    bl_label = "Go to Page"
    bl_options = {"INTERNAL"}

    page: bpy.props.IntProperty(default=0, min=0)  # type: ignore

    def execute(self, context):
        context.window_manager.node_runner_lib.page = self.page
        return {"FINISHED"}


class NODE_RUNNER_OT_library_apply(bpy.types.Operator):
    """Download this node setup and add it to your scene"""

    bl_idname = "node_runner.library_apply"
    bl_label = "Apply Node Setup"
    bl_options = {"REGISTER", "UNDO"}

    repo_key: bpy.props.StringProperty(options={"SKIP_SAVE"})  # type: ignore
    entry_id: bpy.props.StringProperty(options={"SKIP_SAVE"})  # type: ignore
    target: bpy.props.EnumProperty(
        items=[
            ("AUTO", "Auto", "Add to the node tree being edited"),
            ("ACTIVE_OBJECT", "Active Object", "Build a new tree on the active object"),
        ],
        default="AUTO",
        options={"SKIP_SAVE"},
    )  # type: ignore

    @classmethod
    def description(cls, context, properties):
        # layout.label does not wrap, so the full description and tags live
        # in the button tooltip instead of the row.
        _repo, entry = net.find_entry(properties.repo_key, properties.entry_id)
        if entry is None:
            return "Add this node setup to your scene"
        lines = [entry["name"]]
        if entry["description"]:
            lines.append(entry["description"])
        if entry["tags"]:
            lines.append("Tags: " + ", ".join(entry["tags"]))
        if entry["author"]:
            lines.append(f"By {entry['author']}")
        if entry["blender_version"]:
            lines.append(f"Exported with Blender {entry['blender_version']}")
        return "\n".join(lines)

    def execute(self, context):
        repo, entry = net.find_entry(self.repo_key, self.entry_id)
        if repo is None:
            self.report({"ERROR"}, "That repository is no longer configured")
            return {"CANCELLED"}
        if entry is None:
            self.report(
                {"ERROR"},
                f"'{self.entry_id}' is no longer listed - press Refresh",
            )
            return {"CANCELLED"}
        if self.target == "ACTIVE_OBJECT" and context.active_object is None:
            self.report({"ERROR"}, "Select an object to apply this setup to")
            return {"CANCELLED"}

        window = context.window
        if window is not None:
            window.cursor_set("WAIT")
        try:
            raw = net.load_entry_text(repo, entry)
        except net.LibraryError as exc:
            repo["error"] = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        finally:
            if window is not None:
                window.cursor_set("DEFAULT")

        # allow_pickle=False is what makes this safe to run on data fetched
        # from a repository; it also strips payload-supplied image paths.
        return operators.import_raw(
            self, context, raw, None, None,
            allow_pickle=False, target=self.target,
        )


def _load_or_create_config(config_path, directory):
    """Read an existing config.json, or start a fresh one.

    Returns ``(doc, error)``. The document is the raw parsed JSON so that
    keys this addon does not manage survive being rewritten.
    """
    if not os.path.exists(config_path):
        folder = os.path.basename(directory.rstrip("/\\"))
        return library.new_config(name=folder), None
    try:
        with open(config_path, "r", encoding="utf-8") as handle:
            doc = json.load(handle)
    except (OSError, ValueError) as exc:
        return None, f"Could not read {config_path}: {exc}"
    if not isinstance(doc, dict):
        return None, f"{library.CONFIG_NAME} must contain a JSON object"
    doc.setdefault("schema", library.SCHEMA_VERSION)
    return doc, None


class NODE_RUNNER_OT_library_publish(bpy.types.Operator):
    """Save the selected nodes into a local library folder and index them"""

    bl_idname = "node_runner.library_publish"
    bl_label = "Publish to Library"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return operators.supported_tree_poll(context)

    def _on_name_changed(self, context):
        # Keep the slug in step with the name until the user edits it.
        self.entry_id = library.slugify(self.entry_name)

    directory: bpy.props.StringProperty(
        name="Library Folder",
        subtype="DIR_PATH",
        description="Local clone of the repository that holds config.json",
    )  # type: ignore
    entry_name: bpy.props.StringProperty(
        name="Name",
        description="Title shown in the library panel",
        update=_on_name_changed,
    )  # type: ignore
    entry_id: bpy.props.StringProperty(
        name="ID",
        description="Slug used in config.json and as the file name",
    )  # type: ignore
    entry_description: bpy.props.StringProperty(
        name="Description",
        description="One line explaining what this setup does",
    )  # type: ignore
    tags: bpy.props.StringProperty(
        name="Tags",
        description="Comma separated, e.g. vine, plant, organic",
    )  # type: ignore
    subfolder: bpy.props.StringProperty(
        name="Subfolder",
        default="nodes",
        description="Folder inside the repository to write the export into",
    )  # type: ignore
    overwrite: bpy.props.BoolProperty(
        name="Overwrite Existing",
        default=False,
        description="Replace an entry that already uses this ID",
    )  # type: ignore

    # Read by operators.build_export_payload.
    export_name: bpy.props.StringProperty(default="MyNodes", options={"HIDDEN"})  # type: ignore
    export_format: bpy.props.EnumProperty(
        name="Format",
        items=operators.FORMAT_ITEMS,
        default="JSON",
        description="JSON keeps the repository readable and diffable in git",
    )  # type: ignore
    include_image_paths: bpy.props.BoolProperty(
        name="Include Image Paths",
        default=False,
        description=(
            "Store absolute image paths. Off by default: they point at your "
            "own machine and are useless to anyone else"
        ),
    )  # type: ignore

    def invoke(self, context, event):
        prefs = preferences.get_prefs(context)
        if prefs is not None and prefs.publish_dir and not self.directory:
            self.directory = prefs.publish_dir
        if not self.entry_name:
            tree = context.space_data.edit_tree
            self.entry_name = tree.name if tree is not None else "Node Setup"
        return context.window_manager.invoke_props_dialog(
            self, width=440, confirm_text="Publish"
        )

    def draw(self, context):
        layout = self.layout
        column = layout.column()
        column.use_property_split = True
        column.use_property_decorate = False
        column.prop(self, "directory")
        column.prop(self, "entry_name")
        column.prop(self, "entry_id")
        column.prop(self, "entry_description")
        column.prop(self, "tags")
        column.separator()
        column.prop(self, "subfolder")
        column.prop(self, "export_format")
        column.prop(self, "include_image_paths")
        column.prop(self, "overwrite")

    def execute(self, context):
        directory = bpy.path.abspath((self.directory or "").strip())
        if not directory:
            self.report({"ERROR"}, "Choose a library folder")
            return {"CANCELLED"}
        if not os.path.isdir(directory):
            self.report({"ERROR"}, f"Not a folder: {directory}")
            return {"CANCELLED"}

        slug = library.slugify(self.entry_id or self.entry_name)
        name = (self.entry_name or slug).strip()
        self.export_name = name

        export_str, fmt_or_err = operators.build_export_payload(self, context)
        if export_str is None:
            self.report({"WARNING"}, fmt_or_err)
            return {"CANCELLED"}

        sub = (self.subfolder or "").strip().strip("/\\")
        relpath = f"{sub}/{slug}.json" if sub else f"{slug}.json"
        if not library.is_safe_relpath(relpath):
            self.report({"ERROR"}, f"Unsafe subfolder: {self.subfolder!r}")
            return {"CANCELLED"}

        config_path = os.path.join(directory, library.CONFIG_NAME)
        doc, error = _load_or_create_config(config_path, directory)
        if error:
            self.report({"ERROR"}, error)
            return {"CANCELLED"}

        tree = context.space_data.edit_tree
        entry = {
            "id": slug,
            "name": name,
            "description": self.entry_description.strip(),
            "file": relpath,
            "tree_type": tree.bl_idname,
            "tags": library.parse_tags(self.tags),
            "blender_version": operators.blender_version_string(),
            "updated": date.today().isoformat(),
        }
        action, error = library.upsert_entry(doc, entry, overwrite=self.overwrite)
        if error:
            self.report({"ERROR"}, error)
            return {"CANCELLED"}
        library.sort_entries(doc)

        node_path = os.path.join(directory, *relpath.split("/"))
        try:
            net.write_text_atomic(node_path, export_str)
            net.write_text_atomic(
                config_path,
                json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
            )
        except OSError as exc:
            self.report({"ERROR"}, f"Could not write to the library folder: {exc}")
            return {"CANCELLED"}

        prefs = preferences.get_prefs(context)
        if prefs is not None:
            prefs.publish_dir = self.directory

        self.report(
            {"INFO"},
            f"{action.capitalize()} '{name}' in {library.CONFIG_NAME} - "
            f"commit and push to share it",
        )
        return {"FINISHED"}




class NODE_RUNNER_OT_library_index_folder(bpy.types.Operator):
    """Scan a folder of exported node setups and write its config.json

    For a repository whose files already exist on disk - the config.json
    that Publish to Library would have maintained, generated after the fact
    """

    bl_idname = "node_runner.library_index_folder"
    bl_label = "Generate config.json"
    bl_options = {"REGISTER"}

    directory: bpy.props.StringProperty(
        name="Folder",
        subtype="DIR_PATH",
        description="Folder holding the exported node setups",
    )  # type: ignore
    library_name: bpy.props.StringProperty(
        name="Library Name",
        description="Shown as the repository title. Defaults to the folder name",
    )  # type: ignore
    recursive: bpy.props.BoolProperty(
        name="Include Subfolders",
        default=True,
        description="Also index exports in folders below this one",
    )  # type: ignore
    update_existing: bpy.props.BoolProperty(
        name="Update Existing Entries",
        default=False,
        description=(
            "Refresh entries already in config.json. Off by default so "
            "descriptions and tags you wrote by hand are left alone"
        ),
    )  # type: ignore

    def invoke(self, context, event):
        prefs = preferences.get_prefs(context)
        if prefs is not None and prefs.publish_dir and not self.directory:
            self.directory = prefs.publish_dir
        return context.window_manager.invoke_props_dialog(
            self, width=440, confirm_text="Generate"
        )

    def draw(self, context):
        layout = self.layout
        column = layout.column()
        column.use_property_split = True
        column.use_property_decorate = False
        column.prop(self, "directory")
        column.prop(self, "library_name")
        column.prop(self, "recursive")
        column.prop(self, "update_existing")

    def execute(self, context):
        directory = bpy.path.abspath((self.directory or "").strip())
        if not directory or not os.path.isdir(directory):
            self.report({"ERROR"}, f"Not a folder: {directory or '(none)'}")
            return {"CANCELLED"}

        found = self._scan(directory)
        if not found:
            self.report({"WARNING"}, "No exported node setups found in that folder")
            return {"CANCELLED"}

        config_path = os.path.join(directory, library.CONFIG_NAME)
        doc, error = _load_or_create_config(config_path, directory)
        if error:
            self.report({"ERROR"}, error)
            return {"CANCELLED"}
        if self.library_name.strip():
            doc["name"] = self.library_name.strip()

        added = updated = skipped = 0
        for entry in found:
            action, why = library.upsert_entry(
                doc, entry, overwrite=self.update_existing
            )
            if action == "added":
                added += 1
            elif action == "updated":
                updated += 1
            else:
                skipped += 1
                log.debug("Skipped %s: %s", entry["id"], why)
        library.sort_entries(doc)

        try:
            net.write_text_atomic(
                config_path,
                json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
            )
        except OSError as exc:
            self.report({"ERROR"}, f"Could not write {library.CONFIG_NAME}: {exc}")
            return {"CANCELLED"}

        parts = [f"{added} added"]
        if updated:
            parts.append(f"{updated} updated")
        if skipped:
            parts.append(f"{skipped} already listed")
        self.report(
            {"INFO"},
            f"{library.CONFIG_NAME}: {', '.join(parts)} - commit and push to share",
        )
        return {"FINISHED"}

    def _scan(self, directory):
        """Decode every export under *directory* into a config entry."""
        entries = []
        for base, dirs, files in os.walk(directory):
            dirs[:] = sorted(d for d in dirs if not d.startswith("."))
            if not self.recursive and base != directory:
                continue
            for filename in sorted(files):
                full = os.path.join(base, filename)
                relpath = os.path.relpath(full, directory).replace(os.sep, "/")
                if not library.is_export_candidate(relpath):
                    continue
                entry = self._entry_for(full, relpath, filename)
                if entry is not None:
                    entries.append(entry)
        return entries

    @staticmethod
    def _entry_for(full, relpath, filename):
        """Read one export, or return None if it isn't one."""
        try:
            with open(full, "r", encoding="utf-8") as handle:
                raw = handle.read()
        except (OSError, UnicodeDecodeError) as exc:
            log.warning("Skipping %s: %s", relpath, exc)
            return None
        try:
            fmt, payload = operators.strip_header_and_detect(raw)
            data = encoding.decode_as(payload, fmt, allow_pickle=False)
        except (ValueError, KeyError, TypeError) as exc:
            log.warning("Skipping %s: not a Node Runner export (%s)", relpath, exc)
            return None
        if not isinstance(data, dict) or "nodes" not in data:
            log.warning("Skipping %s: no nodes in it", relpath)
            return None
        stem = os.path.splitext(filename)[0]
        return library.entry_from_payload(relpath, data, stem)


# Panels


def _paragraph(layout, text, width=34, max_lines=3):
    """Draw wrapped text; layout.label has no wrapping of its own."""
    column = layout.column(align=True)
    column.scale_y = 0.7
    lines = textwrap.wrap(text, width) or [text]
    for line in lines[:max_lines]:
        column.label(text=line)
    if len(lines) > max_lines:
        column.label(text="...")


def _editor_tree_type(context):
    space = getattr(context, "space_data", None)
    if getattr(space, "type", None) != "NODE_EDITOR":
        return None
    return getattr(space, "tree_type", None)


def _draw_filters(layout, props):
    column = layout.column(align=True)
    column.prop(props, "repo_filter", text="Repo")
    column.prop(props, "type_filter", text="Type")
    if props.view_mode == "GRID":
        column.prop(props, "grid_columns", text="Columns")
    column.prop(props, "page_size", text="Per Page")
    if props.tag_filter:
        row = column.row(align=True)
        row.label(text=f"Tag: {props.tag_filter}", icon="BOOKMARKS")
        row.operator(
            NODE_RUNNER_OT_library_set_tag.bl_idname, text="", icon="X"
        ).tag = ""


def _truncate(text, limit):
    """Shorten *text* for a label, which cannot wrap or elide on its own."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 3)].rstrip() + "..."


def _icon_value(name):
    """Numeric id for a built-in icon, as template_icon wants it.

    Keeps the lookup cached because draw() runs constantly.
    """
    if name not in _ICON_VALUES:
        value = 0
        try:
            items = (
                bpy.types.UILayout.bl_rna
                .functions["operator"].parameters["icon"].enum_items
            )
            value = items[name].value
        except (KeyError, AttributeError):
            pass
        _ICON_VALUES[name] = value
    return _ICON_VALUES[name]


def _apply_button(layout, repo, entry, in_viewport, active_object, text=""):
    """The one small button that pulls a setup into the scene."""
    row = layout.row(align=True)
    if in_viewport and active_object is None:
        row.enabled = False
    props = row.operator(
        NODE_RUNNER_OT_library_apply.bl_idname, text=text, icon="ADD"
    )
    props.repo_key = repo["key"]
    props.entry_id = entry["id"]
    props.target = "ACTIVE_OBJECT" if in_viewport else "AUTO"
    return row


def _draw_entry_grid(layout, repo, entry, in_viewport, active_object):
    """A thumbnail cell: preview slot, title, then a small apply button."""
    cell = layout.column(align=True)

    # Reserved for a real preview image. Swapping icon_value for a
    # bpy.utils.previews icon_id is all this needs later.
    thumb = cell.box().column(align=True)
    thumb.alignment = "CENTER"
    thumb.template_icon(
        icon_value=_icon_value(_TREE_ICON.get(entry["tree_type"], "NODE")),
        scale=THUMB_SCALE,
    )

    footer = cell.row(align=True)
    name = footer.row(align=True)
    name.alignment = "LEFT"
    name.label(text=_truncate(entry["name"], GRID_TITLE_CHARS))
    button = footer.row(align=True)
    button.alignment = "RIGHT"
    _apply_button(button, repo, entry, in_viewport, active_object)

    cell.separator(factor=ROW_GAP)


def _draw_entry_list(layout, repo, entry, in_viewport, active_object, show_repo):
    """A compact row: name, one line of detail, small apply button."""
    row = layout.box().row(align=True)

    body = row.column(align=True)
    body.scale_y = 0.85

    head = body.row(align=True)
    head.label(
        text=entry["name"],
        icon=_TREE_ICON.get(entry["tree_type"], "NODE"),
    )
    if show_repo:
        tail = head.row()
        tail.alignment = "RIGHT"
        tail.label(text=_truncate(repo.get("name") or "", 14))

    if entry["description"]:
        body.label(text=_truncate(entry["description"], 44))
    if entry["tags"]:
        tag_row = body.row(align=True)
        tag_row.alignment = "LEFT"
        for tag in entry["tags"][:3]:
            tag_row.operator(
                NODE_RUNNER_OT_library_set_tag.bl_idname,
                text=tag,
                emboss=False,
            ).tag = tag

    side = row.row(align=True)
    side.alignment = "RIGHT"
    _apply_button(side, repo, entry, in_viewport, active_object)


def _paginate(total, page, page_size):
    """Clamp *page* against the current result count.

    Clamping here rather than writing the property back keeps draw() free of
    side effects; the filters reset the page on their own when they change.
    """
    size = max(1, page_size)
    pages = max(1, -(-total // size))
    current = min(max(page, 0), pages - 1)
    start = current * size
    return current, pages, start, min(start + size, total)


def _draw_pagination(layout, page, pages, start, end, total):
    row = layout.row(align=True)

    back = row.row(align=True)
    back.enabled = page > 0
    back.operator(
        NODE_RUNNER_OT_library_page.bl_idname, text="", icon="TRIA_LEFT"
    ).page = max(0, page - 1)

    middle = row.row(align=True)
    middle.alignment = "CENTER"
    middle.label(text=f"{start + 1}-{end} of {total}")

    forward = row.row(align=True)
    forward.enabled = page < pages - 1
    forward.operator(
        NODE_RUNNER_OT_library_page.bl_idname, text="", icon="TRIA_RIGHT"
    ).page = page + 1


def draw_library(layout, context, in_viewport):
    """Shared body of both library panels."""
    props = context.window_manager.node_runner_lib

    header = layout.row(align=True)
    header.prop(props, "search", text="", icon="VIEWZOOM")
    header.prop(props, "view_mode", text="", expand=True)
    header.operator(
        NODE_RUNNER_OT_library_refresh.bl_idname, text="", icon="FILE_REFRESH"
    )

    if not net.repos():
        box = layout.box()
        box.label(text="No repositories configured", icon="INFO")
        box.operator(
            "preferences.addon_show", text="Add a Repository", icon="PREFERENCES"
        ).module = __package__
        return

    _draw_filters(layout, props)

    if net.is_busy():
        layout.label(text="Refreshing...", icon="SORTTIME")
    for repo_name, message in net.errors():
        box = layout.box()
        box.alert = True
        box.label(text=repo_name, icon="ERROR")
        _paragraph(box, message)

    terms = library.search_terms(props.search)
    wanted = library.type_for_filter(props.type_filter)
    if wanted is None and not in_viewport:
        # A shader setup cannot be applied in a Geometry Nodes editor, so
        # offering it here would only produce an error on click.
        wanted = _editor_tree_type(context)

    rows = [
        (repo, entry)
        for repo, entry in net.all_entries(props.repo_filter)
        if library.entry_matches(entry, terms, wanted, props.tag_filter)
    ]

    if not rows:
        layout.label(text="No matching node setups", icon="INFO")
        return

    show_repo = len(net.repos()) > 1 and props.repo_filter == "ALL"
    active_object = context.active_object

    total = len(rows)
    page, pages, start, end = _paginate(total, props.page, props.page_size)
    visible = rows[start:end]

    if in_viewport and active_object is None:
        note = layout.row()
        note.scale_y = 0.7
        note.label(text="Select an object to apply to", icon="INFO")

    if props.view_mode == "GRID":
        grid = layout.grid_flow(
            row_major=True,
            columns=props.grid_columns,
            even_columns=True,
            even_rows=False,
            align=False,
        )
        for repo, entry in visible:
            _draw_entry_grid(grid, repo, entry, in_viewport, active_object)
    else:
        column = layout.column(align=False)
        for index, (repo, entry) in enumerate(visible):
            if index:
                column.separator(factor=ROW_GAP)
            _draw_entry_list(
                column, repo, entry, in_viewport, active_object, show_repo
            )

    if pages > 1:
        layout.separator()
        _draw_pagination(layout, page, pages, start, end, total)


class NODE_RUNNER_PT_library_view3d(bpy.types.Panel):
    bl_label = "Node Library"
    bl_idname = "NODE_RUNNER_PT_library_view3d"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Node Runner"

    def draw(self, context):
        draw_library(self.layout, context, in_viewport=True)


class NODE_RUNNER_PT_library_node(bpy.types.Panel):
    bl_label = "Node Library"
    bl_idname = "NODE_RUNNER_PT_library_node"
    bl_space_type = "NODE_EDITOR"
    bl_region_type = "UI"
    bl_category = "Node Runner"

    @classmethod
    def poll(cls, context):
        return operators.supported_editor_poll(context)

    def draw(self, context):
        draw_library(self.layout, context, in_viewport=False)



def draw_author(layout, context):
    """Authoring actions: build a library repository, or add to one."""
    column = layout.column(align=True)
    column.operator(
        NODE_RUNNER_OT_library_index_folder.bl_idname,
        text="Generate config.json for a Folder",
        icon="FILEBROWSER",
    )

    can_publish = operators.supported_tree_poll(context)
    row = column.row(align=True)
    row.enabled = can_publish
    row.operator(
        NODE_RUNNER_OT_library_publish.bl_idname,
        text="Publish Selected Nodes",
        icon="EXPORT",
    )
    if not can_publish:
        hint = layout.row()
        hint.scale_y = 0.7
        hint.label(text="Select nodes in a node editor to publish")


class NODE_RUNNER_PT_library_author_view3d(bpy.types.Panel):
    bl_label = "Author Library"
    bl_idname = "NODE_RUNNER_PT_library_author_view3d"
    bl_parent_id = "NODE_RUNNER_PT_library_view3d"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Node Runner"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        draw_author(self.layout, context)


class NODE_RUNNER_PT_library_author_node(bpy.types.Panel):
    bl_label = "Author Library"
    bl_idname = "NODE_RUNNER_PT_library_author_node"
    bl_parent_id = "NODE_RUNNER_PT_library_node"
    bl_space_type = "NODE_EDITOR"
    bl_region_type = "UI"
    bl_category = "Node Runner"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        draw_author(self.layout, context)


# Registration


_classes = (
    NODE_RUNNER_LibraryProps,
    NODE_RUNNER_OT_library_refresh,
    NODE_RUNNER_OT_library_clear_cache,
    NODE_RUNNER_OT_library_set_tag,
    NODE_RUNNER_OT_library_page,
    NODE_RUNNER_OT_library_apply,
    NODE_RUNNER_OT_library_publish,
    NODE_RUNNER_OT_library_index_folder,
    NODE_RUNNER_PT_library_view3d,
    NODE_RUNNER_PT_library_node,
    NODE_RUNNER_PT_library_author_view3d,
    NODE_RUNNER_PT_library_author_node,
)


def register():
    net.startup()
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.WindowManager.node_runner_lib = bpy.props.PointerProperty(
        type=NODE_RUNNER_LibraryProps
    )
    # Populate from the disk cache only - registration must never touch the
    # network, and node_data.refresh() has already made it slow enough.
    try:
        net.sync_repos(preferences.repo_specs(bpy.context))
    except (AttributeError, KeyError, OSError, RuntimeError, TypeError) as exc:
        log.warning("Could not load the library cache: %s", exc)


def unregister():
    net.shutdown()
    if hasattr(bpy.types.WindowManager, "node_runner_lib"):
        del bpy.types.WindowManager.node_runner_lib
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)

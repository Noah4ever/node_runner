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

from . import library, net, operators, preferences

log = logging.getLogger(__name__)

# Rows drawn before the panel switches to a "refine your search" hint. The
# N-panel scrolls as a whole, so an unbounded list is unusable anyway.
MAX_ROWS = 50

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


class NODE_RUNNER_LibraryProps(bpy.types.PropertyGroup):
    """Transient search state, kept on the WindowManager so it never ends
    up saved inside a .blend."""

    search: bpy.props.StringProperty(
        name="Search",
        description="Filter setups by name, description or tag",
        options={"TEXTEDIT_UPDATE"},
    )  # type: ignore
    repo_filter: bpy.props.EnumProperty(
        name="Repository",
        description="Limit results to one repository",
        items=_repo_filter_items,
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
    )  # type: ignore
    tag_filter: bpy.props.StringProperty(
        name="Tag",
        description="Show only setups carrying this tag",
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
        doc, error = self._load_or_create_config(config_path, directory)
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

    @staticmethod
    def _load_or_create_config(config_path, directory):
        """Read an existing config.json, or start a fresh one."""
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
    if props.tag_filter:
        row = column.row(align=True)
        row.label(text=f"Tag: {props.tag_filter}", icon="BOOKMARKS")
        row.operator(
            NODE_RUNNER_OT_library_set_tag.bl_idname, text="", icon="X"
        ).tag = ""


def _draw_entry(layout, repo, entry, in_viewport, active_object, show_repo):
    box = layout.box()

    title = box.row(align=True)
    title.label(
        text=entry["name"],
        icon=_TREE_ICON.get(entry["tree_type"], "NODE"),
    )
    if show_repo:
        tail = title.row()
        tail.alignment = "RIGHT"
        tail.scale_x = 0.9
        tail.label(text=repo.get("name") or "")

    if entry["description"]:
        _paragraph(box, entry["description"])

    if entry["tags"]:
        tag_row = box.row(align=True)
        for tag in entry["tags"][:4]:
            tag_row.operator(
                NODE_RUNNER_OT_library_set_tag.bl_idname,
                text=tag,
                icon="BOOKMARKS",
                emboss=False,
            ).tag = tag

    apply_row = box.row()
    if in_viewport:
        apply_row.enabled = active_object is not None
        if active_object is None:
            label = "Select an object first"
        else:
            label = f"Apply to {active_object.name}"
    else:
        label = "Add to Node Tree"
    props = apply_row.operator(
        NODE_RUNNER_OT_library_apply.bl_idname, text=label, icon="IMPORT"
    )
    props.repo_key = repo["key"]
    props.entry_id = entry["id"]
    props.target = "ACTIVE_OBJECT" if in_viewport else "AUTO"


def draw_library(layout, context, in_viewport):
    """Shared body of both library panels."""
    props = context.window_manager.node_runner_lib

    header = layout.row(align=True)
    header.prop(props, "search", text="", icon="VIEWZOOM")
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
    for repo, entry in rows[:MAX_ROWS]:
        _draw_entry(layout, repo, entry, in_viewport, active_object, show_repo)

    if len(rows) > MAX_ROWS:
        layout.label(
            text=f"{len(rows) - MAX_ROWS} more - refine your search", icon="INFO"
        )


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


# Registration


_classes = (
    NODE_RUNNER_LibraryProps,
    NODE_RUNNER_OT_library_refresh,
    NODE_RUNNER_OT_library_clear_cache,
    NODE_RUNNER_OT_library_set_tag,
    NODE_RUNNER_OT_library_apply,
    NODE_RUNNER_OT_library_publish,
    NODE_RUNNER_PT_library_view3d,
    NODE_RUNNER_PT_library_node,
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

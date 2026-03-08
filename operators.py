"""
Blender operators and UI for Node Runner import/export.
"""

import logging

import bpy

from .constants import EXPORT_HEADER
from .encoding import (
    FORMAT_HASH,
    FORMAT_JSON,
    FORMAT_XML,
    encode_as,
    decode_as,
    detect_format,
)
from .serialize import serialize_node_tree
from .deserialize import deserialize_node_tree

log = logging.getLogger(__name__)

# Blender EnumProperty items for format selection.
_FORMAT_ITEMS = [
    (FORMAT_HASH, "Hash (Base64)", "Compressed base64-encoded string (default)"),
    (FORMAT_JSON, "JSON", "Human-readable JSON"),
    (FORMAT_XML, "XML", "Human-readable XML"),
]


#  Addon preferences


class NODE_RUNNER_preferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    import_at_cursor: bpy.props.BoolProperty(
        name="Import at Cursor",
        description="Offset imported nodes to the mouse cursor position",
        default=True,
    )  # type: ignore

    select_imported: bpy.props.BoolProperty(
        name="Select Imported Nodes",
        description="Select only the imported nodes after import",
        default=True,
    )  # type: ignore

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "import_at_cursor")
        layout.prop(self, "select_imported")


def _get_prefs(context):
    """Return addon preferences, with safe fallback defaults."""
    prefs = context.preferences.addons.get(__package__)
    if prefs:
        return prefs.preferences
    return None


#  Shared helpers


def _build_export_string(data, export_name, fmt):
    """Encode *data* in the requested format and return the final string.

    For hash format the traditional ``Name__NR<base64>`` form is used.
    For JSON / XML the export name is embedded in the data so that the
    output is a valid, self-contained document.
    """
    if fmt in (FORMAT_JSON, FORMAT_XML):
        data = dict(data)
        data["export_name"] = export_name
        return encode_as(data, fmt)

    # Hash – prefix with name + header
    encoded = encode_as(data, fmt)
    return (export_name or "MyNodes") + EXPORT_HEADER + encoded


def _strip_header_and_detect(raw):
    """Strip any Node Runner header and detect the data format.

    Returns ``(format, payload)`` where *payload* is the raw data string
    ready to be decoded.
    """
    # Hash header – only used for the base64 format
    if EXPORT_HEADER in raw:
        payload = raw.split(EXPORT_HEADER, 1)[1]
        return FORMAT_HASH, payload

    # JSON / XML are valid documents – auto-detect from content
    fmt = detect_format(raw)
    return fmt, raw


def _do_import(operator, context, raw, mouse_x=None, mouse_y=None):
    """Shared import logic used by both the Import and Paste operators.

    If *mouse_x* / *mouse_y* are given the imported nodes are offset to
    that region-space position.
    """
    edit_tree = context.space_data.edit_tree
    if edit_tree is None:
        operator.report({"WARNING"}, "No active node tree to import into")
        return {"CANCELLED"}

    fmt, payload = _strip_header_and_detect(raw)

    try:
        data = decode_as(payload, fmt)
    except ValueError as exc:
        operator.report({"ERROR"}, str(exc))
        return {"CANCELLED"}

    # Pop metadata that isn't part of the node-tree payload
    data.pop("export_name", None)

    # Deselect all existing nodes
    for node in edit_tree.nodes:
        node.select = False

    # Track which nodes already exist
    existing_names = set(n.name for n in edit_tree.nodes)

    socket_id_map = {}
    deserialize_node_tree(edit_tree, data, socket_id_map)

    # Find freshly created nodes
    new_nodes = [n for n in edit_tree.nodes if n.name not in existing_names]

    # Select imported nodes
    prefs = _get_prefs(context)
    select_imported = prefs.select_imported if prefs else True
    if select_imported:
        for node in new_nodes:
            node.select = True
        if new_nodes:
            edit_tree.nodes.active = new_nodes[0]

    # Offset to mouse cursor position
    if mouse_x is not None and mouse_y is not None and new_nodes:
        try:
            region = context.region
            mouse_view = region.view2d.region_to_view(mouse_x, mouse_y)
            min_x = min(n.location.x for n in new_nodes)
            max_x = max(n.location.x + n.dimensions.x for n in new_nodes)
            min_y = min(n.location.y - n.dimensions.y for n in new_nodes)
            max_y = max(n.location.y for n in new_nodes)
            center_x = (min_x + max_x) / 2
            center_y = (min_y + max_y) / 2

            offset_x = mouse_view[0] - center_x
            offset_y = mouse_view[1] - center_y

            for node in new_nodes:
                if node.parent is None:
                    node.location.x += offset_x
                    node.location.y += offset_y
        except (AttributeError, TypeError, ValueError, RuntimeError):
            pass

    node_count = len(new_nodes)
    operator.report(
        {"INFO"}, f"Imported {node_count} node{'s' if node_count != 1 else ''}"
    )
    return {"FINISHED"}


#  Export operator


class NODE_RUNNER_OT_export(bpy.types.Operator):
    """Export selected nodes as a Node Runner string"""

    bl_idname = "node_runner.export"
    bl_label = "Export Nodes"
    bl_options = {"REGISTER", "UNDO"}

    export_name: bpy.props.StringProperty(
        name="Name",
        default="MyNodes",
        description="Label for the exported data",
    )  # type: ignore

    export_format: bpy.props.EnumProperty(
        name="Format",
        items=_FORMAT_ITEMS,
        default=FORMAT_HASH,
        description="Output format for the exported data",
    )  # type: ignore

    def execute(self, context):
        edit_tree = context.space_data.edit_tree
        if edit_tree is None:
            self.report({"WARNING"}, "No active node tree")
            return {"CANCELLED"}

        selected = context.selected_nodes or []
        names = [
            n.name
            for n in selected
            if not isinstance(n, (bpy.types.NodeGroupInput, bpy.types.NodeGroupOutput))
        ]

        if not names:
            self.report({"WARNING"}, "No exportable nodes selected")
            return {"CANCELLED"}

        data = serialize_node_tree(edit_tree, selected_node_names=names)
        export_str = _build_export_string(
            data, self.export_name or "MyNodes", self.export_format
        )

        context.window_manager.clipboard = export_str

        fmt_label = {k: v for k, v, _ in _FORMAT_ITEMS}.get(
            self.export_format, self.export_format
        )
        self.report(
            {"INFO"},
            f"Exported '{self.export_name}' as {fmt_label} — copied to clipboard",
        )
        return {"FINISHED"}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=300)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "export_name", text="Name", icon="SORTALPHA")
        layout.prop(self, "export_format", text="Format")


#  Import operators


class NODE_RUNNER_OT_import(bpy.types.Operator):
    """Import nodes from a Node Runner string or from the clipboard"""

    bl_idname = "node_runner.import_nodes"
    bl_label = "Import Nodes"
    bl_options = {"REGISTER", "UNDO"}

    from_clipboard: bpy.props.BoolProperty(
        name="From Clipboard",
        default=True,
        description="Read node data directly from the clipboard "
        "(supports hash, JSON, and XML — auto-detected)",
    )  # type: ignore

    node_runner_import_field: bpy.props.StringProperty(
        name="Hash",
        default="",
        description="Paste a Node Runner hash string",
    )  # type: ignore

    import_at_cursor: bpy.props.BoolProperty(
        name="Import at Cursor",
        description="Offset imported nodes to the mouse cursor position",
        default=True,
    )  # type: ignore

    def draw(self, context):
        layout = self.layout

        layout.prop(self, "from_clipboard", icon="PASTEDOWN")

        row = layout.row()
        row.enabled = not self.from_clipboard
        row.prop(self, "node_runner_import_field", text="", icon="TEXT")

        layout.prop(self, "import_at_cursor", icon="PIVOT_CURSOR")

    def execute(self, context):
        if self.from_clipboard:
            raw = context.window_manager.clipboard
            if not raw:
                self.report({"WARNING"}, "Clipboard is empty")
                return {"CANCELLED"}
        else:
            raw = self.node_runner_import_field
            if not raw:
                self.report({"WARNING"}, "No data provided")
                return {"CANCELLED"}

        mouse_x = getattr(self, "_mouse_x", None)
        mouse_y = getattr(self, "_mouse_y", None)

        if not self.import_at_cursor:
            mouse_x = mouse_y = None

        return _do_import(self, context, raw, mouse_x, mouse_y)

    def invoke(self, context, event):
        self._mouse_x = event.mouse_region_x
        self._mouse_y = event.mouse_region_y

        prefs = _get_prefs(context)
        if prefs:
            self.import_at_cursor = prefs.import_at_cursor

        return context.window_manager.invoke_props_dialog(self, width=420)


class NODE_RUNNER_OT_paste(bpy.types.Operator):
    """Quick-paste nodes from clipboard at the mouse cursor"""

    bl_idname = "node_runner.paste"
    bl_label = "Paste Nodes from Clipboard"
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context, event):
        self._mouse_x = event.mouse_region_x
        self._mouse_y = event.mouse_region_y
        return self.execute(context)

    def execute(self, context):
        raw = context.window_manager.clipboard
        if not raw:
            self.report({"WARNING"}, "Clipboard is empty")
            return {"CANCELLED"}

        edit_tree = context.space_data.edit_tree
        if edit_tree is None:
            self.report({"WARNING"}, "No active node tree")
            return {"CANCELLED"}

        mouse_x = getattr(self, "_mouse_x", None)
        mouse_y = getattr(self, "_mouse_y", None)

        return _do_import(self, context, raw, mouse_x, mouse_y)


#  Context menu (submenu)


class NODE_RUNNER_MT_menu(bpy.types.Menu):
    """Node Runner submenu"""

    bl_idname = "NODE_RUNNER_MT_menu"
    bl_label = "Node Runner"

    def draw(self, context):
        layout = self.layout

        layout.operator(
            NODE_RUNNER_OT_export.bl_idname,
            text="Export Selected",
            icon="EXPORT",
        )
        layout.separator()
        layout.operator(
            NODE_RUNNER_OT_import.bl_idname,
            text="Import",
            icon="IMPORT",
        )
        layout.operator(
            NODE_RUNNER_OT_paste.bl_idname,
            text="Paste from Clipboard",
            icon="PASTEDOWN",
        )


def menu_draw(self, context):
    self.layout.separator()
    self.layout.menu(NODE_RUNNER_MT_menu.bl_idname, icon="NODE")


#  Registration


_classes = (
    NODE_RUNNER_preferences,
    NODE_RUNNER_OT_export,
    NODE_RUNNER_OT_import,
    NODE_RUNNER_OT_paste,
    NODE_RUNNER_MT_menu,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.NODE_MT_context_menu.append(menu_draw)


def unregister():
    bpy.types.NODE_MT_context_menu.remove(menu_draw)
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)

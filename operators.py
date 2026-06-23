"""
Blender operators and UI for Node Runner import/export.
"""

import logging

import bpy

from .constants import EXPORT_HEADER
from .encoding import (
    FORMAT_HASH,
    FORMAT_JSON,
    FORMAT_AI_JSON,
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
    (FORMAT_JSON, "JSON", "Human-readable JSON (verbose)"),
    (
        FORMAT_AI_JSON,
        "AI JSON",
        "Compact readable JSON – ideal for AI / chat sharing",
    ),
    (FORMAT_XML, "XML", "Human-readable XML"),
]


def _blender_version_string():
    """Return the current Blender version as ``'X.Y.Z'``."""
    v = bpy.app.version
    return f"{v[0]}.{v[1]}.{v[2]}"


_SUPPORTED_TREE_TYPES = {"ShaderNodeTree", "GeometryNodeTree", "CompositorNodeTree"}

# Object types that can carry a Geometry Nodes modifier. Used when the
# user invokes Import on an empty GN editor so we know whether we can
# auto-attach a new modifier.
_GN_OBJECT_TYPES = frozenset(
    {"MESH", "CURVE", "CURVES", "POINTCLOUD", "VOLUME", "GREASEPENCIL"}
)


def _supported_editor_poll(context):
    """True when the active editor is a Shader, Geometry, or Compositor Nodes editor.

    Does NOT require an existing tree — Import will auto-create one
    when the editor is empty.
    """
    space = getattr(context, "space_data", None)
    if space is None:
        return False
    if getattr(space, "type", None) != "NODE_EDITOR":
        return False
    return getattr(space, "tree_type", None) in _SUPPORTED_TREE_TYPES


def _supported_tree_poll(context):
    """True when the active editor has a live Shader, Geometry, or Compositor node tree.

    Stricter than ``_supported_editor_poll`` — used by Export, which
    cannot run without an existing tree to read nodes from.
    """
    if not _supported_editor_poll(context):
        return False
    return getattr(context.space_data, "edit_tree", None) is not None


def _find_node_editor_tree(context, tree_type):
    """Walk every open area and return the first node-editor edit_tree
    matching *tree_type*. Used when the operator was invoked from a
    space (file browser, etc.) that has no edit_tree of its own.
    """
    screen = getattr(context, "screen", None)
    if screen is None:
        return None
    for area in screen.areas:
        if area.type != "NODE_EDITOR":
            continue
        for space in area.spaces:
            if space.type != "NODE_EDITOR":
                continue
            tree = getattr(space, "edit_tree", None)
            if tree is not None and tree.bl_idname == tree_type:
                return tree
    return None


def _ensure_default_tree(operator, context, payload_tree_type):
    """Create or enable a default tree of *payload_tree_type* so Import has somewhere to deserialize into.

    Returns the new ``NodeTree``, or ``None`` if attachment isn't
    possible (no active object, wrong object type for GN, etc.).
    """
    obj = getattr(context, "active_object", None)
    tree_name = "Imported Nodes"

    if payload_tree_type == "GeometryNodeTree":
        if obj is None:
            operator.report(
                {"ERROR"},
                "No active object to attach a new Geometry Nodes modifier to. "
                "Select an object and try again.",
            )
            return None
        if obj.type not in _GN_OBJECT_TYPES:
            operator.report(
                {"ERROR"},
                f"Cannot add Geometry Nodes to a {obj.type.title()} object",
            )
            return None
        ng = bpy.data.node_groups.new(tree_name, "GeometryNodeTree")
        # A GN modifier requires the tree to have at least a Group
        # Output node. Seed a Geometry passthrough so the modifier
        # evaluates without errors before the user wires their imported
        # nodes in.
        ng.interface.new_socket(
            "Geometry", in_out="INPUT", socket_type="NodeSocketGeometry"
        )
        ng.interface.new_socket(
            "Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry"
        )
        gi = ng.nodes.new("NodeGroupInput")
        gi.location = (-200, 0)
        go = ng.nodes.new("NodeGroupOutput")
        go.location = (200, 0)
        # Blender 4.x documents NodeLinks.new(input_socket, output_socket).
        # Some older examples use output,input, so try the documented order
        # first and fall back without aborting the import.
        try:
            ng.links.new(go.inputs[0], gi.outputs[0])
        except (RuntimeError, TypeError, ValueError):
            try:
                ng.links.new(gi.outputs[0], go.inputs[0])
            except (RuntimeError, TypeError, ValueError):
                log.debug("Could not seed Geometry passthrough link")
        mod = obj.modifiers.new(name="GeometryNodes", type="NODES")
        mod.node_group = ng
        operator.report(
            {"INFO"},
            f"Created new Geometry Nodes modifier on '{obj.name}'",
        )
        return ng

    if payload_tree_type == "ShaderNodeTree":
        if obj is None:
            operator.report(
                {"ERROR"},
                "No active object to attach a new material to. "
                "Select an object and try again.",
            )
            return None
        if not hasattr(obj.data, "materials"):
            operator.report(
                {"ERROR"},
                f"Object '{obj.name}' cannot hold materials",
            )
            return None
        mat = bpy.data.materials.new(tree_name)
        mat.use_nodes = True
        # Drop the auto-added Principled BSDF but keep the Material
        # Output — the shader needs an output node to render.
        for n in list(mat.node_tree.nodes):
            if n.bl_idname != "ShaderNodeOutputMaterial":
                mat.node_tree.nodes.remove(n)
        obj.data.materials.append(mat)
        for i, slot in enumerate(obj.material_slots):
            if slot.material is mat:
                obj.active_material_index = i
                break
        operator.report(
            {"INFO"},
            f"Created new material on '{obj.name}'",
        )
        return mat.node_tree

    if payload_tree_type == "CompositorNodeTree":
        scene = getattr(context, "scene", None)
        if scene is None:
            operator.report({"ERROR"}, "No active scene for compositor nodes")
            return None
        try:
            scene.use_nodes = True
        except (TypeError, AttributeError, RuntimeError) as exc:
            operator.report({"ERROR"}, f"Could not enable compositor nodes: {exc}")
            return None
        tree = getattr(scene, "node_tree", None)
        if tree is None:
            operator.report({"ERROR"}, "Could not access the scene compositor node tree")
            return None
        operator.report({"INFO"}, "Enabled compositor nodes for the active scene")
        return tree

    return None


# Addon preferences


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


# Shared helpers


def _strip_image_paths(data):
    """Remove ``filepath`` keys from every image dict inside *data*."""
    nodes = data.get("nodes", {})
    for node_data in nodes.values():
        if isinstance(node_data, dict):
            img = node_data.get("image")
            if isinstance(img, dict):
                img.pop("filepath", None)


def _build_export_string(data, export_name, fmt, include_image_paths=True):
    """Encode *data* in the requested format and return the final string.

    For hash format the traditional ``Name__NR<base64>`` form is used.
    For JSON / XML the export name is embedded in the data so that the
    output is a valid, self-contained document.

    The Blender version is always embedded in the data so the importer
    can warn when versions differ.
    """
    data = dict(data)
    data["blender_version"] = _blender_version_string()

    if not include_image_paths:
        _strip_image_paths(data)

    if fmt in (FORMAT_JSON, FORMAT_AI_JSON, FORMAT_XML):
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
    """Shared import logic for the clipboard and file Import operators.

    Decodes *raw*, checks the embedded Blender version, and either
    proceeds directly or pops a confirmation dialog when versions differ.
    Auto-creates a default node tree if the active editor is empty.
    """
    fmt, payload = _strip_header_and_detect(raw)

    try:
        data = decode_as(payload, fmt)
    except ValueError as exc:
        operator.report({"ERROR"}, str(exc))
        return {"CANCELLED"}

    # When invoked from a file picker, context.space_data is the file
    # browser, which has no edit_tree. Fall back to scanning open areas
    # for a node editor showing a tree of the right type.
    edit_tree = getattr(context.space_data, "edit_tree", None)
    payload_tree_type = data.get("tree_type", "ShaderNodeTree")
    if edit_tree is None or edit_tree.bl_idname != payload_tree_type:
        edit_tree = _find_node_editor_tree(context, payload_tree_type) or edit_tree

    auto_created = False
    if edit_tree is None:
        edit_tree = _ensure_default_tree(operator, context, payload_tree_type)
        if edit_tree is None:
            return {"CANCELLED"}
        auto_created = True

    # Check Blender version
    export_version = data.get("blender_version", "")
    current_version = _blender_version_string()

    if export_version and export_version != current_version:
        # Stash decoded data for the confirm operator. The confirm
        # operator re-reads ``space_data.edit_tree`` after the user
        # accepts; by then any modifier/material we just added will be
        # picked up by the editor.
        bpy.types.WindowManager.nr_pending_data = data
        bpy.types.WindowManager.nr_pending_mouse = (mouse_x, mouse_y)
        bpy.types.WindowManager.nr_pending_auto_created = auto_created
        # Keep a direct reference to the target tree. In Blender 4.2 the
        # node editor may not have refreshed immediately after we auto-create
        # a material/modifier, so relying only on context.space_data.edit_tree
        # can make the confirmation step import into None.
        bpy.types.WindowManager.nr_pending_edit_tree = edit_tree
        return bpy.ops.node_runner.confirm_import(
            "INVOKE_DEFAULT",
            export_version=export_version,
            current_version=current_version,
        )

    return _apply_import(
        operator, context, data, mouse_x, mouse_y,
        edit_tree=edit_tree, auto_created=auto_created,
    )


def _apply_import(
    operator, context, data, mouse_x=None, mouse_y=None,
    edit_tree=None, auto_created=False,
):
    """Deserialize decoded *data* into the active node tree.

    This is the second half of import, called after any version-mismatch
    confirmation has been accepted (or skipped). If *edit_tree* is
    provided, it overrides ``space_data.edit_tree`` — used when the
    caller just auto-created a tree that the editor hasn't picked up
    yet within the same operator invocation.
    """
    if edit_tree is None:
        edit_tree = context.space_data.edit_tree
    if edit_tree is None:
        operator.report({"WARNING"}, "No active node tree to import into")
        return {"CANCELLED"}

    # Reject payloads whose source tree type does not match the active editor.
    # Legacy exports (no tree_type field) are assumed to be shader and are
    # only allowed into a ShaderNodeTree.
    payload_tree_type = data.get("tree_type", "ShaderNodeTree")
    target_tree_type = edit_tree.bl_idname
    if payload_tree_type != target_tree_type:
        operator.report(
            {"ERROR"},
            f"Cannot import {payload_tree_type} data into {target_tree_type}",
        )
        return {"CANCELLED"}

    # Pop metadata that isn't part of the node-tree payload
    data.pop("export_name", None)
    data.pop("blender_version", None)

    # When we auto-created/auto-enabled the tree, remove Blender's seed
    # nodes only where they are implementation scaffolding. Geometry Nodes
    # needs a temporary passthrough group to bind a modifier; Compositor
    # Nodes creates Render Layers + Composite when scene.use_nodes is enabled.
    if auto_created:
        if edit_tree.bl_idname == "CompositorNodeTree":
            for node in list(edit_tree.nodes):
                edit_tree.nodes.remove(node)
        else:
            node_types = {
                nd.get("type") for nd in data.get("nodes", {}).values()
            }
            payload_has_output = "NodeGroupOutput" in node_types
            payload_has_input = "NodeGroupInput" in node_types
            if payload_has_output:
                for node in list(edit_tree.nodes):
                    if node.bl_idname == "NodeGroupOutput":
                        edit_tree.nodes.remove(node)
            if payload_has_input:
                for node in list(edit_tree.nodes):
                    if node.bl_idname == "NodeGroupInput":
                        edit_tree.nodes.remove(node)
            # Strip seeded interface sockets that the payload's Group I/O
            # will recreate. Only the matched directions are wiped.
            if hasattr(edit_tree, "interface") and (
                payload_has_input or payload_has_output
            ):
                for item in list(edit_tree.interface.items_tree):
                    if item.item_type != "SOCKET":
                        continue
                    if item.in_out == "INPUT" and payload_has_input:
                        edit_tree.interface.remove(item)
                    elif item.in_out == "OUTPUT" and payload_has_output:
                        edit_tree.interface.remove(item)

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

    # When we auto-created a Geometry Nodes modifier, its per-instance
    # input values were initialized before the imported tree's interface
    # sockets existed. Rebinding pushes the freshly deserialized
    # interface defaults into the modifier so a fresh import renders the
    # same result the source tree did, without the user having to type
    # in every value by hand. Then overlay any modifier_values captured
    # from the source binding so the exact look (Leaf Density = 8 etc.)
    # is reproduced — those override the interface defaults.
    if auto_created and edit_tree.bl_idname == "GeometryNodeTree":
        obj = getattr(context, "active_object", None)
        if obj is not None:
            for mod in obj.modifiers:
                if mod.type == "NODES" and mod.node_group is edit_tree:
                    mod.node_group = None
                    mod.node_group = edit_tree
                    _apply_modifier_values(
                        mod, data.get("modifier_values"), socket_id_map
                    )
                    break

    node_count = len(new_nodes)
    operator.report(
        {"INFO"}, f"Imported {node_count} node{'s' if node_count != 1 else ''}"
    )
    return {"FINISHED"}


# Export operator


def _format_extension(fmt):
    """Return the conventional file extension (with dot) for *fmt*."""
    if fmt in (FORMAT_JSON, FORMAT_AI_JSON):
        return ".json"
    if fmt == FORMAT_XML:
        return ".xml"
    return ".txt"


def _find_modifier_for_tree(context, edit_tree):
    """Return a Geometry Nodes modifier whose node_group is *edit_tree*.

    Prefers the active object's modifier so users get values from the
    binding they are looking at; falls back to the first modifier in the
    scene that uses the tree. Returns ``None`` if no modifier is bound
    or the tree isn't a Geometry Nodes tree.
    """
    if edit_tree.bl_idname != "GeometryNodeTree":
        return None
    active = getattr(context, "active_object", None)
    if active is not None:
        for mod in active.modifiers:
            if mod.type == "NODES" and mod.node_group is edit_tree:
                return mod
    for obj in bpy.data.objects:
        for mod in obj.modifiers:
            if mod.type == "NODES" and mod.node_group is edit_tree:
                return mod
    return None


def _serialize_modifier_value(value):
    """Convert a modifier socket value to a JSON-friendly representation.

    ID references (Collection, Object, Material, ...) become a small dict
    ``{"__id__": <type>, "name": <name>}`` so the importer can attempt
    to resolve them by name in the target file.
    """
    if value is None:
        return None
    if isinstance(value, bpy.types.ID):
        return {"__id__": type(value).__name__, "name": value.name}
    if hasattr(value, "__len__") and not isinstance(value, str):
        try:
            return [float(x) for x in value]
        except (TypeError, ValueError):
            return list(value)
    return value


def _collect_modifier_values(mod):
    """Capture per-instance modifier values keyed by socket identifier.

    Skips the ``_use_attribute`` / ``_attribute_name`` companion keys —
    those are toggle metadata, not the user-facing values.
    """
    out = {}
    for key in mod.keys():
        if key.endswith("_use_attribute") or key.endswith("_attribute_name"):
            continue
        out[key] = _serialize_modifier_value(mod[key])
    return out


def _apply_modifier_values(mod, values, socket_id_map):
    """Restore per-instance modifier values captured at export time.

    Identifiers are remapped through *socket_id_map* because creating
    interface sockets during deserialize allocates fresh IDs. ID
    references (collections, objects, materials) are resolved by name;
    if the target file doesn't have that data block, the slot is left
    unset rather than crashing the import.
    """
    if not values:
        return
    for old_id, raw_value in values.items():
        new_id = socket_id_map.get(old_id, old_id)
        try:
            value = _resolve_id_value(raw_value)
        except (TypeError, KeyError):
            continue
        if value is None and isinstance(raw_value, dict) and "__id__" in raw_value:
            # ID reference that doesn't exist in this file — skip
            continue
        try:
            mod[new_id] = value
        except (TypeError, KeyError, AttributeError):
            log.debug("Could not set modifier value '%s'", new_id)


def _resolve_id_value(payload):
    """Resolve a serialized ID dict back to a Blender ID block by name.

    Returns ``None`` if no matching ID exists in the current file.
    """
    if not isinstance(payload, dict) or "__id__" not in payload:
        return payload
    type_to_data = {
        "Collection": bpy.data.collections,
        "Object": bpy.data.objects,
        "Material": bpy.data.materials,
        "Image": bpy.data.images,
        "Texture": bpy.data.textures,
        "World": bpy.data.worlds,
    }
    data_block = type_to_data.get(payload["__id__"])
    if data_block is None:
        return None
    return data_block.get(payload["name"])


def _build_export_payload(operator, context):
    """Serialize the selected nodes for *operator*.

    Returns ``(export_str, fmt_label)`` on success or ``(None, error_msg)``.
    """
    edit_tree = context.space_data.edit_tree
    if edit_tree is None:
        return None, "No active node tree"

    selected = context.selected_nodes or []
    names = [n.name for n in selected]
    if not names:
        return None, "No exportable nodes selected"

    data = serialize_node_tree(edit_tree, selected_node_names=names)

    # Capture modifier values so re-imports recreate the same look the
    # source object had, not just the tree's interface defaults.
    mod = _find_modifier_for_tree(context, edit_tree)
    if mod is not None:
        data["modifier_values"] = _collect_modifier_values(mod)

    export_str = _build_export_string(
        data,
        operator.export_name or "MyNodes",
        operator.export_format,
        include_image_paths=operator.include_image_paths,
    )
    fmt_label = {k: v for k, v, _ in _FORMAT_ITEMS}.get(
        operator.export_format, operator.export_format
    )
    return export_str, fmt_label


class NODE_RUNNER_OT_export_clipboard(bpy.types.Operator):
    """Copy selected nodes to the clipboard as a Node Runner string"""

    bl_idname = "node_runner.export_clipboard"
    bl_label = "Copy to Clipboard"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _supported_tree_poll(context)

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
    include_image_paths: bpy.props.BoolProperty(
        name="Include Image Paths",
        default=True,
        description=(
            "Store absolute file paths for image textures so they "
            "can be loaded automatically on import"
        ),
    )  # type: ignore

    def invoke(self, context, event):
        # Use a standard property dialog. The OK button is renamed to
        # "Copy to Clipboard" so there is no ambiguity about what
        # confirming the dialog does.
        return context.window_manager.invoke_props_dialog(
            self, width=320, confirm_text="Copy to Clipboard"
        )

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        col.use_property_split = True
        col.use_property_decorate = False
        col.prop(self, "export_name", text="Name")
        col.prop(self, "export_format", text="Format")
        col.prop(self, "include_image_paths")

    def execute(self, context):
        export_str, fmt_or_err = _build_export_payload(self, context)
        if export_str is None:
            self.report({"WARNING"}, fmt_or_err)
            return {"CANCELLED"}
        context.window_manager.clipboard = export_str
        self.report(
            {"INFO"},
            f"Exported '{self.export_name}' as {fmt_or_err} - copied to clipboard",
        )
        return {"FINISHED"}


class NODE_RUNNER_OT_export_file(bpy.types.Operator):
    """Save selected nodes to a file as a Node Runner string"""

    bl_idname = "node_runner.export_file"
    bl_label = "Save to File"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _supported_tree_poll(context)

    # File-browser fields
    filepath: bpy.props.StringProperty(
        subtype="FILE_PATH", options={"SKIP_SAVE"}
    )  # type: ignore
    filter_glob: bpy.props.StringProperty(
        default="*.txt;*.json;*.xml;*.nr", options={"HIDDEN", "SKIP_SAVE"}
    )  # type: ignore

    # Operator options shown in the file browser sidebar.
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
    include_image_paths: bpy.props.BoolProperty(
        name="Include Image Paths",
        default=True,
        description=(
            "Store absolute file paths for image textures so they "
            "can be loaded automatically on import"
        ),
    )  # type: ignore

    def invoke(self, context, event):
        if not self.filepath:
            ext = _format_extension(self.export_format)
            base = (self.export_name or "MyNodes").strip() or "MyNodes"
            self.filepath = base + ext
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        if not self.filepath:
            self.report({"ERROR"}, "No file path provided")
            return {"CANCELLED"}
        # If the user typed an extension that disagrees with the
        # selected format, infer the format from the extension so the
        # file content matches what the OS expects.
        lower = self.filepath.lower()
        if lower.endswith(".json") and self.export_format not in (FORMAT_JSON, FORMAT_AI_JSON):
            self.export_format = FORMAT_JSON
        elif lower.endswith(".xml") and self.export_format != FORMAT_XML:
            self.export_format = FORMAT_XML

        export_str, fmt_or_err = _build_export_payload(self, context)
        if export_str is None:
            self.report({"WARNING"}, fmt_or_err)
            return {"CANCELLED"}
        try:
            with open(self.filepath, "w", encoding="utf-8") as fp:
                fp.write(export_str)
        except OSError as exc:
            self.report({"ERROR"}, f"Could not write file: {exc}")
            return {"CANCELLED"}
        self.report(
            {"INFO"},
            f"Exported '{self.export_name}' as {fmt_or_err} to {self.filepath}",
        )
        return {"FINISHED"}


# Import operators


class NODE_RUNNER_OT_import_clipboard(bpy.types.Operator):
    """Import nodes from the clipboard"""

    bl_idname = "node_runner.import_clipboard"
    bl_label = "From Clipboard"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _supported_editor_poll(context)

    import_at_cursor: bpy.props.BoolProperty(
        name="Import at Cursor",
        description="Offset imported nodes to the mouse cursor position",
        default=True,
    )  # type: ignore

    def invoke(self, context, event):
        self._mouse_x = event.mouse_region_x
        self._mouse_y = event.mouse_region_y
        prefs = _get_prefs(context)
        if prefs:
            self.import_at_cursor = prefs.import_at_cursor
        return self.execute(context)

    def execute(self, context):
        raw = context.window_manager.clipboard
        if not raw:
            self.report({"WARNING"}, "Clipboard is empty")
            return {"CANCELLED"}
        if self.import_at_cursor:
            mouse_x = getattr(self, "_mouse_x", None)
            mouse_y = getattr(self, "_mouse_y", None)
        else:
            mouse_x = mouse_y = None
        return _do_import(self, context, raw, mouse_x, mouse_y)


class NODE_RUNNER_OT_import_file(bpy.types.Operator):
    """Import nodes from a file"""

    bl_idname = "node_runner.import_file"
    bl_label = "Open File"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _supported_editor_poll(context)

    filepath: bpy.props.StringProperty(
        subtype="FILE_PATH", options={"SKIP_SAVE"}
    )  # type: ignore
    filter_glob: bpy.props.StringProperty(
        default="*.txt;*.json;*.xml;*.nr", options={"HIDDEN", "SKIP_SAVE"}
    )  # type: ignore

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        if not self.filepath:
            self.report({"ERROR"}, "No file path provided")
            return {"CANCELLED"}
        try:
            with open(self.filepath, "r", encoding="utf-8") as fp:
                raw = fp.read()
        except OSError as exc:
            self.report({"ERROR"}, f"Could not read file: {exc}")
            return {"CANCELLED"}
        if not raw.strip():
            self.report({"WARNING"}, "File is empty")
            return {"CANCELLED"}
        # File-picker import has no spatial mouse context — drop nodes
        # at the tree's existing center rather than at a stale cursor.
        return _do_import(self, context, raw, None, None)


# Version-mismatch confirmation


class NODE_RUNNER_OT_confirm_import(bpy.types.Operator):
    """Confirm import when the Blender version differs"""

    bl_idname = "node_runner.confirm_import"
    bl_label = "Version Mismatch"
    bl_options = {"INTERNAL"}

    export_version: bpy.props.StringProperty()  # type: ignore
    current_version: bpy.props.StringProperty()  # type: ignore

    def draw(self, context):
        layout = self.layout
        layout.label(text="Blender version mismatch!", icon="ERROR")
        layout.label(text=f"Exported with: {self.export_version}")
        layout.label(text=f"Current:       {self.current_version}")
        layout.separator()
        layout.label(text="Node data may not import correctly.")
        layout.label(text="Continue anyway?")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=320)

    def execute(self, context):
        # Retrieve stashed data from _do_import
        data = getattr(bpy.types.WindowManager, "nr_pending_data", None)
        mouse = getattr(bpy.types.WindowManager, "nr_pending_mouse", (None, None))
        auto_created = getattr(
            bpy.types.WindowManager, "nr_pending_auto_created", False
        )
        edit_tree = getattr(bpy.types.WindowManager, "nr_pending_edit_tree", None)

        if data is None:
            self.report({"ERROR"}, "No pending import data")
            return {"CANCELLED"}

        # Clean up
        del bpy.types.WindowManager.nr_pending_data
        del bpy.types.WindowManager.nr_pending_mouse
        if hasattr(bpy.types.WindowManager, "nr_pending_auto_created"):
            del bpy.types.WindowManager.nr_pending_auto_created
        if hasattr(bpy.types.WindowManager, "nr_pending_edit_tree"):
            del bpy.types.WindowManager.nr_pending_edit_tree

        return _apply_import(
            self, context, data, mouse[0], mouse[1],
            edit_tree=edit_tree, auto_created=auto_created,
        )


# Context menu (submenu)


class NODE_RUNNER_MT_menu(bpy.types.Menu):
    """Node Runner submenu"""

    bl_idname = "NODE_RUNNER_MT_menu"
    bl_label = "Node Runner"

    def draw(self, context):
        layout = self.layout

        layout.label(text="Export", icon="EXPORT")
        layout.operator(
            NODE_RUNNER_OT_export_clipboard.bl_idname,
            text="Copy to Clipboard",
            icon="COPYDOWN",
        )
        layout.operator(
            NODE_RUNNER_OT_export_file.bl_idname,
            text="Save to File...",
            icon="FILE_TICK",
        )

        layout.separator()

        layout.label(text="Import", icon="IMPORT")
        layout.operator(
            NODE_RUNNER_OT_import_clipboard.bl_idname,
            text="Paste from Clipboard",
            icon="PASTEDOWN",
        )
        layout.operator(
            NODE_RUNNER_OT_import_file.bl_idname,
            text="Open File...",
            icon="FILE_FOLDER",
        )


def menu_draw(self, context):
    if not _supported_editor_poll(context):
        return
    self.layout.separator()
    self.layout.menu(NODE_RUNNER_MT_menu.bl_idname, icon="NODE")


# Registration


_classes = (
    NODE_RUNNER_preferences,
    NODE_RUNNER_OT_export_clipboard,
    NODE_RUNNER_OT_export_file,
    NODE_RUNNER_OT_confirm_import,
    NODE_RUNNER_OT_import_clipboard,
    NODE_RUNNER_OT_import_file,
    NODE_RUNNER_MT_menu,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.NODE_MT_context_menu.append(menu_draw)


def unregister():
    try:
        bpy.types.NODE_MT_context_menu.remove(menu_draw)
    except (AttributeError, ValueError, RuntimeError):
        pass
    for cls in reversed(_classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass

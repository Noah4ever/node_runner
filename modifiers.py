"""
Geometry Nodes modifier binding helpers.

A Geometry Nodes setup only looks right when the modifier's per-instance
input values come along with the node tree, and how those values are
reached changed between Blender 4.x and 5.2: 4.x exposed them as
IDProperties on the modifier, while 5.2 dropped that and the node group's
interface socket defaults became the live values. Everything that has to
straddle both lives here.
"""

import logging

import bpy

log = logging.getLogger(__name__)


def find_modifier_for_tree(context, edit_tree):
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


def reinit_gn_modifier(obj, node_group):
    """Re-create *obj*'s NODES modifier bound to *node_group*.

    Returns the fresh modifier (or ``None`` if no matching modifier was
    found). A newly added modifier initializes all of its inputs from the
    node group's current interface defaults, which is the only reliable
    way to push those defaults into the binding on Blender 5.2. The
    auto-created modifier is the most recent one, so re-adding keeps it in
    the same (last) slot.
    """
    old = None
    for mod in obj.modifiers:
        if mod.type == "NODES" and mod.node_group is node_group:
            old = mod
            break
    if old is None:
        return None
    name = old.name
    obj.modifiers.remove(old)
    new_mod = obj.modifiers.new(name=name, type="NODES")
    new_mod.node_group = node_group
    return new_mod


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


def collect_modifier_values(mod):
    """Capture per-instance modifier values keyed by socket identifier.

    Skips the ``_use_attribute`` / ``_attribute_name`` companion keys —
    those are toggle metadata, not the user-facing values.

    Blender 4.x exposed a GN modifier's inputs as IDProperties
    (``mod["Socket_3"]``). Blender 5.2 dropped that — ``mod.keys()`` and
    item access raise ``TypeError`` — so we fall back to the node group's
    interface socket defaults, which are the live input values there.
    """
    try:
        keys = list(mod.keys())
    except TypeError:
        return _collect_interface_values(mod.node_group)
    out = {}
    for key in keys:
        if key.endswith("_use_attribute") or key.endswith("_attribute_name"):
            continue
        out[key] = _serialize_modifier_value(mod[key])
    return out


def _interface_input_sockets(node_group):
    """Yield the INPUT interface sockets of *node_group* (5.2-safe)."""
    if node_group is None:
        return
    items = getattr(getattr(node_group, "interface", None), "items_tree", None)
    if not items:
        return
    for item in items:
        if getattr(item, "item_type", None) != "SOCKET":
            continue
        if getattr(item, "in_out", None) != "INPUT":
            continue
        if not hasattr(item, "default_value"):
            continue
        yield item


def _collect_interface_values(node_group):
    """Capture INPUT interface socket defaults keyed by identifier.

    Used on Blender 5.2+, where GN modifier inputs are no longer
    IDProperties and the interface default *is* the input value.
    """
    return {
        item.identifier: _serialize_modifier_value(item.default_value)
        for item in _interface_input_sockets(node_group)
    }


def apply_modifier_values(mod, values, socket_id_map):
    """Restore per-instance modifier values captured at export time.

    Identifiers are remapped through *socket_id_map* because creating
    interface sockets during deserialize allocates fresh IDs. ID
    references (collections, objects, materials) are resolved by name;
    if the target file doesn't have that data block, the slot is left
    unset rather than crashing the import.
    """
    if not values:
        return
    node_group = getattr(mod, "node_group", None)
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
            # Blender 5.2+: GN modifier inputs aren't IDProperties, so the
            # item assignment above isn't available. Write the value onto
            # the interface socket default instead — that's the live input.
            if not _set_interface_default(node_group, new_id, value):
                log.debug("Could not set modifier value '%s'", new_id)


def _set_interface_default(node_group, identifier, value):
    """Set an interface socket's default by identifier (Blender 5.2+).

    Returns ``True`` if a matching socket was found and assigned.
    """
    for item in _interface_input_sockets(node_group):
        if item.identifier != identifier:
            continue
        try:
            item.default_value = value
        except (TypeError, ValueError):
            log.debug("Could not set interface default '%s'", identifier)
        return True
    return False


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

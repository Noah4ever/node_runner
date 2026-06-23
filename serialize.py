"""
Serialization module for Node Runner.

Converts Blender node trees into plain Python dicts that can be
encoded and shared as strings.
"""

import logging
import pickle

import bpy
import mathutils

from .constants import EXCLUDE_NODE_PROPS, SERIALIZE_READONLY_PROPS, PAIRED_NODE_TYPES

log = logging.getLogger(__name__)

def _node_absolute_location(node):
    """Return node location in absolute canvas coordinates.

    Blender 4.5 exposes ``Node.location_absolute`` for this directly, but
    Blender 4.2 does not expose it on all node classes.  Reconstruct it
    from ``location`` and parent frames so export still works in 4.2.
    """
    loc_abs = getattr(node, "location_absolute", None)
    if loc_abs is not None:
        return [float(loc_abs[0]), float(loc_abs[1])]

    loc = getattr(node, "location", (0.0, 0.0))
    x = float(loc[0]) if len(loc) > 0 else 0.0
    y = float(loc[1]) if len(loc) > 1 else 0.0

    parent = getattr(node, "parent", None)
    if parent is not None:
        parent_abs = _node_absolute_location(parent)
        x += float(parent_abs[0])
        y += float(parent_abs[1])

    return [x, y]


# Primitive / math type serializers


def serialize_color(color):
    """Serialize a Color to a list of floats."""
    return list(color)


def serialize_vector(vector):
    """Serialize a Vector to a list of floats."""
    return list(vector)


def serialize_euler(euler):
    """Serialize an Euler to a list of floats."""
    return list(euler)


# Complex type serializers


def serialize_color_ramp(node):
    """Serialize a ColorRamp attached to *node*."""
    ramp = node.color_ramp
    return {
        "color_mode": ramp.color_mode,
        "hue_interpolation": ramp.hue_interpolation,
        "interpolation": ramp.interpolation,
        "elements": [
            {"position": el.position, "color": list(el.color)} for el in ramp.elements
        ],
    }


def serialize_color_mapping(node):
    """Serialize a ColorMapping block attached to *node*."""
    cm = node.color_mapping
    return {
        "blend_color": serialize_color(cm.blend_color),
        "blend_factor": cm.blend_factor,
        "blend_type": cm.blend_type,
        "brightness": cm.brightness,
        "color_ramp": serialize_color_ramp(cm),
        "contrast": cm.contrast,
        "saturation": cm.saturation,
        "use_color_ramp": cm.use_color_ramp,
    }


def serialize_texture_mapping(node):
    """Serialize a TexMapping block attached to *node*."""
    tm = node.texture_mapping
    return {
        "mapping": tm.mapping,
        "mapping_x": tm.mapping_x,
        "mapping_y": tm.mapping_y,
        "mapping_z": tm.mapping_z,
        "max": serialize_vector(tm.max),
        "min": serialize_vector(tm.min),
        "rotation": serialize_vector(tm.rotation),
        "scale": serialize_vector(tm.scale),
        "translation": serialize_vector(tm.translation),
        "use_max": tm.use_max,
        "use_min": tm.use_min,
        "vector_type": tm.vector_type,
    }


def serialize_curve_mapping(node):
    """Serialize a CurveMapping block attached to *node*."""
    mapping = node.mapping
    return {
        "black_level": serialize_attr(node, mapping.black_level),
        "clip_max_x": mapping.clip_max_x,
        "clip_max_y": mapping.clip_max_y,
        "clip_min_x": mapping.clip_min_x,
        "clip_min_y": mapping.clip_min_y,
        "curves": serialize_attr(node, mapping.curves),
        "extend": mapping.extend,
        "tone": mapping.tone,
        "use_clip": mapping.use_clip,
        "white_level": serialize_attr(node, mapping.white_level),
    }


def serialize_curve_map(node, curve_map):
    """Serialize a single CurveMap."""
    return {
        "points": serialize_attr(node, curve_map.points),
    }


def serialize_curve_map_point(node, point):
    """Serialize a single CurveMapPoint."""
    return {
        "handle_type": point.handle_type,
        "location": serialize_attr(node, point.location),
        "select": point.select,
    }


def serialize_image(image):
    """Serialize an Image reference (name + absolute filepath when available)."""
    result = {"name": image.name}
    raw_path = getattr(image, "filepath", "")
    if raw_path:
        result["filepath"] = bpy.path.abspath(raw_path)
    return result


def serialize_id_reference(id_block):
    """Serialize a Blender ID pointer by type and name.

    This is especially useful for compositor nodes such as Render Layers,
    Movie Clip, and Mask nodes. The importer will resolve the reference by
    name if the target .blend already contains the same data-block.
    """
    if id_block is None:
        return None
    return {"__id__": type(id_block).__name__, "name": getattr(id_block, "name", "")}


def serialize_output_file_slots(node):
    """Serialize compositor File Output node slot layout defensively."""
    result = {}
    for collection_name in ("file_slots", "layer_slots"):
        slots = getattr(node, collection_name, None)
        if slots is None:
            continue
        entries = []
        try:
            iterator = list(slots)
        except (TypeError, RuntimeError):
            continue
        for slot in iterator:
            entry = {}
            for attr_name in ("name", "path", "use_node_format", "save_as_render"):
                if hasattr(slot, attr_name):
                    try:
                        entry[attr_name] = getattr(slot, attr_name)
                    except (TypeError, AttributeError, RuntimeError):
                        pass
            entries.append(entry)
        result[collection_name] = entries
    return result


def serialize_text_line(text_line):
    """Serialize one TextLine."""
    return {"body": text_line.body}


def serialize_text(text):
    """Serialize a Text data-block."""
    return {
        "current_character": text.current_character,
        "current_line": serialize_text_line(text.current_line),
        "current_line_index": text.current_line_index,
        "filepath": text.filepath,
        "indentation": text.indentation,
        "lines": [serialize_text_line(line) for line in text.lines],
        "select_end_character": text.select_end_character,
        "select_end_line_index": text.select_end_line_index,
        "use_module": text.use_module,
    }


# Generic attribute dispatcher


def serialize_attr(node, attr):
    """Serialize an arbitrary node attribute by dispatching on type.

    Falls back to returning the value directly if it is pickle-safe.
    Logs a warning for unsupported types.
    """
    # Dispatch table: type -> serializer callable. Build it defensively so
    # Blender 4.2 does not fail if a class name from a newer Blender build is
    # absent.
    _dispatch = {
        mathutils.Color: serialize_color,
        mathutils.Vector: serialize_vector,
        mathutils.Euler: serialize_euler,
    }

    def _add_type(type_name, serializer):
        data_type = getattr(bpy.types, type_name, None)
        if data_type is not None:
            _dispatch[data_type] = serializer

    _add_type("ColorRamp", lambda _: serialize_color_ramp(node))
    _add_type("NodeTree", lambda _: serialize_node_tree(node.node_tree))
    _add_type("ColorMapping", lambda _: serialize_color_mapping(node))
    _add_type("TexMapping", lambda _: serialize_texture_mapping(node))
    _add_type("CurveMapping", lambda _: serialize_curve_mapping(node))
    _add_type("CurveMap", lambda d: serialize_curve_map(node, d))
    _add_type("CurveMapPoint", lambda d: serialize_curve_map_point(node, d))
    _add_type("Image", serialize_image)
    for _id_type in (
        "Scene",
        "MovieClip",
        "Mask",
        "Object",
        "Collection",
        "Material",
        "Texture",
        "World",
    ):
        _add_type(_id_type, serialize_id_reference)
    _add_type("ImageUser", lambda _: {})
    _add_type("NodeFrame", lambda _: {})  # Handled separately
    _add_type("Text", lambda _: serialize_text(node.script))
    _add_type(
        "NodeSocketStandard",
        lambda d: (
            serialize_attr(node, d.default_value)
            if hasattr(d, "default_value")
            else None
        ),
    )
    _add_type(
        "bpy_prop_collection",
        lambda d: [serialize_attr(node, el) for el in d.values()],
    )
    _add_type("bpy_prop_array", lambda d: [serialize_attr(node, el) for el in d])

    for data_type, serializer in _dispatch.items():
        if isinstance(attr, data_type):
            return serializer(attr)

    # Fallback: check if pickle-safe
    try:
        pickle.dumps(attr)
    except (pickle.PicklingError, TypeError, AttributeError):
        log.warning(
            "Cannot serialize attribute on node '%s': value=%r type=%s",
            node.name,
            attr,
            type(attr).__name__,
        )
        return None
    return attr


# Node serialization


def _socket_entry(node, s, iface_by_id):
    """Build a socket dict for group input/output ordering, with default if available."""
    entry = {"type": s.bl_idname, "name": s.name, "identifier": s.identifier}
    iface = iface_by_id.get(s.identifier)
    if iface is not None and hasattr(iface, "default_value"):
        dv = iface.default_value
        if dv is not None and not isinstance(dv, bpy.types.ID):
            try:
                entry["default"] = serialize_attr(node, dv)
            except (TypeError, ValueError):
                pass
    return entry


def _prune_group_interface_orders_to_exported_links(data):
    """Trim Group Input/Output interface orders to linked sockets only.

    A Group Input node in Blender shows every INPUT socket of the group
    interface, regardless of how many of those sockets the selected snippet
    actually uses. This keeps copied snippets compact on paste.
    """
    nodes = data.get("nodes", {})
    used_group_input_outputs = {}
    used_group_output_inputs = {}

    for link in data.get("links", []):
        from_name = link.get("from_node")
        to_name = link.get("to_node")
        from_node = nodes.get(from_name, {})
        to_node = nodes.get(to_name, {})

        if from_node.get("type") == "NodeGroupInput":
            ident = link.get("from_socket_identifier")
            if ident:
                used_group_input_outputs.setdefault(from_name, set()).add(ident)

        if to_node.get("type") == "NodeGroupOutput":
            ident = link.get("to_socket_identifier")
            if ident:
                used_group_output_inputs.setdefault(to_name, set()).add(ident)

    for node_name, node_data in nodes.items():
        node_type = node_data.get("type")
        if node_type == "NodeGroupInput":
            used = used_group_input_outputs.get(node_name, set())
            if "output_order" in node_data:
                node_data["output_order"] = [
                    item
                    for item in node_data.get("output_order", [])
                    if item.get("identifier") in used
                ]
        elif node_type == "NodeGroupOutput":
            used = used_group_output_inputs.get(node_name, set())
            if "input_order" in node_data:
                node_data["input_order"] = [
                    item
                    for item in node_data.get("input_order", [])
                    if item.get("identifier") in used
                ]


def _compact_group_input_nodes_in_payload(data):
    """Collapse selected-snippet Group Input instances into one payload node."""
    nodes = data.get("nodes", {})
    links = data.get("links", [])
    group_input_names = [
        name for name, node_data in nodes.items()
        if node_data.get("type") == "NodeGroupInput"
    ]
    if len(group_input_names) <= 1:
        return

    linked_from = {
        link.get("from_node")
        for link in links
        if nodes.get(link.get("from_node"), {}).get("type") == "NodeGroupInput"
    }
    if not linked_from:
        for name in group_input_names:
            nodes.pop(name, None)
        return

    def used_count(name):
        return sum(1 for link in links if link.get("from_node") == name)

    def loc_x(name):
        loc = nodes.get(name, {}).get("location_absolute") or nodes.get(name, {}).get("location") or [0, 0]
        try:
            return float(loc[0])
        except (TypeError, ValueError, IndexError):
            return 0.0

    primary = sorted(linked_from, key=lambda n: (-used_count(n), loc_x(n), n))[0]
    primary_data = nodes[primary]

    used_identifiers = {
        link.get("from_socket_identifier")
        for link in links
        if nodes.get(link.get("from_node"), {}).get("type") == "NodeGroupInput"
        and link.get("from_socket_identifier")
    }

    order = {}
    i = 0
    by_identifier = {}
    for name in group_input_names:
        for item in nodes.get(name, {}).get("output_order", []):
            ident = item.get("identifier")
            if ident and ident not in order:
                order[ident] = i
                i += 1
            if ident in used_identifiers and ident not in by_identifier:
                by_identifier[ident] = item

    for link in links:
        if nodes.get(link.get("from_node"), {}).get("type") != "NodeGroupInput":
            continue
        ident = link.get("from_socket_identifier")
        if ident and ident not in by_identifier:
            by_identifier[ident] = {
                "type": link.get("from_socket_type", "NodeSocketFloat"),
                "name": link.get("from_socket", ""),
                "identifier": ident,
            }
        link["from_node"] = primary

    primary_data["output_order"] = sorted(
        by_identifier.values(), key=lambda item: order.get(item.get("identifier"), 10_000)
    )

    for name in group_input_names:
        if name != primary:
            nodes.pop(name, None)

    data["group_input_policy"] = "single_compact"


def serialize_node(node):
    """Serialize all properties of a single node into a dict.

    Uses ``bl_rna.properties`` for fast, reliable property iteration
    instead of ``dir()``.
    """
    node_dict = {}

    # Use RNA introspection for reliable, fast iteration
    for prop in node.bl_rna.properties:
        prop_name = prop.identifier
        if prop_name in EXCLUDE_NODE_PROPS:
            continue
        if prop.is_readonly and prop_name not in SERIALIZE_READONLY_PROPS:
            continue

        try:
            attr = getattr(node, prop_name)
        except AttributeError:
            continue

        if attr is None:
            continue

        # Parent frame: store name only
        if prop_name == "parent":
            node_dict["parent"] = node.parent.name
            continue

        # Group input/output socket ordering
        if node.bl_idname in ("NodeGroupInput", "NodeGroupOutput"):
            tree = getattr(node, "id_data", None)
            iface_by_id = {}
            iface_items = getattr(getattr(tree, "interface", None), "items_tree", None)
            if iface_items is not None:
                for item in iface_items:
                    if getattr(item, "item_type", None) == "SOCKET":
                        iface_by_id[item.identifier] = item

            if prop_name == "inputs":
                node_dict["input_order"] = [
                    _socket_entry(node, s, iface_by_id)
                    for s in node.inputs
                    if s.bl_idname != "NodeSocketVirtual"
                ]
            if prop_name == "outputs":
                node_dict["output_order"] = [
                    _socket_entry(node, s, iface_by_id)
                    for s in node.outputs
                    if s.bl_idname != "NodeSocketVirtual"
                ]

        node_dict[prop_name] = serialize_attr(node, attr)

    # Always include bl_idname as "type" and label
    node_dict["type"] = node.bl_idname
    node_dict["label"] = node.label

    # Store absolute location for correct nested-frame positioning.
    # Blender 4.2 does not expose node.location_absolute on all nodes.
    node_dict["location_absolute"] = _node_absolute_location(node)

    # Compositor File Output nodes store their per-input slot names/paths in
    # a collection, not in normal socket default values. Preserve that layout
    # so pasted compositor setups keep their output passes organized.
    if node.bl_idname == "CompositorNodeOutputFile":
        node_dict["file_output_slots"] = serialize_output_file_slots(node)

    # Store paired output reference for zone nodes (repeat, simulation, etc.)
    if node.bl_idname in PAIRED_NODE_TYPES:
        attr_name = PAIRED_NODE_TYPES[node.bl_idname]
        paired = getattr(node, attr_name, None)
        if paired is not None:
            node_dict["_paired_output"] = paired.name

    return node_dict


def serialize_node_tree(node_tree, selected_node_names=None):
    """Serialize a complete node tree (nodes + links).

    Args:
        node_tree: The Blender NodeTree to serialize.
        selected_node_names: Optional list of node names to include.
            If ``None``, all nodes are included.

    Returns:
        dict with keys ``"nodes"``, ``"links"``, ``"name"``.
    """
    nodes = node_tree.nodes
    data = {
        "nodes": {},
        "links": [],
        "name": node_tree.name,
        "tree_type": node_tree.bl_idname,
    }

    if selected_node_names is None:
        selected_nodes = list(nodes)
    else:
        selected_nodes = [nodes[name] for name in selected_node_names if name in nodes]

    # Also include parent frames of selected nodes
    extra_frames = set()
    for node in selected_nodes:
        parent = node.parent
        while parent is not None:
            if parent.name not in {n.name for n in selected_nodes}:
                extra_frames.add(parent.name)
            parent = parent.parent
    for frame_name in extra_frames:
        if frame_name in nodes:
            selected_nodes.append(nodes[frame_name])

    selected_names = {n.name for n in selected_nodes}

    for node in selected_nodes:
        data["nodes"][node.name] = serialize_node(node)

    for link in node_tree.links:
        # Compare by name - id() is unreliable for bpy_struct wrappers
        # since Blender may create new Python objects on each access.
        if (
            link.from_node.name in selected_names
            and link.to_node.name in selected_names
        ):
            data["links"].append(
                {
                    "from_node": link.from_node.name,
                    "to_node": link.to_node.name,
                    "from_socket": link.from_socket.name,
                    "from_socket_type": link.from_socket.bl_idname,
                    "from_socket_identifier": link.from_socket.identifier,
                    "to_socket": link.to_socket.name,
                    "to_socket_type": link.to_socket.bl_idname,
                    "to_socket_identifier": link.to_socket.identifier,
                }
            )

    # Node Runner exports selected nodes. For Group Input/Output nodes,
    # Blender exposes the entire group interface on every instance. If we
    # serialize the entire interface for a small selected-node export, importing
    # it recreates many unrelated/empty sockets. Keep only interface sockets
    # actually used by the exported links.
    if selected_node_names is not None:
        data["interface_socket_policy"] = "linked_only"
        # Keep each Group Input node as a real layout node. Blender's group
        # interface is global, but individual Group Input socket visibility is
        # per-node, so the importer can recreate the original compact scattered
        # Group Input layout by hiding outputs that do not belong to each node.
        _prune_group_interface_orders_to_exported_links(data)
        data["group_input_policy"] = "per_node_hidden_outputs"

    log.debug("Serialized %d links", len(data["links"]))
    return data

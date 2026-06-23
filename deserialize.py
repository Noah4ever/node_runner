"""
Deserialization module for Node Runner.

Recreates Blender node trees from plain Python dicts produced by
the serialization module.
"""

import logging

import bpy

from .constants import (
    READONLY_DESERIALIZE_PROPS,
    SOCKET_BASE_TYPES,
    MODE_CHANGING_PROPS,
    PAIRED_NODE_TYPES,
)

log = logging.getLogger(__name__)

def _node_absolute_location(node):
    """Return node location in absolute canvas coordinates.

    Blender 4.5 has ``Node.location_absolute``. Blender 4.2 may not expose
    it on every node, so reconstruct it from ``location`` and parent frames.
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

# Helpers


def _rna_type_exists(type_name: str) -> bool:
    """Return True when *type_name* exists in this Blender build."""
    return bool(type_name and getattr(bpy.types, type_name, None) is not None)


def get_node_socket_base_type(socket_type: str) -> str:
    """Map a specific socket type string to a base type supported here.

    Blender 4.5 can export sockets/nodes that older Blender 4.x builds do
    not know. Blender 4.2 should not crash just because a newer socket type
    appears in a payload, so unsupported types gracefully fall back to the
    closest broad socket family and finally to ``NodeSocketFloat``.
    """
    socket_type = socket_type or ""

    for base in SOCKET_BASE_TYPES:
        if base in socket_type and _rna_type_exists(base):
            return base

    family_fallbacks = (
        ("Bool", "NodeSocketBool"),
        ("Boolean", "NodeSocketBool"),
        ("Vector", "NodeSocketVector"),
        ("Rotation", "NodeSocketRotation"),
        ("Matrix", "NodeSocketVector"),
        ("Int", "NodeSocketInt"),
        ("Integer", "NodeSocketInt"),
        ("Color", "NodeSocketColor"),
        ("Shader", "NodeSocketShader"),
        ("String", "NodeSocketString"),
        ("Image", "NodeSocketImage"),
        ("Object", "NodeSocketObject"),
        ("Collection", "NodeSocketCollection"),
        ("Geometry", "NodeSocketGeometry"),
        ("Menu", "NodeSocketMenu"),
        ("Material", "NodeSocketMaterial"),
        ("Texture", "NodeSocketTexture"),
    )
    for token, fallback in family_fallbacks:
        if token in socket_type and _rna_type_exists(fallback):
            return fallback

    return "NodeSocketFloat"



def _interface_socket_map_key(in_out, identifier):
    return f"interface:{in_out}:{identifier}"


def get_socket_by_identifier(
    node, identifier, socket_id_map, direction="INPUT", name=None
):
    """Find a socket on *node* by its original identifier.

    Handles remapping for group nodes whose identifiers change when
    sockets are created during deserialization.  Falls back to matching
    by *name* when the identifier lookup fails.

    Args:
        node: The Blender node.
        identifier: Original socket identifier from serialized data.
        socket_id_map: dict mapping old identifiers -> new identifiers.
        direction: ``'INPUT'`` or ``'OUTPUT'``.
        name: Optional socket name for fallback matching.

    Returns:
        The matching ``NodeSocket`` or ``None``.
    """
    sockets = node.inputs if direction == "INPUT" else node.outputs
    resolved_id = identifier

    if node.bl_idname == "NodeGroupInput":
        resolved_id = socket_id_map.get(
            _interface_socket_map_key("INPUT", identifier),
            socket_id_map.get(identifier, identifier),
        )
    elif node.bl_idname == "NodeGroupOutput":
        resolved_id = socket_id_map.get(
            _interface_socket_map_key("OUTPUT", identifier),
            socket_id_map.get(identifier, identifier),
        )
    elif node.bl_idname == "ShaderNodeGroup" and hasattr(node, "node_tree"):
        child_key = "child_" + node.node_tree.name
        if child_key in socket_id_map:
            resolved_id = socket_id_map[child_key].get(identifier, identifier)

    # Primary: match by identifier
    for sock in sockets:
        if sock.identifier == resolved_id:
            return sock

    # Fallback: match by name
    if name:
        for sock in sockets:
            if sock.name == name:
                return sock

    log.warning(
        "Socket '%s' (name='%s') not found on '%s' (%s)",
        identifier,
        name,
        node.name,
        direction,
    )
    return None


def create_interface_socket(node_tree, name, description, in_out, socket_type):
    """Create a new socket on a node group's interface.

    Args:
        node_tree: The NodeTree to add the socket to.
        name: Socket name.
        description: Socket description.
        in_out: ``'INPUT'`` or ``'OUTPUT'``.
        socket_type: Base socket type string.

    Returns:
        The newly created ``NodeTreeInterfaceSocket``.
    """
    socket_type = get_node_socket_base_type(socket_type)
    try:
        return node_tree.interface.new_socket(
            name=name,
            description=description,
            in_out=in_out,
            socket_type=socket_type,
        )
    except (TypeError, RuntimeError, ValueError) as exc:
        # Last-resort fallback for interface socket types unsupported by
        # Blender 4.2. This keeps the import usable instead of aborting the
        # whole node tree. The link/default may not be exact for the skipped
        # type, but the surrounding graph survives.
        log.warning(
            "Could not create interface socket '%s' as %s: %s; using Float",
            name,
            socket_type,
            exc,
        )
        return node_tree.interface.new_socket(
            name=name,
            description=description,
            in_out=in_out,
            socket_type="NodeSocketFloat",
        )


def _apply_group_interface_socket_policy(data):
    """Reduce Group Input/Output interface data for selected-node imports.

    Node Runner exports selected nodes, not a guaranteed complete node-tree
    snapshot. In Blender, every Group Input node serializes the whole group
    interface, even if the selected node island only uses a few of those
    sockets. Older payloads therefore recreated many unrelated empty inputs
    on import. Unless a payload explicitly asks for a full interface, keep
    only sockets referenced by exported links.
    """
    nodes = data.get("nodes", {})
    if not nodes:
        return

    policy = data.get("interface_socket_policy")
    # Future-proof escape hatch: a payload may explicitly request the whole
    # interface. Current Node Runner selected-node exports use linked_only.
    if policy == "full":
        return

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

    # For both new linked_only payloads and legacy 1.4.3 payloads without a
    # policy field, prune to the sockets that links actually need.
    for node_name, node_data in nodes.items():
        if node_data.get("type") == "NodeGroupInput" and "output_order" in node_data:
            used = used_group_input_outputs.get(node_name, set())
            node_data["output_order"] = [
                item
                for item in node_data.get("output_order", [])
                if item.get("identifier") in used
            ]
        elif node_data.get("type") == "NodeGroupOutput" and "input_order" in node_data:
            used = used_group_output_inputs.get(node_name, set())
            node_data["input_order"] = [
                item
                for item in node_data.get("input_order", [])
                if item.get("identifier") in used
            ]


def _socket_sort_key_from_original_order(nodes, socket_entries):
    """Return a stable key function using the first full-ish Group Input order found."""
    order = {}
    idx = 0
    for node_data in nodes.values():
        if node_data.get("type") != "NodeGroupInput":
            continue
        for item in node_data.get("output_order", []):
            ident = item.get("identifier")
            if ident and ident not in order:
                order[ident] = idx
                idx += 1
    return lambda item: order.get(item.get("identifier"), 10_000)


def _compact_group_input_nodes(data):
    """Collapse multiple Group Input nodes into one compact node for snippets.

    Blender does not support a different visible interface per Group Input node:
    every Group Input instance displays the same node-tree interface. If a
    selected-node snippet contains several Group Input nodes, creating the union
    of needed interface sockets makes each instance look like it has many
    unrelated sockets. For linked-only snippets, keep one Group Input node and
    redirect all outgoing Group Input links to it.
    """
    if data.get("interface_socket_policy") == "full":
        return

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
        # Nothing in the pasted snippet actually uses these nodes. Remove them.
        for name in group_input_names:
            nodes.pop(name, None)
        return

    def used_count(name):
        return sum(1 for link in links if link.get("from_node") == name)

    # Prefer the linked Group Input that contributes the most sockets.
    # Tie-break by the leftmost position so the resulting node usually stays
    # close to the source side of the node island.
    def loc_x(name):
        loc = nodes.get(name, {}).get("location_absolute") or nodes.get(name, {}).get("location") or [0, 0]
        try:
            return float(loc[0])
        except (TypeError, ValueError, IndexError):
            return 0.0

    primary = sorted(linked_from, key=lambda n: (-used_count(n), loc_x(n), n))[0]
    primary_data = nodes[primary]

    # Build the union of only sockets that are required by actual links.
    used_identifiers = {
        link.get("from_socket_identifier")
        for link in links
        if nodes.get(link.get("from_node"), {}).get("type") == "NodeGroupInput"
        and link.get("from_socket_identifier")
    }
    by_identifier = {}
    for name in group_input_names:
        for item in nodes.get(name, {}).get("output_order", []):
            ident = item.get("identifier")
            if ident in used_identifiers and ident not in by_identifier:
                by_identifier[ident] = item

    # Some very old payloads may not have output_order after pruning. Rebuild
    # minimal entries from the link metadata so links can still resolve.
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

    sort_key = _socket_sort_key_from_original_order(nodes, by_identifier.values())
    primary_data["output_order"] = sorted(by_identifier.values(), key=sort_key)

    # Redirect all Group Input links to the single remaining node. The socket
    # identifier stays the same, so get_socket_by_identifier can still resolve it
    # through socket_id_map after the interface sockets are created.
    for link in links:
        if nodes.get(link.get("from_node"), {}).get("type") == "NodeGroupInput":
            link["from_node"] = primary

    for name in group_input_names:
        if name != primary:
            nodes.pop(name, None)

    data["group_input_policy"] = "single_compact"


def _set_interface_socket_default(iface_socket, entry):
    if "default" not in entry or not hasattr(iface_socket, "default_value"):
        return
    try:
        iface_socket.default_value = entry["default"]
    except (TypeError, AttributeError, ValueError):
        log.debug("Could not set default for interface socket '%s'", entry.get("name"))


def _hide_group_io_sockets_per_payload_node(node_map, nodes_data, socket_id_map):
    """Restore the original per-node compact Group Input/Output display.

    Blender stores the node-group interface globally, so every Group Input node
    receives every group input socket. But the visible/hidden state of each
    socket on each node instance is local to that node. Selected-node snippets
    use ``output_order`` / ``input_order`` as the list of sockets that should be
    visible on that particular Group Input/Output node. Hide the rest so the
    imported layout matches the source layout instead of producing one very long
    Group Input node.
    """

    def mapped_identifiers(entries, in_out):
        identifiers = set()
        for entry in entries or []:
            old_identifier = entry.get("identifier")
            if not old_identifier:
                continue
            map_key = _interface_socket_map_key(in_out, old_identifier)
            identifiers.add(socket_id_map.get(map_key, socket_id_map.get(old_identifier, old_identifier)))
        return identifiers

    for old_name, node in node_map.items():
        node_data = nodes_data.get(old_name, {})
        node_type = node_data.get("type")

        if node_type == "NodeGroupInput" and hasattr(node, "outputs"):
            if "output_order" not in node_data:
                continue
            visible = mapped_identifiers(node_data.get("output_order", []), "INPUT")
            for sock in node.outputs:
                if getattr(sock, "bl_idname", "") == "NodeSocketVirtual":
                    continue
                try:
                    sock.hide = sock.identifier not in visible
                except (TypeError, AttributeError, ValueError):
                    pass

        elif node_type == "NodeGroupOutput" and hasattr(node, "inputs"):
            if "input_order" not in node_data:
                continue
            visible = mapped_identifiers(node_data.get("input_order", []), "OUTPUT")
            for sock in node.inputs:
                if getattr(sock, "bl_idname", "") == "NodeSocketVirtual":
                    continue
                try:
                    sock.hide = sock.identifier not in visible
                except (TypeError, AttributeError, ValueError):
                    pass


# Type-specific deserializers


def deserialize_color_ramp(node, data):
    """Apply color ramp data to *node*."""
    ramp = node.color_ramp
    ramp.color_mode = data.get("color_mode", ramp.color_mode)
    ramp.hue_interpolation = data.get("hue_interpolation", ramp.hue_interpolation)
    ramp.interpolation = data.get("interpolation", ramp.interpolation)

    elements_data = data.get("elements", [])
    if not elements_data:
        return

    # Ensure correct number of elements
    while len(ramp.elements) < len(elements_data):
        ramp.elements.new(0.5)
    while len(ramp.elements) > len(elements_data) and len(ramp.elements) > 1:
        ramp.elements.remove(ramp.elements[-1])

    # Apply positions and colors (sorted order to avoid re-indexing)
    for i, el_data in enumerate(elements_data):
        if i < len(ramp.elements):
            ramp.elements[i].position = el_data["position"]
            ramp.elements[i].color = el_data["color"]


def deserialize_color_mapping(node, data):
    """Apply color mapping data to *node*."""
    cm = node.color_mapping
    cm.blend_color = data.get("blend_color", (0.0, 0.0, 0.0))
    cm.blend_factor = data.get("blend_factor", 0.0)
    cm.blend_type = data.get("blend_type", cm.blend_type)
    cm.brightness = data.get("brightness", 0.0)
    if "color_ramp" in data:
        deserialize_color_ramp(cm, data["color_ramp"])
    cm.contrast = data.get("contrast", 0.0)
    cm.saturation = data.get("saturation", 0.0)
    cm.use_color_ramp = data.get("use_color_ramp", False)


def deserialize_texture_mapping(node, data):
    """Apply texture mapping data to *node*."""
    tm = node.texture_mapping
    tm.mapping = data.get("mapping", tm.mapping)
    tm.mapping_x = data.get("mapping_x", tm.mapping_x)
    tm.mapping_y = data.get("mapping_y", tm.mapping_y)
    tm.mapping_z = data.get("mapping_z", tm.mapping_z)
    tm.max = data.get("max", (0.0, 0.0, 0.0))
    tm.min = data.get("min", (0.0, 0.0, 0.0))
    tm.rotation = data.get("rotation", (0.0, 0.0, 0.0))
    tm.scale = data.get("scale", (1.0, 1.0, 1.0))
    tm.translation = data.get("translation", (0.0, 0.0, 0.0))
    tm.use_max = data.get("use_max", False)
    tm.use_min = data.get("use_min", False)
    tm.vector_type = data.get("vector_type", tm.vector_type)


def deserialize_curve_mapping(node, data):
    """Apply curve mapping data to *node*."""
    mapping = node.mapping
    mapping.black_level = data.get("black_level", (0.0, 0.0, 0.0))

    curves_data = data.get("curves", [])
    for i, curve_data in enumerate(curves_data):
        if i >= len(mapping.curves):
            break
        points_data = curve_data.get("points", [])
        if not points_data:
            continue

        existing_points = mapping.curves[i].points

        # Set the first and last default points
        if len(existing_points) >= 1 and len(points_data) >= 1:
            existing_points[0].location = points_data[0].get("location", (0.0, 0.0))
        if len(existing_points) >= 2 and len(points_data) >= 2:
            existing_points[-1].location = points_data[-1].get("location", (1.0, 1.0))

        # Create intermediate points
        for k in range(1, len(points_data) - 1):
            loc = points_data[k].get("location", (0.5, 0.5))
            mapping.curves[i].points.new(loc[0], loc[1])

    mapping.clip_max_x = data.get("clip_max_x", 1.0)
    mapping.clip_max_y = data.get("clip_max_y", 1.0)
    mapping.clip_min_x = data.get("clip_min_x", 0.0)
    mapping.clip_min_y = data.get("clip_min_y", 0.0)
    mapping.extend = data.get("extend", mapping.extend)
    mapping.tone = data.get("tone", mapping.tone)
    mapping.use_clip = data.get("use_clip", False)
    mapping.white_level = data.get("white_level", (1.0, 1.0, 1.0))


def deserialize_image(node, data):
    """Set image on *node* from serialized data.

    Looks up by name first.  If the image is not already loaded and a
    ``filepath`` was stored, attempts to load it from disk.
    """
    img_name = data.get("name")
    if not img_name:
        return

    image = bpy.data.images.get(img_name)
    if image:
        node.image = image
        return

    filepath = data.get("filepath", "")
    if filepath:
        try:
            image = bpy.data.images.load(filepath)
            node.image = image
            log.info("Loaded image '%s' from '%s'.", img_name, filepath)
            return
        except (RuntimeError, OSError):
            log.warning(
                "Image '%s' not found in blend file and could not be "
                "loaded from '%s'.",
                img_name,
                filepath,
            )
            return

    log.info("Image '%s' not found in blend file.", img_name)


def resolve_id_reference(payload):
    """Resolve a serialized Blender ID pointer by type and name."""
    if not isinstance(payload, dict) or "__id__" not in payload:
        return payload
    data_map = {
        "Scene": bpy.data.scenes,
        "MovieClip": bpy.data.movieclips,
        "Mask": bpy.data.masks,
        "Object": bpy.data.objects,
        "Collection": bpy.data.collections,
        "Material": bpy.data.materials,
        "Image": bpy.data.images,
        "Texture": bpy.data.textures,
        "World": bpy.data.worlds,
    }
    data_block = data_map.get(payload.get("__id__"))
    if data_block is None:
        return None
    return data_block.get(payload.get("name", ""))


def deserialize_output_file_slots(node, data):
    """Restore compositor File Output node slot layout defensively."""
    if not isinstance(data, dict):
        return
    for collection_name in ("file_slots", "layer_slots"):
        slots_data = data.get(collection_name)
        slots = getattr(node, collection_name, None)
        if slots is None or not isinstance(slots_data, list):
            continue

        # Match slot count. Blender's File Output node usually starts with one
        # default slot; add/remove only when the API allows it.
        try:
            while len(slots) < len(slots_data):
                label = slots_data[len(slots)].get("name") or slots_data[len(slots)].get("path") or "Image"
                slots.new(label)
        except (TypeError, AttributeError, RuntimeError):
            pass
        try:
            while len(slots) > len(slots_data) and len(slots) > 0:
                slots.remove(slots[-1])
        except (TypeError, AttributeError, RuntimeError):
            pass

        try:
            pairs = zip(list(slots), slots_data)
        except (TypeError, RuntimeError):
            continue
        for slot, entry in pairs:
            if not isinstance(entry, dict):
                continue
            for attr_name in ("path", "use_node_format", "save_as_render", "name"):
                if attr_name not in entry:
                    continue
                try:
                    setattr(slot, attr_name, entry[attr_name])
                except (TypeError, AttributeError, RuntimeError):
                    pass


def deserialize_text_line(text_line, data):
    """Apply text line data."""
    text_line.body = data.get("body", "")


def deserialize_text(data):
    """Recreate or find a Text data-block from serialized data."""
    filepath = data.get("filepath", "")

    # Try to find existing text by filepath
    if filepath:
        for txt in bpy.data.texts:
            if txt.filepath == filepath:
                return txt

    text = bpy.data.texts.new(name="Text")
    # Write lines
    lines_data = data.get("lines", [])
    if lines_data:
        body = "\n".join(ld.get("body", "") for ld in lines_data)
        text.write(body)
    text.filepath = filepath

    return text


# Input / Output deserializers


def deserialize_inputs(node, data, node_data, node_tree, socket_id_map):
    """Deserialize input sockets for *node*.

    For ``NodeGroupInput`` nodes, creates interface sockets on the
    parent group instead.
    """
    if isinstance(node, (bpy.types.NodeGroupInput, bpy.types.NodeGroupOutput)):
        if isinstance(node, bpy.types.NodeGroupInput):
            for inp in node_data.get("output_order", []):
                old_identifier = inp.get("identifier")
                map_key = _interface_socket_map_key("INPUT", old_identifier)
                if old_identifier and map_key in socket_id_map:
                    continue
                iface_socket = create_interface_socket(
                    node_tree,
                    inp.get("name", ""),
                    inp.get("name", "") + " Input",
                    "INPUT",
                    get_node_socket_base_type(inp.get("type", "NodeSocketFloat")),
                )
                if old_identifier:
                    socket_id_map[map_key] = iface_socket.identifier
                    socket_id_map.setdefault(old_identifier, iface_socket.identifier)
                _set_interface_socket_default(iface_socket, inp)
        return

    if not hasattr(node, "inputs"):
        return

    for i, value in enumerate(data):
        if (
            value is not None
            and i < len(node.inputs)
            and hasattr(node.inputs[i], "default_value")
        ):
            try:
                node.inputs[i].default_value = value
            except (TypeError, AttributeError, ValueError):
                log.debug("Could not set input %d on '%s'", i, node.name)


def deserialize_outputs(node, data, node_data, node_tree, socket_id_map):
    """Deserialize output sockets for *node*.

    For ``NodeGroupOutput`` nodes, creates interface sockets on the
    parent group instead.
    """
    if isinstance(node, (bpy.types.NodeGroupInput, bpy.types.NodeGroupOutput)):
        if isinstance(node, bpy.types.NodeGroupOutput):
            for out in node_data.get("input_order", []):
                old_identifier = out.get("identifier")
                map_key = _interface_socket_map_key("OUTPUT", old_identifier)
                if old_identifier and map_key in socket_id_map:
                    continue
                iface_socket = create_interface_socket(
                    node_tree,
                    out.get("name", ""),
                    out.get("name", "") + " Output",
                    "OUTPUT",
                    get_node_socket_base_type(out.get("type", "NodeSocketFloat")),
                )
                if old_identifier:
                    socket_id_map[map_key] = iface_socket.identifier
                    socket_id_map.setdefault(old_identifier, iface_socket.identifier)
                _set_interface_socket_default(iface_socket, out)
        return

    if not hasattr(node, "outputs"):
        return

    for i, value in enumerate(data):
        if (
            value is not None
            and i < len(node.outputs)
            and hasattr(node.outputs[i], "default_value")
        ):
            try:
                node.outputs[i].default_value = value
            except (TypeError, AttributeError, ValueError):
                log.debug("Could not set output %d on '%s'", i, node.name)


# Node deserializer


def deserialize_node(node_data, node_tree, socket_id_map, defer_io=False):
    """Create a new node and apply all serialized properties.

    Args:
        node_data: dict of serialized properties for one node.
        node_tree: The Blender NodeTree to add the node to.
        socket_id_map: Mutable dict tracking socket identifier remappings.
        defer_io: If True, skip socket default assignment and return
            the deferred data as a second element.

    Returns:
        The newly created ``Node`` (or ``None``), or a tuple
        ``(Node, deferred_io_dict)`` when *defer_io* is True.
    """
    node_type = node_data.get("type", "")
    if node_type == "NodeUndefined":
        return (None, {}) if defer_io else None

    try:
        new_node = node_tree.nodes.new(type=node_type)
    except (RuntimeError, TypeError, ValueError) as exc:
        log.warning(
            "Skipping unsupported node type '%s' in this Blender version: %s",
            node_type,
            exc,
        )
        return (None, {}) if defer_io else None
    new_node.label = node_data.get("label", "")

    # Node tree must be created before inputs/outputs
    if "node_tree" in node_data:
        nt_data = node_data["node_tree"]
        tree_type = nt_data.get("tree_type", "ShaderNodeTree")
        try:
            new_node.node_tree = bpy.data.node_groups.new(nt_data["name"], tree_type)
        except (RuntimeError, TypeError, ValueError) as exc:
            log.warning(
                "Could not create child node group '%s' of type %s: %s",
                nt_data.get("name", "<unnamed>"),
                tree_type,
                exc,
            )
        else:
            child_key = "child_" + new_node.node_tree.name
            socket_id_map[child_key] = {}
            deserialize_node_tree(new_node.node_tree, nt_data, socket_id_map[child_key])
        # Don't process node_tree again below
        node_data = {k: v for k, v in node_data.items() if k != "node_tree"}

    # Property dispatch
    _prop_handlers = {
        "color_ramp": deserialize_color_ramp,
        "color_mapping": deserialize_color_mapping,
        "texture_mapping": deserialize_texture_mapping,
        "mapping": deserialize_curve_mapping,
        "image": deserialize_image,
        "file_output_slots": deserialize_output_file_slots,
        "inputs": lambda n, v: deserialize_inputs(
            n, v, node_data, node_tree, socket_id_map
        ),
        "outputs": lambda n, v: deserialize_outputs(
            n, v, node_data, node_tree, socket_id_map
        ),
        "script": lambda n, v: setattr(n, "script", deserialize_text(v)),
    }

    # Set mode-changing properties first:
    # These affect what sockets the node exposes and must precede
    # any socket default value assignment.
    for prop_name in MODE_CHANGING_PROPS:
        if prop_name not in node_data or prop_name in READONLY_DESERIALIZE_PROPS:
            continue
        try:
            setattr(new_node, prop_name, node_data[prop_name])
        except (TypeError, AttributeError, KeyError) as exc:
            log.debug(
                "Cannot set mode prop '%s' on '%s': %s", prop_name, new_node.name, exc
            )

    # Set remaining (non-socket) properties:
    _deferred_io = {}

    for prop_name, prop_value in node_data.items():
        if prop_name in READONLY_DESERIALIZE_PROPS:
            continue
        if prop_name in MODE_CHANGING_PROPS:
            continue  # Already handled in phase 1

        # Defer socket default value assignment
        if prop_name in ("inputs", "outputs"):
            _deferred_io[prop_name] = prop_value
            continue

        if prop_name in _prop_handlers:
            _prop_handlers[prop_name](new_node, prop_value)
        elif prop_name in ("parent", "_paired_output"):
            # Handled at the node-tree level
            pass
        elif prop_name in ("label", "type", "name"):
            continue
        else:
            if isinstance(prop_value, dict) and "__id__" in prop_value:
                prop_value = resolve_id_reference(prop_value)
                if prop_value is None:
                    continue
            try:
                setattr(new_node, prop_name, prop_value)
            except (TypeError, AttributeError, KeyError) as exc:
                log.debug(
                    "Cannot set '%s' on '%s': %s",
                    prop_name,
                    new_node.name,
                    exc,
                )

    # Apply deferred socket defaults:
    if not defer_io:
        for prop_name, prop_value in _deferred_io.items():
            _prop_handlers[prop_name](new_node, prop_value)

    if defer_io:
        return new_node, _deferred_io
    return new_node


# Link deserializer


def deserialize_link(node_map, link_data, socket_id_map):
    """Resolve link endpoints from serialized data.

    Args:
        node_map: dict mapping original node names to deserialized Node objects.
        link_data: dict with from_node, to_node, socket identifiers, etc.
        socket_id_map: Socket identifier remapping dict.

    Returns:
        Tuple ``(output_socket, input_socket)`` or ``(None, None)`` on error.
    """
    from_node = node_map.get(link_data["from_node"])
    to_node = node_map.get(link_data["to_node"])

    if from_node is None or to_node is None:
        log.warning(
            "Link references missing node(s): %s -> %s",
            link_data["from_node"],
            link_data["to_node"],
        )
        return None, None

    if "from_socket_index" in link_data:
        idx = link_data["from_socket_index"]
        if idx < len(from_node.outputs):
            out_sock = from_node.outputs[idx]
        else:
            out_sock = get_socket_by_identifier(
                from_node,
                link_data.get("from_socket_identifier", ""),
                socket_id_map,
                "OUTPUT",
                name=link_data.get("from_socket"),
            )
    else:
        out_sock = get_socket_by_identifier(
            from_node,
            link_data.get("from_socket_identifier", ""),
            socket_id_map,
            "OUTPUT",
            name=link_data.get("from_socket"),
        )

    if "to_socket_index" in link_data:
        idx = link_data["to_socket_index"]
        if idx < len(to_node.inputs):
            in_sock = to_node.inputs[idx]
        else:
            in_sock = get_socket_by_identifier(
                to_node,
                link_data.get("to_socket_identifier", ""),
                socket_id_map,
                "INPUT",
                name=link_data.get("to_socket"),
            )
    else:
        in_sock = get_socket_by_identifier(
            to_node,
            link_data.get("to_socket_identifier", ""),
            socket_id_map,
            "INPUT",
            name=link_data.get("to_socket"),
        )

    return out_sock, in_sock


# Frame handling: topological ordering for nested frames


def _topological_sort_frames(nodes_data):
    """Return frame node names in parent-first order.

    This ensures that when we create frames, the parent frame always
    exists before any child frame.
    """
    frame_names = [
        name for name, data in nodes_data.items() if data.get("type") == "NodeFrame"
    ]

    # Build parent -> children mapping
    parent_of = {}
    for name in frame_names:
        parent_of[name] = nodes_data[name].get("parent")

    # Simple topological sort (frames are shallow, no cycles)
    ordered = []
    visited = set()

    def visit(name):
        if name in visited:
            return
        parent = parent_of.get(name)
        if parent and parent in parent_of:
            visit(parent)
        visited.add(name)
        ordered.append(name)

    for name in frame_names:
        visit(name)

    return ordered


# Node tree deserializer


def deserialize_node_tree(node_tree, data, socket_id_map):
    """Recreate a full node tree from serialized data.

    Handles:
    - Topologically sorted frame creation (parent-first)
    - Correct absolute -> relative location conversion for nested frames
    - All node types, links, and group sockets.

    Args:
        node_tree: The target Blender NodeTree.
        data: Serialized node tree dict.
        socket_id_map: Mutable dict for socket identifier remapping.
    """
    _apply_group_interface_socket_policy(data)

    nodes_data = data.get("nodes", {})
    links_data = data.get("links", [])
    node_map = {}  # old_name -> new Node

    # Create frames in topological (parent-first) order:
    frame_order = _topological_sort_frames(nodes_data)
    frame_name_remap = {}  # old_name -> new_name

    for frame_name in frame_order:
        frame_data = nodes_data[frame_name]
        new_frame = deserialize_node(frame_data, node_tree, socket_id_map)
        if new_frame is None:
            continue

        # Attempt to keep the original name
        new_frame.name = frame_data.get("name", frame_name)
        frame_name_remap[frame_name] = new_frame.name
        node_map[frame_name] = new_frame

    # Assign parent relationships for nested frames
    for frame_name in frame_order:
        frame_data = nodes_data[frame_name]
        parent_name = frame_data.get("parent")
        if parent_name and parent_name in frame_name_remap:
            new_name = frame_name_remap[frame_name]
            parent_new_name = frame_name_remap[parent_name]
            if new_name in node_tree.nodes and parent_new_name in node_tree.nodes:
                node_tree.nodes[new_name].parent = node_tree.nodes[parent_new_name]

    # Set frame locations (use absolute location, then convert to relative)
    for frame_name in frame_order:
        frame_data = nodes_data[frame_name]
        frame_node = node_map.get(frame_name)
        if frame_node is None:
            continue
        abs_loc = frame_data.get("location_absolute")
        if abs_loc:
            _set_location_from_absolute(frame_node, abs_loc)
        else:
            # Fallback for data without location_absolute (old format)
            loc = frame_data.get("location")
            if loc:
                frame_node.location = loc

    # Create all non-frame nodes:
    non_frame_names = [name for name in nodes_data if name not in frame_name_remap]

    # Update parent references to new frame names
    for name in non_frame_names:
        nd = nodes_data[name]
        if "parent" in nd and nd["parent"] in frame_name_remap:
            nd["parent"] = frame_name_remap[nd["parent"]]

    # Track deferred I/O for paired zone nodes
    _deferred_io_map = {}  # node_name -> deferred_io dict

    for node_name in non_frame_names:
        nd = nodes_data[node_name]
        is_paired = nd.get("type") in PAIRED_NODE_TYPES

        if is_paired:
            result = deserialize_node(nd, node_tree, socket_id_map, defer_io=True)
            new_node, deferred_io = result
            if new_node is not None:
                _deferred_io_map[node_name] = deferred_io
        else:
            new_node = deserialize_node(nd, node_tree, socket_id_map)

        if new_node is None:
            continue
        node_map[node_name] = new_node

        # Assign parent frame
        parent_name = nd.get("parent")
        if parent_name and parent_name in node_tree.nodes:
            new_node.parent = node_tree.nodes[parent_name]

        # Set location from absolute coordinates
        abs_loc = nd.get("location_absolute")
        if abs_loc:
            _set_location_from_absolute(new_node, abs_loc)
        else:
            # Fallback for old format: location is relative
            loc = nd.get("location")
            if loc is not None:
                if new_node.parent:
                    pass
                else:
                    new_node.location = loc

    # Pair zone nodes (repeat, simulation, etc.):
    for node_name in non_frame_names:
        nd = nodes_data[node_name]
        paired_name = nd.get("_paired_output")
        if paired_name and node_name in node_map and paired_name in node_map:
            input_node = node_map[node_name]
            output_node = node_map[paired_name]
            if hasattr(input_node, "pair_with_output"):
                try:
                    input_node.pair_with_output(output_node)
                except (RuntimeError, AttributeError) as exc:
                    log.warning(
                        "Failed to pair '%s' with '%s': %s",
                        node_name,
                        paired_name,
                        exc,
                    )

    # Apply deferred I/O for paired nodes:
    for node_name, deferred_io in _deferred_io_map.items():
        node = node_map.get(node_name)
        if node is None:
            continue
        nd = nodes_data[node_name]
        for prop_name, prop_value in deferred_io.items():
            if prop_name == "inputs":
                deserialize_inputs(node, prop_value, nd, node_tree, socket_id_map)
            elif prop_name == "outputs":
                deserialize_outputs(node, prop_value, nd, node_tree, socket_id_map)

    # Restore per-node visible socket layout for Group Input/Output nodes.
    # This must run after all interface sockets exist, and before links are
    # created so hidden sockets are still resolvable by identifier.
    _hide_group_io_sockets_per_payload_node(node_map, nodes_data, socket_id_map)

    # Create links:
    links_created = 0
    for link_data in links_data:
        out_sock, in_sock = deserialize_link(node_map, link_data, socket_id_map)
        if in_sock and out_sock:
            try:
                # Blender API: links.new(input_socket, output_socket)
                node_tree.links.new(in_sock, out_sock)
                links_created += 1
            except (RuntimeError, TypeError, ValueError) as exc:
                log.warning(
                    "Failed to create link %s.%s -> %s.%s: %s",
                    link_data.get("from_node"),
                    link_data.get("from_socket"),
                    link_data.get("to_node"),
                    link_data.get("to_socket"),
                    exc,
                )
        else:
            log.warning(
                "Could not resolve link endpoints: %s.%s -> %s.%s"
                " (out_sock=%s, in_sock=%s)",
                link_data.get("from_node"),
                link_data.get("from_socket"),
                link_data.get("to_node"),
                link_data.get("to_socket"),
                out_sock,
                in_sock,
            )
    log.debug("Created %d/%d links", links_created, len(links_data))


def _set_location_from_absolute(node, abs_loc):
    """Set a node's location from absolute canvas coordinates.

    In Blender, ``node.location`` is relative to ``node.parent``.
    So we need to subtract the parent's absolute location to get
    the correct relative location.
    """
    if node.parent:
        parent_abs = _node_absolute_location(node.parent)
        node.location = (
            float(abs_loc[0]) - float(parent_abs[0]),
            float(abs_loc[1]) - float(parent_abs[1]),
        )
    else:
        node.location = abs_loc

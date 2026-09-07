"""
Encoding and decoding utilities for Node Runner.

Handles compression (zlib) and encoding (base64) of serialized node data.
Supports multiple output formats: base64 (default), JSON, and XML.

The base64 (hash) format uses a compact internal representation that
reduces string length by:
- Storing nodes as arrays instead of keyed dicts
- Representing links as index pairs instead of repeated name strings
- Quantising positions to integers
- Stripping None values from socket default lists
"""

import base64
import binascii
import json
import logging
import pickle
import xml.etree.ElementTree as ET
import zlib

from .node_data import NODE_DEFAULTS, INPUT_NAMES, OUTPUT_NAMES

log = logging.getLogger(__name__)

# Format identifiers
FORMAT_HASH = "HASH"
FORMAT_JSON = "JSON"
FORMAT_AI_JSON = "AI_JSON"
FORMAT_XML = "XML"

FORMATS = (FORMAT_HASH, FORMAT_JSON, FORMAT_AI_JSON, FORMAT_XML)

# Upper bound on inflated hash payloads, guarding against zip bombs.
MAX_DECOMPRESSED_BYTES = 256 * 1024 * 1024


# Compact representation (used by base64 / hash format)

# Node fields that are stored in fixed positions in the compact array
_COMPACT_SKIP = frozenset(
    {
        "type",
        "label",
        "name",
        "location",
        "location_absolute",
        "inputs",
        "outputs",
        "parent",
        "width",
        "height",
    }
)

# Node properties whose Blender defaults are stripped during compaction.
# Values here are the Blender defaults - if a property equals its default,
# it is omitted from the compact representation to save space.
_DEFAULT_NODE_PROPS = {
    "use_custom_color": False,
    "color": [0.6079999804496765, 0.6079999804496765, 0.6079999804496765],
    "show_options": True,
    "show_preview": False,
    "mute": False,
    "show_texture": False,
}

# Default texture_mapping - all fields at Blender defaults.
_DEFAULT_TEXTURE_MAPPING = {
    "mapping": "FLAT",
    "mapping_x": "X",
    "mapping_y": "Y",
    "mapping_z": "Z",
    "max": [1.0, 1.0, 1.0],
    "min": [0.0, 0.0, 0.0],
    "rotation": [0.0, 0.0, 0.0],
    "scale": [1.0, 1.0, 1.0],
    "translation": [0.0, 0.0, 0.0],
    "use_max": False,
    "use_min": False,
    "vector_type": "POINT",
}

# Default color_mapping - all fields at Blender defaults.
_DEFAULT_COLOR_MAPPING = {
    "blend_color": [0.800000011920929, 0.800000011920929, 0.800000011920929],
    "blend_factor": 0.0,
    "blend_type": "MIX",
    "brightness": 1.0,
    "color_ramp": {
        "color_mode": "RGB",
        "hue_interpolation": "NEAR",
        "interpolation": "LINEAR",
        "elements": [
            {"position": 0.0, "color": [0.0, 0.0, 0.0, 1.0]},
            {"position": 1.0, "color": [1.0, 1.0, 1.0, 1.0]},
        ],
    },
    "contrast": 1.0,
    "saturation": 1.0,
    "use_color_ramp": False,
}

# Current compact format version
_COMPACT_VERSION = 4


def _values_equal(a, b):
    """Compare two serialized values, handling float tolerance for lists."""
    if type(a) is not type(b):
        return False
    if isinstance(a, list):
        if len(a) != len(b):
            return False
        return all(_values_equal(x, y) for x, y in zip(a, b))
    if isinstance(a, float):
        return abs(a - b) < 1e-6
    return a == b


def _compact_data(data):
    """Convert a standard node-tree dict to a compact representation.

    The compact format uses arrays instead of dicts for nodes and links,
    strips None socket values, and quantises positions to integers.
    Nested node trees (groups) are compacted recursively.
    """
    if "v" in data:
        return data  # Already compact

    nodes_data = data.get("nodes", {})
    links_data = data.get("links", [])

    node_names = list(nodes_data.keys())
    name_to_idx = {name: i for i, name in enumerate(node_names)}

    compact_nodes = []
    for name in node_names:
        nd = nodes_data[name]
        node_type = nd.get("type", "")
        node_def = NODE_DEFAULTS.get(node_type)
        def_props = node_def.get("props", {}) if node_def else {}
        def_inputs = node_def.get("inputs") if node_def else None

        loc = nd.get("location_absolute", nd.get("location", [0, 0]))
        loc = [round(loc[0]), round(loc[1])]

        parent = nd.get("parent")
        parent_idx = name_to_idx.get(parent, -1) if parent else -1

        # Collect all non-fixed-field properties, stripping defaults
        props = {}
        for k, v in nd.items():
            if k in _COMPACT_SKIP:
                continue
            if v is None:
                continue
            # Strip properties that equal their Blender defaults
            if k in _DEFAULT_NODE_PROPS and v == _DEFAULT_NODE_PROPS[k]:
                continue
            # Strip all-default texture_mapping / color_mapping
            if (
                k == "texture_mapping"
                and isinstance(v, dict)
                and v == _DEFAULT_TEXTURE_MAPPING
            ):
                continue
            if (
                k == "color_mapping"
                and isinstance(v, dict)
                and v == _DEFAULT_COLOR_MAPPING
            ):
                continue
            # Strip props that match node-type defaults
            if k in def_props and _values_equal(v, def_props[k]):
                continue
            # Recursively compact nested node trees (groups)
            if k == "node_tree" and isinstance(v, dict) and "nodes" in v:
                v = _compact_data(v)
            props[k] = v

        # Sparse inputs: store only [index, value] for non-default
        raw_inputs = nd.get("inputs", [])
        inputs_sparse = []
        for i, v in enumerate(raw_inputs):
            if v is None:
                continue
            if (
                def_inputs is not None
                and i < len(def_inputs)
                and _values_equal(v, def_inputs[i])
            ):
                continue
            inputs_sparse.append([i, v])

        # Sparse outputs - needed for nodes like ShaderNodeRGB / ShaderNodeValue
        raw_outputs = nd.get("outputs", [])
        outputs_sparse = []
        for i, v in enumerate(raw_outputs):
            if v is not None:
                outputs_sparse.append([i, v])

        # Node array: [type, name, label, [x,y], parent_idx, props, inputs]
        # Optional 8th element: sparse outputs (only when non-empty)
        node_arr = [
            nd.get("type", ""),
            name,
            nd.get("label", ""),
            loc,
            parent_idx,
            props,
            inputs_sparse,
        ]
        if outputs_sparse:
            node_arr.append(outputs_sparse)
        compact_nodes.append(node_arr)

    # Compact links: [from_node_idx, from_socket, to_node_idx, to_socket]
    # Socket is the identifier string, or [identifier, name] if they differ.
    compact_links = []
    for link in links_data:
        from_idx = name_to_idx.get(link["from_node"], -1)
        to_idx = name_to_idx.get(link["to_node"], -1)

        from_sock_id = link.get("from_socket_identifier", link.get("from_socket", ""))
        to_sock_id = link.get("to_socket_identifier", link.get("to_socket", ""))
        from_sock_name = link.get("from_socket", from_sock_id)
        to_sock_name = link.get("to_socket", to_sock_id)

        from_sock = (
            from_sock_id
            if from_sock_id == from_sock_name
            else [from_sock_id, from_sock_name]
        )
        to_sock = (
            to_sock_id if to_sock_id == to_sock_name else [to_sock_id, to_sock_name]
        )

        compact_links.append([from_idx, from_sock, to_idx, to_sock])

    result = {
        "v": _COMPACT_VERSION,
        "n": compact_nodes,
        "l": compact_links,
    }

    # Only store tree_type if present in source data
    if "tree_type" in data:
        result["t"] = data["tree_type"]

    # Preserve any metadata that lives at the top level
    if "name" in data:
        result["name"] = data["name"]
    for key in ("blender_version", "export_name"):
        if key in data:
            result[key] = data[key]

    return result


def _expand_data(data):
    """Convert a compact representation back to the standard dict format.

    Handles both compact (v>=2) and legacy data transparently.
    """
    if "nodes" in data:
        return data  # Already in standard format

    if data.get("v", 1) < 2:
        return data  # Unknown version, return as-is

    compact_nodes = data.get("n", [])
    compact_links = data.get("l", [])

    # Rebuild node names for link resolution
    node_names = [n[1] for n in compact_nodes]

    version = data.get("v", 2)

    # Expand nodes
    nodes = {}
    for node_arr in compact_nodes:
        # 8 elements when outputs present, 7 without
        if len(node_arr) >= 8:
            (
                node_type,
                name,
                label,
                loc,
                parent_idx,
                props,
                inputs_sparse,
                outputs_sparse,
            ) = node_arr
        else:
            node_type, name, label, loc, parent_idx, props, inputs_sparse = node_arr
            outputs_sparse = []

        nd = {}
        nd["type"] = node_type
        nd["name"] = name
        nd["label"] = label
        nd["location_absolute"] = [float(loc[0]), float(loc[1])]
        nd["location"] = [float(loc[0]), float(loc[1])]

        if 0 <= parent_idx < len(node_names):
            nd["parent"] = node_names[parent_idx]

        # Restore default props before overlaying stored ones
        node_def = NODE_DEFAULTS.get(node_type) if version >= 4 else None
        if node_def:
            for k, v in node_def.get("props", {}).items():
                nd[k] = v

        # Expand extra properties (overwrite defaults with stored values)
        for k, v in props.items():
            # Recursively expand nested node trees
            if k == "node_tree" and isinstance(v, dict) and "v" in v:
                v = _expand_data(v)
            nd[k] = v

        # Start with default inputs, then overlay sparse stored values
        if node_def and node_def.get("inputs"):
            def_inputs = node_def["inputs"]
            inputs = list(def_inputs)
            # Extend if sparse inputs reference beyond defaults
            if inputs_sparse:
                max_idx = max(i for i, _ in inputs_sparse)
                if max_idx >= len(inputs):
                    inputs.extend([None] * (max_idx + 1 - len(inputs)))
            for i, v in inputs_sparse:
                inputs[i] = v
            nd["inputs"] = inputs
        elif inputs_sparse:
            max_idx = max(i for i, _ in inputs_sparse)
            inputs = [None] * (max_idx + 1)
            for i, v in inputs_sparse:
                inputs[i] = v
            nd["inputs"] = inputs
        else:
            nd["inputs"] = []

        # Expand sparse outputs
        if outputs_sparse:
            max_idx = max(i for i, _ in outputs_sparse)
            outputs = [None] * (max_idx + 1)
            for i, v in outputs_sparse:
                outputs[i] = v
            nd["outputs"] = outputs
        else:
            nd["outputs"] = []

        nodes[name] = nd

    # Expand links
    links = []
    for link_arr in compact_links:
        from_idx, from_sock, to_idx, to_sock = link_arr

        if isinstance(from_sock, list):
            from_id, from_name = from_sock
        else:
            from_id = from_name = from_sock

        if isinstance(to_sock, list):
            to_id, to_name = to_sock
        else:
            to_id = to_name = to_sock

        links.append(
            {
                "from_node": (
                    node_names[from_idx] if 0 <= from_idx < len(node_names) else ""
                ),
                "to_node": node_names[to_idx] if 0 <= to_idx < len(node_names) else "",
                "from_socket": from_name,
                "from_socket_identifier": from_id,
                "to_socket": to_name,
                "to_socket_identifier": to_id,
            }
        )

    result = {
        "nodes": nodes,
        "links": links,
        "name": data.get("name", ""),
    }

    # Only include tree_type if it was in the compact data
    if "t" in data:
        result["tree_type"] = data["t"]

    # Preserve metadata
    for key in ("blender_version", "export_name"):
        if key in data:
            result[key] = data[key]

    return result


# Base64 / hash (default)


def encode(data: dict) -> str:
    """Compact, compress, and base64-encode node tree data."""
    compact = _compact_data(data)
    raw = json.dumps(compact, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    compressed = zlib.compress(raw, 9)
    return base64.b64encode(compressed).decode("utf-8")


def decode(base64_encoded: str, *, allow_pickle: bool = True) -> dict:
    """Decode and decompress a base64-encoded node tree string.

    Set *allow_pickle* to ``False`` for data from an untrusted source such
    as a library repository: the legacy pickle fallback below executes
    arbitrary code, which is acceptable for a string the user pasted
    themselves but never for one fetched over the network.
    """
    try:
        compressed = base64.b64decode(base64_encoded)
        # Bounded inflate - a tiny payload can otherwise expand to
        # gigabytes and exhaust memory.
        inflator = zlib.decompressobj()
        raw = inflator.decompress(compressed, MAX_DECOMPRESSED_BYTES)
        if inflator.unconsumed_tail:
            raise ValueError(
                "Node data expands beyond "
                f"{MAX_DECOMPRESSED_BYTES // (1024 * 1024)} MB - refusing to decode it"
            )
        if not inflator.eof:
            # decompressobj tolerates a truncated or empty stream where
            # zlib.decompress would have raised; treat it as bad data.
            raise ValueError("Failed to decode node data: incomplete stream")

        # New format: JSON
        try:
            data = json.loads(raw)
            return _expand_data(data)
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass

        # Legacy format: pickle (backward compat)
        if not allow_pickle:
            raise ValueError(
                "Refusing to decode legacy pickle data from an untrusted "
                "source. Re-export this setup with a current Node Runner."
            )
        log.info("Decoding legacy pickle format - re-export to upgrade.")
        return pickle.loads(raw)  # noqa: S301
    except (zlib.error, pickle.UnpicklingError, binascii.Error, EOFError) as exc:
        raise ValueError(f"Failed to decode node data: {exc}") from exc


# JSON


def encode_json(data: dict) -> str:
    """Serialize node tree data to a pretty-printed JSON string."""
    return json.dumps(data, indent=2, ensure_ascii=False)


def decode_json(json_string: str) -> dict:
    """Deserialize a JSON string to a node tree dictionary."""
    try:
        return json.loads(json_string)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to decode JSON node data: {exc}") from exc


# AI JSON (AI-readable)

# Properties to exclude from the AI-readable format (visual-only noise)
_AI_JSON_SKIP_PROPS = {
    "use_custom_color",
    "color",
    "show_options",
    "show_preview",
    "mute",
    "show_texture",
    "is_active_output",
    "target",
    "texture_mapping",
    "color_mapping",
}

# Node types whose output values are user-settable (not computed).
# Only these nodes get their outputs preserved in AI JSON.
_USER_OUTPUT_NODES = frozenset(
    {
        "ShaderNodeRGB",
        "ShaderNodeValue",
    }
)


def _input_name(node_type, index):
    """Return the human-readable socket name for *index*, or a fallback."""
    names = INPUT_NAMES.get(node_type)
    if names and index < len(names):
        return names[index]
    return f"Input {index}"


def _output_name(node_type, index):
    """Return the human-readable output socket name for *index*, or a fallback."""
    names = OUTPUT_NAMES.get(node_type)
    if names and index < len(names):
        return names[index]
    return f"Output {index}"


def _input_index(node_type, name):
    """Return the input index for the given socket *name*, or -1."""
    names = INPUT_NAMES.get(node_type)
    if not names:
        return -1
    # Handle duplicates (e.g. ShaderNodeMath has three "Value" inputs)
    # Returns the first match; caller uses _next variant for dupes
    try:
        return names.index(name)
    except ValueError:
        return -1


def _output_index(node_type, name):
    """Return the output index for the given socket *name*, or -1."""
    names = OUTPUT_NAMES.get(node_type)
    if not names:
        return -1
    try:
        return names.index(name)
    except ValueError:
        return -1


def _resolve_named_sockets(named, names_table):
    """Convert named socket dict to positional array using a name table."""
    if names_table:
        result = [None] * len(names_table)
        used = set()
        for sock_name, v in named.items():
            parts = sock_name.rsplit(" ", 1)
            if len(parts) == 2 and parts[1].isdigit():
                idx = int(parts[1])
                if idx < len(result):
                    result[idx] = v
                    used.add(idx)
                    continue
            for i, n in enumerate(names_table):
                if n == sock_name and i not in used:
                    result[i] = v
                    used.add(i)
                    break
        return result
    # No name table, treat keys as "Name N"
    max_idx = 0
    idx_vals = []
    for sock_name, v in named.items():
        parts = sock_name.rsplit(" ", 1)
        if len(parts) == 2 and parts[1].isdigit():
            idx = int(parts[1])
        else:
            idx = 0
        idx_vals.append((idx, v))
        max_idx = max(max_idx, idx)
    result = [None] * (max_idx + 1)
    for idx, v in idx_vals:
        result[idx] = v
    return result


def encode_ai_json(data: dict) -> str:
    """Serialize node tree data as AI-readable JSON.

    Produces a clean, human-and-AI-readable format with named inputs,
    named links, and only non-default values.
    """
    nodes_data = data.get("nodes", {})
    links_data = data.get("links", [])

    readable_nodes = {}
    for name, nd in nodes_data.items():
        node_type = nd.get("type", "")
        rn = {"type": node_type}

        # Location
        loc = nd.get("location_absolute", nd.get("location", [0, 0]))
        rn["location"] = [round(loc[0]), round(loc[1])]

        # Non-default properties (skip visual noise)
        node_def = NODE_DEFAULTS.get(node_type)
        def_props = node_def.get("props", {}) if node_def else {}
        def_inputs = node_def.get("inputs") if node_def else None

        props = {}
        for k, v in nd.items():
            if k in _COMPACT_SKIP or k in _AI_JSON_SKIP_PROPS:
                continue
            if v is None:
                continue
            if k in _DEFAULT_NODE_PROPS and v == _DEFAULT_NODE_PROPS[k]:
                continue
            if k in def_props and _values_equal(v, def_props[k]):
                continue
            props[k] = v
        if props:
            rn["settings"] = props

        # Named inputs (only non-default, non-None)
        raw_inputs = nd.get("inputs", [])
        named_inputs = {}
        for i, v in enumerate(raw_inputs):
            if v is None:
                continue
            if (
                def_inputs is not None
                and i < len(def_inputs)
                and _values_equal(v, def_inputs[i])
            ):
                continue
            sock_name = _input_name(node_type, i)
            # Handle duplicate socket names (e.g. Math has 3x "Value")
            if sock_name in named_inputs:
                sock_name = f"{sock_name} {i}"
            named_inputs[sock_name] = v
        if named_inputs:
            rn["inputs"] = named_inputs

        # Named outputs (only for nodes with user-settable outputs)
        if node_type in _USER_OUTPUT_NODES:
            raw_outputs = nd.get("outputs", [])
            named_outputs = {}
            for i, v in enumerate(raw_outputs):
                if v is None:
                    continue
                out_name = _output_name(node_type, i)
                if out_name in named_outputs:
                    out_name = f"{out_name} {i}"
                named_outputs[out_name] = v
            if named_outputs:
                rn["outputs"] = named_outputs

        readable_nodes[name] = rn

    # Readable links: ["FromNode.Socket", "ToNode.Socket"]
    readable_links = []
    seen_from = {}
    seen_to = {}
    for link in links_data:
        from_node = link["from_node"]
        to_node = link["to_node"]
        from_sock = link.get("from_socket", link.get("from_socket_identifier", ""))
        to_sock = link.get("to_socket", link.get("to_socket_identifier", ""))

        # Disambiguate duplicate output socket names
        from_key = (from_node, from_sock)
        from_count = seen_from.get(from_key, 0)
        if from_count > 0:
            out_names = OUTPUT_NAMES.get(
                nodes_data.get(from_node, {}).get("type", ""), []
            )
            matches = [i for i, n in enumerate(out_names) if n == from_sock]
            if from_count < len(matches):
                from_sock = f"{from_sock} {matches[from_count]}"
        seen_from[from_key] = from_count + 1

        # Disambiguate duplicate input socket names
        to_key = (to_node, to_sock)
        to_count = seen_to.get(to_key, 0)
        if to_count > 0:
            in_names = INPUT_NAMES.get(nodes_data.get(to_node, {}).get("type", ""), [])
            matches = [i for i, n in enumerate(in_names) if n == to_sock]
            if to_count < len(matches):
                to_sock = f"{to_sock} {matches[to_count]}"
        seen_to[to_key] = to_count + 1

        readable_links.append([f"{from_node}.{from_sock}", f"{to_node}.{to_sock}"])

    result = {"nodes": readable_nodes, "links": readable_links}

    if "tree_type" in data:
        result["tree_type"] = data["tree_type"]
    if "name" in data:
        result["name"] = data["name"]
    for key in ("blender_version", "export_name"):
        if key in data:
            result[key] = data[key]

    return json.dumps(result, indent=2, ensure_ascii=False)


def decode_ai_json(json_string: str) -> str:
    """Deserialize an AI JSON string to a node tree dictionary.

    Handles both the AI-readable format (named inputs, link strings)
    and the legacy compact format (arrays, sparse inputs).
    """
    try:
        data = json.loads(json_string)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to decode AI JSON node data: {exc}") from exc

    # Legacy compact format, delegate to _expand_data
    if "v" in data and "n" in data:
        return _expand_data(data)

    # New AI-readable format
    nodes_src = data.get("nodes", {})
    links_src = data.get("links", [])

    nodes = {}
    for name, rn in nodes_src.items():
        nd = {}
        node_type = rn.get("type", "")
        nd["type"] = node_type
        nd["name"] = name
        nd["label"] = rn.get("label", "")

        loc = rn.get("location", [0, 0])
        nd["location"] = [float(loc[0]), float(loc[1])]
        nd["location_absolute"] = [float(loc[0]), float(loc[1])]

        # Restore settings as top-level properties
        for k, v in rn.get("settings", {}).items():
            nd[k] = v

        # Convert named inputs back to positional array
        named_inputs = rn.get("inputs", {})
        if named_inputs:
            nd["inputs"] = _resolve_named_sockets(
                named_inputs, INPUT_NAMES.get(node_type)
            )
        else:
            nd["inputs"] = []

        # Convert named outputs back to positional array
        named_outputs = rn.get("outputs", {})
        if named_outputs:
            nd["outputs"] = _resolve_named_sockets(
                named_outputs, OUTPUT_NAMES.get(node_type)
            )
        else:
            nd["outputs"] = []

        nodes[name] = nd

    # Convert link strings back to dict format
    links = []
    used_from = {}
    used_to = {}
    for link_pair in links_src:
        from_str, to_str = link_pair
        from_node, from_sock_raw = from_str.split(".", 1)
        to_node, to_sock_raw = to_str.split(".", 1)

        # Parse "Shader 2" style disambiguation
        from_sock = from_sock_raw
        from_idx = None
        parts = from_sock_raw.rsplit(" ", 1)
        if len(parts) == 2 and parts[1].isdigit():
            from_sock = parts[0]
            from_idx = int(parts[1])

        to_sock = to_sock_raw
        to_idx = None
        parts = to_sock_raw.rsplit(" ", 1)
        if len(parts) == 2 and parts[1].isdigit():
            to_sock = parts[0]
            to_idx = int(parts[1])

        # For bare duplicate names, resolve by link order
        if from_idx is None:
            from_key = (from_node, from_sock)
            from_count = used_from.get(from_key, 0)
            from_type = nodes.get(from_node, {}).get("type", "")
            out_names = OUTPUT_NAMES.get(from_type, [])
            matches = [i for i, n in enumerate(out_names) if n == from_sock]
            if len(matches) > 1 and from_count < len(matches):
                from_idx = matches[from_count]
            used_from[from_key] = from_count + 1

        if to_idx is None:
            to_key = (to_node, to_sock)
            to_count = used_to.get(to_key, 0)
            to_type = nodes.get(to_node, {}).get("type", "")
            in_names = INPUT_NAMES.get(to_type, [])
            matches = [i for i, n in enumerate(in_names) if n == to_sock]
            if len(matches) > 1 and to_count < len(matches):
                to_idx = matches[to_count]
            used_to[to_key] = to_count + 1

        link_dict = {
            "from_node": from_node,
            "to_node": to_node,
            "from_socket": from_sock,
            "from_socket_identifier": from_sock,
            "to_socket": to_sock,
            "to_socket_identifier": to_sock,
        }
        if from_idx is not None:
            link_dict["from_socket_index"] = from_idx
        if to_idx is not None:
            link_dict["to_socket_index"] = to_idx
        links.append(link_dict)

    result = {"nodes": nodes, "links": links}
    if "name" in data:
        result["name"] = data["name"]
    if "tree_type" in data:
        result["tree_type"] = data["tree_type"]
    for key in ("blender_version", "export_name"):
        if key in data:
            result[key] = data[key]

    return result


# XML


def _dict_to_xml(tag: str, data) -> ET.Element:
    """Recursively convert a Python value to an XML element tree.

    Type information is stored in a ``type`` attribute so the structure
    can be faithfully round-tripped.
    """
    elem = ET.Element(tag)

    if isinstance(data, dict):
        elem.set("type", "dict")
        for key, value in data.items():
            child = _dict_to_xml(key, value)
            elem.append(child)
    elif isinstance(data, list):
        elem.set("type", "list")
        for item in data:
            child = _dict_to_xml("item", item)
            elem.append(child)
    elif isinstance(data, bool):
        elem.set("type", "bool")
        elem.text = str(data).lower()
    elif isinstance(data, int):
        elem.set("type", "int")
        elem.text = str(data)
    elif isinstance(data, float):
        elem.set("type", "float")
        elem.text = repr(data)
    elif data is None:
        elem.set("type", "none")
    else:
        elem.set("type", "str")
        elem.text = str(data)

    return elem


def _xml_to_dict(elem: ET.Element):
    """Recursively convert an XML element tree back to Python objects."""
    dtype = elem.get("type", "str")

    converters = {
        "dict": lambda e: {child.tag: _xml_to_dict(child) for child in e},
        "list": lambda e: [_xml_to_dict(child) for child in e],
        "bool": lambda e: e.text == "true",
        "int": lambda e: int(e.text),
        "float": lambda e: float(e.text),
        "none": lambda _: None,
        "str": lambda e: e.text or "",
    }

    return converters.get(dtype, converters["str"])(elem)


def encode_xml(data: dict) -> str:
    """Serialize node tree data to an XML string."""
    root = _dict_to_xml("node_runner", data)
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="unicode", xml_declaration=True)


def decode_xml(xml_string: str) -> dict:
    """Deserialize an XML string to a node tree dictionary."""
    try:
        root = ET.fromstring(xml_string)
        return _xml_to_dict(root)
    except ET.ParseError as exc:
        raise ValueError(f"Failed to decode XML node data: {exc}") from exc


# Unified API


def encode_as(data: dict, fmt: str = FORMAT_HASH) -> str:
    """Encode node tree data in the given format."""
    if fmt == FORMAT_HASH:
        return encode(data)
    if fmt == FORMAT_JSON:
        return encode_json(data)
    if fmt == FORMAT_AI_JSON:
        return encode_ai_json(data)
    if fmt == FORMAT_XML:
        return encode_xml(data)
    raise ValueError(f"Unknown format: {fmt!r}")


def decode_as(encoded: str, fmt: str = FORMAT_HASH, *,
              allow_pickle: bool = True) -> dict:
    """Decode an encoded string in the given format.

    *allow_pickle* only affects the hash format; the JSON and XML paths
    never reach the pickle fallback.
    """
    if fmt == FORMAT_HASH:
        return decode(encoded, allow_pickle=allow_pickle)
    if fmt == FORMAT_AI_JSON:
        return decode_ai_json(encoded)
    if fmt == FORMAT_JSON:
        return decode_ai_json(encoded) if _is_ai_json(encoded) else decode_json(encoded)
    if fmt == FORMAT_XML:
        return decode_xml(encoded)
    raise ValueError(f"Unknown format: {fmt!r}")


def _is_ai_json(raw: str) -> bool:
    """Return True if *raw* looks like AI JSON or legacy compact JSON."""
    try:
        d = json.loads(raw)
        if not isinstance(d, dict):
            return False
        # Legacy compact format
        if "v" in d and "n" in d:
            return True
        # AI-readable format: "nodes" dict whose values have "type" keys
        # and inputs stored as dicts (named) rather than lists (positional)
        nodes = d.get("nodes")
        if isinstance(nodes, dict) and nodes:
            first = next(iter(nodes.values()))
            if not isinstance(first, dict) or "type" not in first:
                return False
            inputs = first.get("inputs")
            # AI JSON uses dict inputs; regular JSON uses list inputs
            return inputs is None or isinstance(inputs, dict)
        return False
    except (json.JSONDecodeError, ValueError):
        return False


def detect_format(data: str) -> str:
    """Auto-detect the format of an encoded node data string."""
    stripped = data.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        if _is_ai_json(stripped):
            return FORMAT_AI_JSON
        return FORMAT_JSON
    if stripped.startswith("<"):
        return FORMAT_XML
    return FORMAT_HASH

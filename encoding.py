"""
Encoding and decoding utilities for Node Runner.

Handles compression (zlib) and encoding (base64) of serialized node data.
Supports multiple output formats: base64 (default), JSON, and XML.
"""

import base64
import binascii
import json
import logging
import pickle
import xml.etree.ElementTree as ET
import zlib

log = logging.getLogger(__name__)

# Format identifiers
FORMAT_HASH = "HASH"
FORMAT_JSON = "JSON"
FORMAT_XML = "XML"

FORMATS = (FORMAT_HASH, FORMAT_JSON, FORMAT_XML)


#  Base64 / hash (default)


def encode(data: dict) -> str:
    """Serialize, compress, and base64-encode node tree data.

    Args:
        data: Serialized node tree dictionary.

    Returns:
        Base64 encoded string.
    """
    raw = pickle.dumps(data, protocol=pickle.HIGHEST_PROTOCOL)
    compressed = zlib.compress(raw, 9)
    return base64.b64encode(compressed).decode("utf-8")


def decode(base64_encoded: str) -> dict:
    """Decode and decompress a base64-encoded node tree string.

    Args:
        base64_encoded: Base64 encoded and zlib compressed data.

    Returns:
        Deserialized node tree dictionary.

    Raises:
        ValueError: If decoding or decompression fails.
    """
    try:
        compressed = base64.b64decode(base64_encoded)
        raw = zlib.decompress(compressed)
        return pickle.loads(raw)
    except (zlib.error, pickle.UnpicklingError, binascii.Error) as exc:
        raise ValueError(f"Failed to decode node data: {exc}") from exc


#  JSON


def encode_json(data: dict) -> str:
    """Serialize node tree data to a JSON string.

    Args:
        data: Serialized node tree dictionary.

    Returns:
        Pretty-printed JSON string.
    """
    return json.dumps(data, indent=2, ensure_ascii=False)


def decode_json(json_string: str) -> dict:
    """Deserialize a JSON string to a node tree dictionary.

    Args:
        json_string: JSON-encoded node tree data.

    Returns:
        Deserialized node tree dictionary.

    Raises:
        ValueError: If the string is not valid JSON.
    """
    try:
        return json.loads(json_string)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to decode JSON node data: {exc}") from exc


#  XML ─


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

    if dtype == "dict":
        return {child.tag: _xml_to_dict(child) for child in elem}
    elif dtype == "list":
        return [_xml_to_dict(child) for child in elem]
    elif dtype == "bool":
        return elem.text == "true"
    elif dtype == "int":
        return int(elem.text)
    elif dtype == "float":
        return float(elem.text)
    elif dtype == "none":
        return None
    else:
        return elem.text or ""


def encode_xml(data: dict) -> str:
    """Serialize node tree data to an XML string.

    Args:
        data: Serialized node tree dictionary.

    Returns:
        XML string with declaration.
    """
    root = _dict_to_xml("node_runner", data)
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="unicode", xml_declaration=True)


def decode_xml(xml_string: str) -> dict:
    """Deserialize an XML string to a node tree dictionary.

    Args:
        xml_string: XML-encoded node tree data.

    Returns:
        Deserialized node tree dictionary.

    Raises:
        ValueError: If the string is not valid XML or cannot be parsed.
    """
    try:
        root = ET.fromstring(xml_string)
        return _xml_to_dict(root)
    except ET.ParseError as exc:
        raise ValueError(f"Failed to decode XML node data: {exc}") from exc


#  Unified API


def encode_as(data: dict, fmt: str = FORMAT_HASH) -> str:
    """Encode node tree data in the given format.

    Args:
        data: Serialized node tree dictionary.
        fmt: One of ``FORMAT_HASH``, ``FORMAT_JSON``, or ``FORMAT_XML``.

    Returns:
        Encoded string in the requested format.

    Raises:
        ValueError: If *fmt* is not recognised.
    """
    if fmt == FORMAT_HASH:
        return encode(data)
    elif fmt == FORMAT_JSON:
        return encode_json(data)
    elif fmt == FORMAT_XML:
        return encode_xml(data)
    raise ValueError(f"Unknown format: {fmt!r}")


def decode_as(encoded: str, fmt: str = FORMAT_HASH) -> dict:
    """Decode an encoded string in the given format.

    Args:
        encoded: Encoded node tree string.
        fmt: One of ``FORMAT_HASH``, ``FORMAT_JSON``, or ``FORMAT_XML``.

    Returns:
        Deserialized node tree dictionary.

    Raises:
        ValueError: If *fmt* is not recognised or decoding fails.
    """
    if fmt == FORMAT_HASH:
        return decode(encoded)
    elif fmt == FORMAT_JSON:
        return decode_json(encoded)
    elif fmt == FORMAT_XML:
        return decode_xml(encoded)
    raise ValueError(f"Unknown format: {fmt!r}")


def detect_format(data: str) -> str:
    """Auto-detect the format of an encoded node data string.

    Inspects leading characters to determine whether the string is
    JSON, XML, or a base64 hash.

    Args:
        data: The raw string to inspect.

    Returns:
        One of ``FORMAT_HASH``, ``FORMAT_JSON``, or ``FORMAT_XML``.
    """
    stripped = data.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        return FORMAT_JSON
    if stripped.startswith("<"):
        return FORMAT_XML
    return FORMAT_HASH

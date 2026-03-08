"""Tests for the encoding module."""

import pytest

from node_runner.encoding import (
    encode,
    decode,
    encode_json,
    decode_json,
    encode_xml,
    decode_xml,
    encode_as,
    decode_as,
    detect_format,
    FORMAT_HASH,
    FORMAT_JSON,
    FORMAT_XML,
)
from node_runner.constants import EXPORT_HEADER


class TestEncodeDecode:
    """Round-trip tests for encode/decode."""

    def test_roundtrip_simple_dict(self):
        data = {"nodes": {}, "links": [], "name": "Test"}
        encoded = encode(data)
        assert isinstance(encoded, str)
        assert len(encoded) > 0
        decoded = decode(encoded)
        assert decoded == data

    def test_roundtrip_with_node_data(self):
        data = {
            "nodes": {
                "Math": {
                    "type": "ShaderNodeMath",
                    "label": "",
                    "operation": "ADD",
                    "location": [100.0, 200.0],
                    "location_absolute": [100.0, 200.0],
                    "inputs": [0.5, 0.5, None],
                }
            },
            "links": [],
            "name": "Material",
        }
        encoded = encode(data)
        decoded = decode(encoded)
        assert decoded["nodes"]["Math"]["operation"] == "ADD"
        assert decoded["nodes"]["Math"]["location"] == [100.0, 200.0]

    def test_roundtrip_with_links(self):
        data = {
            "nodes": {"A": {"type": "ShaderNodeMath"}, "B": {"type": "ShaderNodeMath"}},
            "links": [
                {
                    "from_node": "A",
                    "to_node": "B",
                    "from_socket": "Value",
                    "from_socket_type": "NodeSocketFloat",
                    "from_socket_identifier": "Value",
                    "to_socket": "Value",
                    "to_socket_type": "NodeSocketFloat",
                    "to_socket_identifier": "Value",
                }
            ],
            "name": "Test",
        }
        assert decode(encode(data)) == data

    def test_decode_invalid_data(self):
        with pytest.raises(ValueError, match="Failed to decode"):
            decode("not-valid-base64!!!")

    def test_decode_empty_string(self):
        with pytest.raises(ValueError):
            decode("")

    def test_roundtrip_nested_structures(self):
        data = {
            "nodes": {
                "ColorRamp": {
                    "type": "ShaderNodeValToRGB",
                    "color_ramp": {
                        "color_mode": "RGB",
                        "interpolation": "LINEAR",
                        "hue_interpolation": "NEAR",
                        "elements": [
                            {"position": 0.0, "color": [0.0, 0.0, 0.0, 1.0]},
                            {"position": 1.0, "color": [1.0, 1.0, 1.0, 1.0]},
                        ],
                    },
                }
            },
            "links": [],
            "name": "Test",
        }
        assert decode(encode(data)) == data

    def test_encode_produces_compact_output(self):
        """Encoding with compression should be shorter than raw pickle."""
        import pickle

        data = {"nodes": {"A" * 100: {"type": "X" * 100}}, "links": [], "name": "T"}
        encoded = encode(data)
        raw_len = len(pickle.dumps(data))
        # base64 is ~4/3 overhead, but zlib should more than compensate
        # for repetitive data
        assert len(encoded) < raw_len * 2


# ── Sample data used by JSON / XML tests ─────────────────────────────

_SIMPLE_DATA = {"nodes": {}, "links": [], "name": "Test"}

_NODE_DATA = {
    "nodes": {
        "Math": {
            "type": "ShaderNodeMath",
            "label": "",
            "operation": "ADD",
            "location": [100.0, 200.0],
            "location_absolute": [100.0, 200.0],
            "inputs": [0.5, 0.5],
        }
    },
    "links": [],
    "name": "Material",
}

_NESTED_DATA = {
    "nodes": {
        "ColorRamp": {
            "type": "ShaderNodeValToRGB",
            "color_ramp": {
                "color_mode": "RGB",
                "interpolation": "LINEAR",
                "hue_interpolation": "NEAR",
                "elements": [
                    {"position": 0.0, "color": [0.0, 0.0, 0.0, 1.0]},
                    {"position": 1.0, "color": [1.0, 1.0, 1.0, 1.0]},
                ],
            },
        }
    },
    "links": [],
    "name": "Test",
}


class TestJsonEncodeDecode:
    """Round-trip tests for JSON encode/decode."""

    def test_roundtrip_simple_dict(self):
        encoded = encode_json(_SIMPLE_DATA)
        assert isinstance(encoded, str)
        decoded = decode_json(encoded)
        assert decoded == _SIMPLE_DATA

    def test_roundtrip_with_node_data(self):
        encoded = encode_json(_NODE_DATA)
        decoded = decode_json(encoded)
        assert decoded["nodes"]["Math"]["operation"] == "ADD"
        assert decoded["nodes"]["Math"]["location"] == [100.0, 200.0]

    def test_roundtrip_nested_structures(self):
        assert decode_json(encode_json(_NESTED_DATA)) == _NESTED_DATA

    def test_output_is_human_readable(self):
        encoded = encode_json(_SIMPLE_DATA)
        assert "\n" in encoded
        assert '"name"' in encoded

    def test_output_is_valid_json(self):
        """Exported JSON must be a valid standalone document."""
        import json

        data_with_name = dict(_SIMPLE_DATA, export_name="MyNodes")
        encoded = encode_json(data_with_name)
        parsed = json.loads(encoded)
        assert parsed["export_name"] == "MyNodes"

    def test_decode_invalid_json(self):
        with pytest.raises(ValueError, match="Failed to decode JSON"):
            decode_json("{invalid json!!}")

    def test_decode_empty_string(self):
        with pytest.raises(ValueError):
            decode_json("")

    def test_preserves_none_values(self):
        data = {"nodes": {"A": {"value": None}}, "links": [], "name": "T"}
        assert decode_json(encode_json(data)) == data

    def test_preserves_bool_values(self):
        data = {"nodes": {"A": {"flag": True, "off": False}}, "links": [], "name": "T"}
        assert decode_json(encode_json(data)) == data

    def test_export_name_roundtrip(self):
        data = dict(_SIMPLE_DATA, export_name="TestExport")
        decoded = decode_json(encode_json(data))
        assert decoded["export_name"] == "TestExport"
        # After popping, original data is recovered
        decoded.pop("export_name")
        assert decoded == _SIMPLE_DATA


class TestXmlEncodeDecode:
    """Round-trip tests for XML encode/decode."""

    def test_roundtrip_simple_dict(self):
        encoded = encode_xml(_SIMPLE_DATA)
        assert isinstance(encoded, str)
        decoded = decode_xml(encoded)
        assert decoded == _SIMPLE_DATA

    def test_roundtrip_with_node_data(self):
        encoded = encode_xml(_NODE_DATA)
        decoded = decode_xml(encoded)
        assert decoded["nodes"]["Math"]["operation"] == "ADD"
        assert decoded["nodes"]["Math"]["location"] == [100.0, 200.0]

    def test_roundtrip_nested_structures(self):
        assert decode_xml(encode_xml(_NESTED_DATA)) == _NESTED_DATA

    def test_output_is_xml(self):
        encoded = encode_xml(_SIMPLE_DATA)
        assert encoded.startswith("<?xml")
        assert "<node_runner" in encoded

    def test_output_is_valid_xml(self):
        """Exported XML must be a valid standalone document."""
        import xml.etree.ElementTree as ET

        data_with_name = dict(_SIMPLE_DATA, export_name="MyNodes")
        encoded = encode_xml(data_with_name)
        root = ET.fromstring(encoded)
        assert root.tag == "node_runner"

    def test_decode_invalid_xml(self):
        with pytest.raises(ValueError, match="Failed to decode XML"):
            decode_xml("<unclosed")

    def test_decode_empty_string(self):
        with pytest.raises(ValueError):
            decode_xml("")

    def test_preserves_none_values(self):
        data = {"nodes": {"A": {"value": None}}, "links": [], "name": "T"}
        assert decode_xml(encode_xml(data)) == data

    def test_preserves_bool_values(self):
        data = {"nodes": {"A": {"flag": True, "off": False}}, "links": [], "name": "T"}
        assert decode_xml(encode_xml(data)) == data

    def test_preserves_int_vs_float(self):
        data = {"nodes": {}, "links": [], "name": "T", "count": 42, "ratio": 3.14}
        result = decode_xml(encode_xml(data))
        assert isinstance(result["count"], int)
        assert isinstance(result["ratio"], float)

    def test_export_name_roundtrip(self):
        data = dict(_SIMPLE_DATA, export_name="TestExport")
        decoded = decode_xml(encode_xml(data))
        assert decoded["export_name"] == "TestExport"
        decoded.pop("export_name")
        assert decoded == _SIMPLE_DATA


class TestEncodeAsDecodeAs:
    """Tests for the unified encode_as / decode_as API."""

    @pytest.mark.parametrize("fmt", [FORMAT_HASH, FORMAT_JSON, FORMAT_XML])
    def test_roundtrip_all_formats(self, fmt):
        encoded = encode_as(_NODE_DATA, fmt)
        decoded = decode_as(encoded, fmt)
        assert decoded == _NODE_DATA

    def test_default_is_hash(self):
        assert encode_as(_SIMPLE_DATA) == encode(_SIMPLE_DATA)

    def test_unknown_format_encode(self):
        with pytest.raises(ValueError, match="Unknown format"):
            encode_as(_SIMPLE_DATA, "TOML")

    def test_unknown_format_decode(self):
        with pytest.raises(ValueError, match="Unknown format"):
            decode_as("data", "TOML")


class TestDetectFormat:
    """Tests for auto-detection of format from raw strings."""

    def test_detect_json_object(self):
        assert detect_format('{"nodes": {}}') == FORMAT_JSON

    def test_detect_json_array(self):
        assert detect_format("[1, 2, 3]") == FORMAT_JSON

    def test_detect_xml(self):
        assert detect_format("<?xml version='1.0'?>") == FORMAT_XML

    def test_detect_xml_element(self):
        assert detect_format("<node_runner>") == FORMAT_XML

    def test_detect_hash(self):
        assert detect_format("eJzLSM3JyQcABJgB8Q==") == FORMAT_HASH

    def test_detect_with_whitespace(self):
        assert detect_format('  \n  {"a": 1}') == FORMAT_JSON


class TestExportImportFlow:
    """End-to-end tests simulating the operator build/strip helpers."""

    def _build_export_string(self, data, export_name, fmt):
        """Mirror the operator helper ``_build_export_string``."""
        if fmt in (FORMAT_JSON, FORMAT_XML):
            data = dict(data)
            data["export_name"] = export_name
            return encode_as(data, fmt)
        encoded = encode_as(data, fmt)
        return (export_name or "MyNodes") + EXPORT_HEADER + encoded

    def _strip_header_and_detect(self, raw):
        """Mirror the operator helper ``_strip_header_and_detect``."""
        if EXPORT_HEADER in raw:
            payload = raw.split(EXPORT_HEADER, 1)[1]
            return FORMAT_HASH, payload
        fmt = detect_format(raw)
        return fmt, raw

    @pytest.mark.parametrize("fmt", [FORMAT_HASH, FORMAT_JSON, FORMAT_XML])
    def test_roundtrip_all_formats(self, fmt):
        export_str = self._build_export_string(_NODE_DATA, "TestExport", fmt)
        detected_fmt, payload = self._strip_header_and_detect(export_str)
        assert detected_fmt == fmt
        decoded = decode_as(payload, detected_fmt)
        decoded.pop("export_name", None)
        assert decoded == _NODE_DATA

    def test_hash_export_has_header(self):
        export_str = self._build_export_string(_SIMPLE_DATA, "Foo", FORMAT_HASH)
        assert export_str.startswith("Foo" + EXPORT_HEADER)

    def test_json_export_is_valid_json(self):
        import json

        export_str = self._build_export_string(_SIMPLE_DATA, "Foo", FORMAT_JSON)
        parsed = json.loads(export_str)
        assert parsed["export_name"] == "Foo"

    def test_xml_export_is_valid_xml(self):
        import xml.etree.ElementTree as ET

        export_str = self._build_export_string(_SIMPLE_DATA, "Foo", FORMAT_XML)
        root = ET.fromstring(export_str)
        assert root.tag == "node_runner"

    def test_json_no_header_prefix(self):
        export_str = self._build_export_string(_SIMPLE_DATA, "Foo", FORMAT_JSON)
        assert not export_str.startswith("Foo" + EXPORT_HEADER)
        assert export_str.lstrip().startswith("{")

    def test_xml_no_header_prefix(self):
        export_str = self._build_export_string(_SIMPLE_DATA, "Foo", FORMAT_XML)
        assert not export_str.startswith("Foo" + EXPORT_HEADER)
        assert export_str.lstrip().startswith("<")

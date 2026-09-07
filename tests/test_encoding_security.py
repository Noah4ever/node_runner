"""Tests for the decode hardening that makes remote payloads safe.

The hash format's legacy fallback runs ``pickle.loads``, which executes
arbitrary code. That is tolerable for a string the user pasted themselves
and unacceptable for one fetched from a library repository, so the network
path must be able to turn it off.
"""

import base64
import pickle
import zlib

import pytest

from node_runner.encoding import (
    FORMAT_HASH,
    FORMAT_JSON,
    FORMAT_XML,
    MAX_DECOMPRESSED_BYTES,
    decode,
    decode_as,
    encode,
    encode_as,
    encode_json,
    encode_xml,
)


def _legacy_pickle_payload(data):
    """Build a string in the pre-JSON pickle format."""
    raw = pickle.dumps(data, protocol=pickle.HIGHEST_PROTOCOL)
    return base64.b64encode(zlib.compress(raw, 9)).decode("utf-8")


DATA = {"nodes": {"A": {"type": "ShaderNodeMath"}}, "links": [], "name": "T"}


def test_legacy_pickle_still_decodes_for_local_sources():
    assert decode(_legacy_pickle_payload(DATA)) == DATA


def test_legacy_pickle_is_refused_when_pickle_is_disallowed():
    with pytest.raises(ValueError, match="Refusing to decode legacy pickle"):
        decode(_legacy_pickle_payload(DATA), allow_pickle=False)


def test_pickle_payload_is_never_executed_when_disallowed():
    """The refusal must happen before unpickling, not after.

    This payload is a GLOBAL opcode naming a module that does not exist, so
    reaching ``pickle.loads`` would raise ModuleNotFoundError. Getting the
    refusal message instead proves the unpickle was never attempted.
    """
    raw = b"cnode_runner_no_such_module_xyz\nboom\n."
    payload = base64.b64encode(zlib.compress(raw, 9)).decode("utf-8")
    with pytest.raises(ValueError, match="Refusing to decode legacy pickle"):
        decode(payload, allow_pickle=False)


def test_current_json_hash_format_decodes_with_pickle_disallowed():
    """Disabling pickle must not change what a current payload decodes to."""
    encoded = encode(DATA)
    assert decode(encoded, allow_pickle=False) == decode(encoded)


def test_decode_as_forwards_the_flag_for_the_hash_format():
    payload = _legacy_pickle_payload(DATA)
    assert decode_as(payload, FORMAT_HASH) == DATA
    with pytest.raises(ValueError):
        decode_as(payload, FORMAT_HASH, allow_pickle=False)


def test_decode_as_round_trips_hash_with_pickle_disallowed():
    encoded = encode_as(DATA, FORMAT_HASH)
    assert decode_as(encoded, FORMAT_HASH, allow_pickle=False) == decode_as(
        encoded, FORMAT_HASH
    )


@pytest.mark.parametrize(
    "fmt,encoder", [(FORMAT_JSON, encode_json), (FORMAT_XML, encode_xml)]
)
def test_text_formats_are_unaffected_by_the_flag(fmt, encoder):
    encoded = encoder(DATA)
    assert decode_as(encoded, fmt, allow_pickle=False) == decode_as(encoded, fmt)


def test_allow_pickle_is_keyword_only():
    """Nobody should be able to flip this by passing a stray positional."""
    with pytest.raises(TypeError):
        decode(encode(DATA), False)  # pylint: disable=too-many-function-args


def test_zip_bomb_is_refused_rather_than_inflated():
    bomb = base64.b64encode(
        zlib.compress(b"\0" * (MAX_DECOMPRESSED_BYTES + 1024), 9)
    ).decode("utf-8")
    with pytest.raises(ValueError, match="expands beyond"):
        decode(bomb)


def test_truncated_stream_is_an_error_not_a_pickle_attempt():
    good = base64.b64decode(encode(DATA))
    truncated = base64.b64encode(good[: len(good) // 2]).decode("utf-8")
    with pytest.raises(ValueError, match="Failed to decode node data"):
        decode(truncated)


def test_empty_payload_is_an_error():
    with pytest.raises(ValueError):
        decode("")


def test_garbage_payload_is_an_error():
    with pytest.raises(ValueError):
        decode("not base64 at all !!!")

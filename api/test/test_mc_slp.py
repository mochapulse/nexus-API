"""Tests for api.mc.slp: VarInt helpers and the Server List Ping probe."""

import json

import pytest

from api.mc import slp


class _BufferReader:
    """Test double matching the recv() interface, feeding fixed chunks."""

    def __init__(self, data: bytes, chunk_size: int = 1) -> None:
        self._data = data
        self._chunk_size = chunk_size
        self._offset = 0

    def recv(self, num_bytes: int) -> bytes:
        if self._offset >= len(self._data):
            return b""
        size = min(num_bytes, self._chunk_size, len(self._data) - self._offset)
        chunk = self._data[self._offset : self._offset + size]
        self._offset += size
        return chunk


class _FakeSocket:
    """Fake socket returning a prebuilt response in small chunks.

    Exercises the partial-read loop in ``_recv_exact``: every ``recv()``
    call returns at most ``chunk_size`` bytes, regardless of how many
    bytes were requested.
    """

    def __init__(self, response: bytes, chunk_size: int = 3) -> None:
        self._reader = _BufferReader(response, chunk_size=chunk_size)
        self.sent = bytearray()

    def sendall(self, data: bytes) -> None:
        self.sent.extend(data)

    def recv(self, num_bytes: int) -> bytes:
        return self._reader.recv(num_bytes)

    def settimeout(self, _timeout: float) -> None:
        pass

    def __enter__(self) -> "_FakeSocket":
        return self

    def __exit__(self, *_exc_info: object) -> bool:
        return False


def _build_status_response(payload: dict, packet_id: int = 0x00) -> bytes:
    """Frame a status response packet the way a real server would."""
    json_bytes = json.dumps(payload).encode("utf-8")
    body = slp.encode_varint(packet_id) + slp.encode_varint(len(json_bytes)) + json_bytes
    return slp.encode_varint(len(body)) + body


class TestVarInt:
    @pytest.mark.parametrize(
        "value",
        [0, 1, 15, 127, 128, 255, 300, 2097151, 2147483647],
    )
    def test_round_trip(self, value):
        encoded = slp.encode_varint(value)
        decoded = slp.decode_varint(_BufferReader(encoded))
        assert decoded == value

    def test_negative_protocol_version_encodes_as_unsigned_32bit(self):
        encoded = slp.encode_varint(-1)
        decoded = slp.decode_varint(_BufferReader(encoded))
        assert decoded == 0xFFFFFFFF

    def test_decode_varint_too_long_raises(self):
        # Five continuation bytes with the high bit set, never terminating.
        malformed = bytes([0xFF] * 5)
        with pytest.raises(ValueError):
            slp.decode_varint(_BufferReader(malformed))

    def test_decode_varint_exhausted_reader_raises(self):
        with pytest.raises(ConnectionError):
            slp.decode_varint(_BufferReader(b""))

    def test_recv_exact_over_partial_reads(self):
        reader = _BufferReader(b"abcdefgh", chunk_size=3)
        assert slp._recv_exact(reader, 8) == b"abcdefgh"


class TestExtractMotd:
    def test_plain_string(self):
        assert slp._extract_motd("Welcome!") == "Welcome!"

    def test_none(self):
        assert slp._extract_motd(None) is None

    def test_chat_component_text_only(self):
        assert slp._extract_motd({"text": "Hello"}) == "Hello"

    def test_chat_component_with_extra(self):
        description = {
            "text": "Hello ",
            "extra": [{"text": "World"}, {"text": "!"}],
        }
        assert slp._extract_motd(description) == "Hello World!"

    def test_unrecognized_shape_returns_none(self):
        assert slp._extract_motd(42) is None


class TestProbe:
    def test_probe_success_with_partial_reads(self, monkeypatch):
        payload = {
            "version": {"name": "1.20.1"},
            "players": {"online": 3, "max": 20},
            "description": {"text": "A ", "extra": [{"text": "Minecraft Server"}]},
        }
        response = _build_status_response(payload)
        fake_socket = _FakeSocket(response, chunk_size=3)
        monkeypatch.setattr(
            slp.socket, "create_connection", lambda *a, **kw: fake_socket
        )

        status = slp.probe("localhost", 25565)

        assert status.online is True
        assert status.players_online == 3
        assert status.players_max == 20
        assert status.version == "1.20.1"
        assert status.motd == "A Minecraft Server"
        assert status.latency_ms is not None and status.latency_ms >= 0
        assert status.error is None

    def test_probe_connection_refused(self, monkeypatch):
        def _raise_refused(*_args, **_kwargs):
            raise ConnectionRefusedError("connection refused")

        monkeypatch.setattr(slp.socket, "create_connection", _raise_refused)

        status = slp.probe("localhost", 25565)

        assert status.online is False
        assert status.players_online is None
        assert status.error is not None

    def test_probe_timeout(self, monkeypatch):
        def _raise_timeout(*_args, **_kwargs):
            raise TimeoutError("timed out")

        monkeypatch.setattr(slp.socket, "create_connection", _raise_timeout)

        status = slp.probe("localhost", 25565, timeout=0.1)

        assert status.online is False
        assert status.error is not None

    def test_probe_malformed_json(self, monkeypatch):
        body = slp.encode_varint(0x00) + slp.encode_varint(4) + b"nope"
        response = slp.encode_varint(len(body)) + body
        fake_socket = _FakeSocket(response)
        monkeypatch.setattr(
            slp.socket, "create_connection", lambda *a, **kw: fake_socket
        )

        status = slp.probe("localhost", 25565)

        assert status.online is False
        assert status.error is not None

    def test_probe_non_object_json(self, monkeypatch):
        json_bytes = b"[1, 2, 3]"
        body = slp.encode_varint(0x00) + slp.encode_varint(len(json_bytes)) + json_bytes
        response = slp.encode_varint(len(body)) + body
        fake_socket = _FakeSocket(response)
        monkeypatch.setattr(
            slp.socket, "create_connection", lambda *a, **kw: fake_socket
        )

        status = slp.probe("localhost", 25565)

        assert status.online is False

    def test_probe_oversized_length_rejected(self, monkeypatch):
        # Advertise a packet length far above the 1 MiB cap.
        response = slp.encode_varint(slp._MAX_PACKET_LENGTH + 1)
        fake_socket = _FakeSocket(response)
        monkeypatch.setattr(
            slp.socket, "create_connection", lambda *a, **kw: fake_socket
        )

        status = slp.probe("localhost", 25565)

        assert status.online is False
        assert status.error is not None

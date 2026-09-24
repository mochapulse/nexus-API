"""Minecraft Java Edition Server List Ping (SLP) probe.

Implements the status handshake of the Minecraft Java Edition protocol
over the stdlib ``socket`` module: no external dependency, no async
runtime. Calls are blocking; the watchdog runs :func:`probe` through
``asyncio.to_thread`` so it never blocks the event loop.

See https://minecraft.wiki/w/Java_Edition_protocol/Server_List_Ping for
the wire format this module implements.
"""

import json
import logging
import socket
import struct
import time
from dataclasses import dataclass
from typing import Protocol

log = logging.getLogger(__name__)

# Caps against a malicious or malformed server sending an absurd or
# unbounded length prefix.
_MAX_PACKET_LENGTH = 1024 * 1024  # 1 MiB
_MAX_VARINT_BYTES = 5

_HANDSHAKE_PACKET_ID = 0x00
_STATUS_REQUEST_PACKET_ID = 0x00
_STATUS_NEXT_STATE = 0x01
_HANDSHAKE_PROTOCOL_VERSION = -1  # any value is accepted for a status ping


@dataclass(frozen=True)
class McStatus:
    """Result of a Server List Ping probe.

    ``online`` reflects whether the server answered the status request.
    On success, ``players_online``, ``players_max``, ``version``, and
    ``motd`` carry the parsed status, ``latency_ms`` is the wall-clock
    time of the status exchange, and ``error`` is ``None``. On failure,
    every field except ``online`` and ``error`` is ``None``, and
    ``error`` holds a human-readable failure reason.
    """

    online: bool
    players_online: int | None
    players_max: int | None
    version: str | None
    motd: str | None
    latency_ms: float | None
    error: str | None


class _Recvable(Protocol):
    """Structural type for anything :func:`_recv_exact` can read from."""

    def recv(self, num_bytes: int) -> bytes: ...


class _BufferReader:
    """Adapts an in-memory ``bytes`` buffer to the ``recv()`` interface.

    Lets the same VarInt/exact-read helpers used against a live socket
    also parse an already-buffered response body.
    """

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._offset = 0

    def recv(self, num_bytes: int) -> bytes:
        chunk = self._data[self._offset : self._offset + num_bytes]
        self._offset += len(chunk)
        return chunk


def encode_varint(value: int) -> bytes:
    """Encode an integer as a protocol VarInt.

    Negative values (only the handshake's placeholder protocol version,
    ``-1``, in practice) are encoded via their unsigned 32-bit two's
    complement representation, matching the Minecraft protocol's VarInt
    convention.

    Args:
        value: The integer to encode.

    Returns:
        The VarInt-encoded bytes (1 to 5 bytes).
    """
    value &= 0xFFFFFFFF
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def decode_varint(reader: _Recvable) -> int:
    """Decode a protocol VarInt by reading one byte at a time.

    Args:
        reader: Any object exposing ``recv(num_bytes)``, such as a
            ``socket.socket`` or a :class:`_BufferReader`.

    Returns:
        The decoded non-negative integer.

    Raises:
        ValueError: If the VarInt exceeds :data:`_MAX_VARINT_BYTES`
            bytes without terminating.
        ConnectionError: If the underlying reader is exhausted before a
            complete VarInt is read.
    """
    result = 0
    for index in range(_MAX_VARINT_BYTES):
        byte = _recv_exact(reader, 1)[0]
        result |= (byte & 0x7F) << (7 * index)
        if not (byte & 0x80):
            return result
    raise ValueError("VarInt exceeds the maximum length of 5 bytes")


def _recv_exact(reader: _Recvable, num_bytes: int) -> bytes:
    """Read exactly ``num_bytes`` from ``reader``, looping over partial reads.

    ``socket.recv()`` (and our in-memory stand-in) may return fewer bytes
    than requested even when more data is available.

    Args:
        reader: Any object exposing ``recv(num_bytes)``.
        num_bytes: The exact number of bytes to read.

    Returns:
        Exactly ``num_bytes`` bytes.

    Raises:
        ConnectionError: If the reader is exhausted before ``num_bytes``
            bytes are available.
    """
    chunks = bytearray()
    while len(chunks) < num_bytes:
        chunk = reader.recv(num_bytes - len(chunks))
        if not chunk:
            raise ConnectionError(
                "connection closed while reading Minecraft SLP response"
            )
        chunks.extend(chunk)
    return bytes(chunks)


def _encode_string(text: str) -> bytes:
    """Encode a string as a VarInt-length-prefixed UTF-8 payload."""
    data = text.encode("utf-8")
    return encode_varint(len(data)) + data


def _build_handshake(host: str, port: int) -> bytes:
    """Build the framed handshake packet requesting the status state."""
    payload = bytearray()
    payload += encode_varint(_HANDSHAKE_PACKET_ID)
    payload += encode_varint(_HANDSHAKE_PROTOCOL_VERSION)
    payload += _encode_string(host)
    payload += struct.pack(">H", port)
    payload += encode_varint(_STATUS_NEXT_STATE)
    return encode_varint(len(payload)) + bytes(payload)


def _build_status_request() -> bytes:
    """Build the framed status request packet."""
    payload = encode_varint(_STATUS_REQUEST_PACKET_ID)
    return encode_varint(len(payload)) + payload


def _extract_motd(description: object) -> str | None:
    """Best-effort plain-text extraction from a ``description`` field.

    ``description`` may be a plain string or a Minecraft chat component
    (a dict with a ``text`` field and an optional ``extra`` list of
    further components). Unrecognized shapes yield ``None`` rather than
    raising.

    Args:
        description: The raw ``description``/MOTD value from the status
            JSON payload.

    Returns:
        The concatenated plain text, or ``None`` if nothing could be
        extracted.
    """
    if isinstance(description, str):
        return description or None
    if not isinstance(description, dict):
        return None

    parts: list[str] = []
    text = description.get("text")
    if isinstance(text, str) and text:
        parts.append(text)
    for extra in description.get("extra") or []:
        if isinstance(extra, str) and extra:
            parts.append(extra)
        elif isinstance(extra, dict):
            extra_text = extra.get("text")
            if isinstance(extra_text, str) and extra_text:
                parts.append(extra_text)

    return "".join(parts) if parts else None


def _status_from_payload(payload: dict, latency_ms: float) -> McStatus:
    """Build an online :class:`McStatus` from a parsed status JSON payload."""
    players = payload.get("players")
    players = players if isinstance(players, dict) else {}
    version = payload.get("version")
    version = version if isinstance(version, dict) else {}

    return McStatus(
        online=True,
        players_online=players.get("online"),
        players_max=players.get("max"),
        version=version.get("name"),
        motd=_extract_motd(payload.get("description")),
        latency_ms=latency_ms,
        error=None,
    )


def probe(host: str, port: int, timeout: float = 3.0) -> McStatus:
    """Probe a Minecraft Java Edition server with a Server List Ping.

    Performs the handshake + status request/response exchange defined
    by the Java Edition protocol. Never raises: any connection, timeout,
    protocol, or JSON error is captured in the returned
    :class:`McStatus`.

    Args:
        host: The server hostname or IP address.
        port: The server port.
        timeout: Socket connect/read timeout in seconds.

    Returns:
        An :class:`McStatus` describing the outcome. ``online`` is
        ``False`` and ``error`` is set on any failure.
    """
    start = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(_build_handshake(host, port))
            sock.sendall(_build_status_request())

            packet_length = decode_varint(sock)
            if packet_length <= 0 or packet_length > _MAX_PACKET_LENGTH:
                raise ValueError(
                    f"invalid Minecraft SLP response packet length: {packet_length}"
                )

            body = _BufferReader(_recv_exact(sock, packet_length))
            _packet_id = decode_varint(body)
            json_length = decode_varint(body)
            json_bytes = _recv_exact(body, json_length)

        latency_ms = (time.perf_counter() - start) * 1000
        payload = json.loads(json_bytes.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Minecraft SLP response JSON is not an object")
        return _status_from_payload(payload, latency_ms)
    except (OSError, ValueError, ConnectionError, UnicodeDecodeError) as exc:
        log.debug("Minecraft SLP probe to %s:%d failed: %s", host, port, exc)
        return McStatus(
            online=False,
            players_online=None,
            players_max=None,
            version=None,
            motd=None,
            latency_ms=None,
            error=str(exc),
        )

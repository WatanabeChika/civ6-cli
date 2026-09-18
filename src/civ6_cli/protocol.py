"""FireTuner packet framing.

The transport deliberately knows nothing about Lua or game actions. Civ VI's
observed command channel uses a little-endian length-prefixed body, with a
little-endian message type followed by a NUL-terminated payload.
"""

from __future__ import annotations

from dataclasses import dataclass
import struct


class ProtocolError(ValueError):
    """Raised when a packet cannot be safely decoded."""


@dataclass(frozen=True)
class FireTunerPacket:
    message_type: int
    payload: bytes

    def encode(self) -> bytes:
        # Nexus protocol header: [payload length][signed tag]. The tag is
        # not part of the length (an earlier Phase-1 draft got this wrong).
        return struct.pack("<Ii", len(self.payload), self.message_type) + self.payload

    @classmethod
    def decode(cls, header: bytes, payload: bytes) -> "FireTunerPacket":
        if len(header) != 8:
            raise ProtocolError("packet header must be exactly 8 bytes")
        length, message_type = struct.unpack("<Ii", header)
        if length != len(payload):
            raise ProtocolError("packet payload length does not match header")
        return cls(message_type, payload)


def encode_command(lua: str, *, command_id: int = 65535, message_type: int = 3) -> bytes:
    if "\x00" in lua:
        raise ProtocolError("Lua command must not contain NUL")
    payload = f"CMD:{command_id}:{lua}\x00".encode("utf-8")
    return FireTunerPacket(message_type, payload).encode()


def clean_response(payload: bytes) -> str:
    """Decode a response payload without interpreting its contents."""
    data = payload.rstrip(b"\x00")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        # Civ VI's Windows localization layer can emit the active ANSI code
        # page (GBK on this workstation) even though protocol commands are
        # UTF-8. ``mbcs`` maps to that Windows code page.
        return data.decode("mbcs", errors="replace")

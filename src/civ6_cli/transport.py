"""Persistent TCP transport for the Civ VI FireTuner command channel."""

from __future__ import annotations

import socket
import struct
import time
from typing import Optional

from .protocol import FireTunerPacket, clean_response, encode_command, ProtocolError


class FireTunerError(ConnectionError):
    """Base class for connection and framing failures."""


class FireTunerConnection:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 4318,
        *,
        timeout: float = 5.0,
        max_packet_size: int = 16 * 1024 * 1024,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.max_packet_size = max_packet_size
        self._sock: Optional[socket.socket] = None
        self.app_identity: Optional[str] = None
        self.lua_states: dict[str, int] = {}
        self._request_seq = 0

    @property
    def connected(self) -> bool:
        return self._sock is not None

    def connect(self) -> None:
        self.close()
        try:
            self._sock = socket.create_connection((self.host, self.port), self.timeout)
            self._sock.settimeout(self.timeout)
            self._handshake()
        except (OSError, ProtocolError) as exc:
            self.close()
            raise FireTunerError(f"unable to connect to {self.host}:{self.port}: {exc}") from exc

    def close(self) -> None:
        sock, self._sock = self._sock, None
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()

    def __enter__(self) -> "FireTunerConnection":
        self.connect()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _recv_exact(self, size: int) -> bytes:
        if self._sock is None:
            raise FireTunerError("not connected")
        if size < 0 or size > self.max_packet_size:
            raise ProtocolError(f"invalid packet size: {size}")
        chunks: list[bytes] = []
        remaining = size
        try:
            while remaining:
                chunk = self._sock.recv(remaining)
                if not chunk:
                    raise FireTunerError("FireTuner closed the connection")
                chunks.append(chunk)
                remaining -= len(chunk)
        except socket.timeout as exc:
            raise FireTunerError("timed out waiting for FireTuner response") from exc
        except OSError as exc:
            raise FireTunerError(f"read failed: {exc}") from exc
        return b"".join(chunks)

    def _recv_packet(self) -> FireTunerPacket:
        header = self._recv_exact(8)
        length, _ = struct.unpack("<Ii", header)
        if length < 0 or length > self.max_packet_size:
            raise ProtocolError(f"invalid packet payload size: {length}")
        return FireTunerPacket.decode(header, self._recv_exact(length))

    def _send_packet(self, message_type: int, payload: str) -> FireTunerPacket:
        if self._sock is None:
            raise FireTunerError("not connected")
        if "\x00" in payload:
            raise ProtocolError("packet payload must not contain NUL")
        try:
            self._sock.sendall(FireTunerPacket(message_type, payload.encode("utf-8") + b"\x00").encode())
            return self._recv_packet()
        except OSError as exc:
            self.close()
            raise FireTunerError(f"FireTuner I/O failed: {exc}") from exc

    def _send_only(self, message_type: int, payload: str) -> None:
        if self._sock is None:
            raise FireTunerError("not connected")
        if "\x00" in payload:
            raise ProtocolError("packet payload must not contain NUL")
        try:
            self._sock.sendall(FireTunerPacket(message_type, payload.encode("utf-8") + b"\x00").encode())
        except OSError as exc:
            self.close()
            raise FireTunerError(f"FireTuner write failed: {exc}") from exc

    def _handshake(self) -> None:
        app = self._send_packet(4, "APP:")
        self.app_identity = clean_response(app.payload)
        states = self._send_packet(4, "LSQ:")
        raw_states = clean_response(states.payload)
        tokens = [token.strip() for token in raw_states.split("\x00") if token.strip()]
        if len(tokens) <= 1:
            tokens = [token.strip() for token in clean_response(states.payload).splitlines() if token.strip()]
        parsed: dict[str, int] = {}
        for index in range(0, len(tokens) - 1, 2):
            try:
                parsed[tokens[index + 1]] = int(tokens[index])
            except ValueError:
                continue
        self.lua_states = parsed

    def send_lua(self, state_index: int, lua: str) -> str:
        """Send one Lua command and return the raw decoded response."""
        if self._sock is None:
            raise FireTunerError("not connected")
        try:
            response = self._send_packet(3, f"CMD:{state_index}:{lua}")
        except OSError as exc:
            self.close()
            raise FireTunerError(f"write failed: {exc}") from exc
        return clean_response(response.payload)

    def execute_read_lines(self, lua: str, *, context: str = "GameCore_Tuner", timeout: float | None = None) -> list[str]:
        """Run a fixed read-only query and collect its explicit print output."""
        return self._execute_lines(lua, context=context, timeout=timeout)

    def execute_action_lines(self, lua: str, *, context: str = "InGame", timeout: float | None = None) -> list[str]:
        """Run one fixed action once; callers must never replay on failure."""
        return self._execute_lines(lua, context=context, timeout=timeout)

    def _execute_lines(self, lua: str, *, context: str, timeout: float | None) -> list[str]:
        """Collect explicitly framed print output from one Lua command.

        FireTuner acknowledges a command before Lua's print messages arrive, so
        a normal request/response call is insufficient.  The generated
        sentinel is the only completion signal accepted by this method.
        """
        state = self.lua_states.get(context)
        if state is None:
            raise FireTunerError(f"{context} was not advertised by FireTuner")
        self._request_seq += 1
        sentinel = f"__CIV6CLI_END_{self._request_seq}__"
        row_prefix = f"__CIV6CLI_ROW_{self._request_seq}__"
        deadline = time.monotonic() + (timeout if timeout is not None else self.timeout)
        # A Lua runtime error used to prevent the sentinel from running, which
        # was indistinguishable from a network timeout.  Isolate every fixed
        # fixed template so a version/DLC-specific missing API returns a
        # printable diagnostic while the connection remains usable.
        wrapped_lua = (
            "local __civ6cli_raw_print = print\n"
            + "local __civ6cli_row_id = 0\n"
            + "local function __civ6cli_hex(value)\n"
            + "  local raw, result = value, {}\n"
            + "  if type(raw) ~= 'string' then raw = tostring(raw) end\n"
            + "  for index = 1, string.len(raw) do result[index] = string.format('%02X', string.byte(raw, index)) end\n"
            + "  return table.concat(result)\n"
            + "end\n"
            + "local function print(value)\n"
            + "  __civ6cli_row_id = __civ6cli_row_id + 1\n"
            + "  local encoded = __civ6cli_hex(value)\n"
            # FireTuner truncates long individual print events. Keep the
            # encoded wire fragment comfortably below the smallest observed
            # event buffer once protocol/context prefixes are included.
            + "  local chunk_size = 48\n"
            + "  local total = math.max(1, math.ceil(string.len(encoded) / chunk_size))\n"
            + "  for part = 1, total do\n"
            + f"    __civ6cli_raw_print('{row_prefix}H|' .. __civ6cli_row_id .. '|' .. part .. '|' .. total .. '|' .. string.sub(encoded, (part-1)*chunk_size+1, part*chunk_size))\n"
            + "  end\n"
            + "end\n"
            + "local __civ6cli_ok, __civ6cli_err = xpcall(function()\n"
            + lua
            + "\nend, function(err) return tostring(err) end)\n"
            + "if not __civ6cli_ok then print('ERROR|' .. tostring(__civ6cli_err):gsub('|', '/'):gsub('\\n', ' ')) end\n"
            + f"__civ6cli_raw_print('{sentinel}')"
        )
        self._send_only(3, f"CMD:{state}:{wrapped_lua}")
        previous_timeout = self._sock.gettimeout() if self._sock else self.timeout
        if self._sock is not None and timeout is not None:
            self._sock.settimeout(timeout)
        lines: list[str] = []
        chunks: dict[int, tuple[int, dict[int, str]]] = {}
        output_size = 0
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise FireTunerError("timed out collecting Lua query output")
                if self._sock is not None:
                    self._sock.settimeout(remaining)
                packet = self._recv_packet()
                raw = clean_response(packet.payload)
                text = self._parse_output(raw)
                if text is None:
                    continue  # command acknowledgement or another tuner event
                if text == sentinel:
                    if chunks:
                        self.close()
                        raise FireTunerError("FireTuner ended the query with an incomplete output record")
                    return lines
                # A previous query's delayed sentinel is not query data.
                if text.startswith("__CIV6CLI_END_"):
                    continue
                # Civ VI UI contexts write unrelated diagnostic messages to
                # the same FireTuner output stream.  Only the locally wrapped
                # print calls belonging to this request are query records.
                if not text.startswith(row_prefix):
                    continue
                text = text[len(row_prefix):]
                if not text.startswith("H|"):
                    continue
                try:
                    _, row_text, part_text, total_text, encoded = text.split("|", 4)
                    row_id, part, total = int(row_text), int(part_text), int(total_text)
                    if row_id < 1 or part < 1 or total < 1 or part > total or len(encoded) % 2:
                        raise ValueError
                    bytes.fromhex(encoded)  # validate every chunk before retaining it
                except ValueError as exc:
                    self.close()
                    raise FireTunerError("received a malformed encoded Lua output chunk") from exc
                expected, parts = chunks.setdefault(row_id, (total, {}))
                if expected != total or part in parts:
                    self.close()
                    raise FireTunerError("received inconsistent encoded Lua output chunks")
                parts[part] = encoded
                if len(parts) < total:
                    continue
                try:
                    row_bytes = bytes.fromhex("".join(parts[index] for index in range(1, total + 1)))
                    text = row_bytes.decode("utf-8")
                except (KeyError, ValueError, UnicodeDecodeError) as exc:
                    self.close()
                    if isinstance(exc, UnicodeDecodeError):
                        fragment = row_bytes[max(0, exc.start-8):exc.start+8].hex().upper()
                        detail = f" (row {row_id}, byte {exc.start}, bytes {fragment})"
                    else:
                        detail = ""
                    raise FireTunerError("could not decode the complete Lua output record" + detail) from exc
                del chunks[row_id]
                output_size += len(text.encode('utf-8'))
                if output_size > self.max_packet_size:
                    raise FireTunerError("Lua query output exceeded the response size limit")
                lines.append(text)
        except (OSError, ProtocolError) as exc:
            # Continuing after a partial response could mix two snapshots.
            self.close()
            raise FireTunerError(f"could not collect Lua output: {exc}") from exc
        finally:
            if self._sock is not None:
                self._sock.settimeout(previous_timeout)

    @staticmethod
    def _parse_output(payload: str) -> str | None:
        if not payload.startswith("O"):
            return None
        separator = payload.find(": ", 2)
        if separator >= 0:
            return payload[separator + 2 :]
        return payload.lstrip("O").lstrip("\x00").strip()

    def probe(self) -> str:
        """Run a side-effect-free Lua expression used by Phase 1."""
        lines = self.execute_read_lines("print(tostring(Game.GetCurrentGameTurn()))")
        if len(lines) != 1:
            raise FireTunerError(f"unexpected turn query output: {lines!r}")
        return lines[0]

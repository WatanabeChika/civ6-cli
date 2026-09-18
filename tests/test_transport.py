import socket
import struct
import threading
import unittest

from civ6_cli.protocol import FireTunerPacket
from civ6_cli.transport import FireTunerConnection, FireTunerError


class FakeFireTuner(unittest.TestCase):
    def pair(self, *, max_packet_size=16*1024*1024):
        client, server = socket.socketpair()
        self.addCleanup(client.close)
        self.addCleanup(server.close)
        client.settimeout(0.1)
        connection = FireTunerConnection(timeout=0.1, max_packet_size=max_packet_size)
        connection._sock = client
        connection.lua_states = {'GameCore_Tuner': 4}
        return connection, server

    @staticmethod
    def output(server, text):
        server.sendall(FireTunerPacket(1, ('O4: ' + text + '\x00').encode('utf-8')).encode())

    def row(self, server, request, text):
        encoded = text.encode('utf-8').hex().upper()
        chunks = [encoded[index:index+240] for index in range(0, len(encoded), 240)] or ['']
        for part, chunk in enumerate(chunks, 1):
            self.output(server, f'__CIV6CLI_ROW_{request}__H|1|{part}|{len(chunks)}|{chunk}')

    def test_read_lines_uses_sentinel_not_acknowledgement(self):
        connection, server = self.pair()
        server.sendall(FireTunerPacket(3, b'ACK\x00').encode())
        self.output(server, 'ViewUnitsPage')
        self.row(server, 1, 'CITY|65536|开罗')
        self.output(server, 'Timer1: UpdateUnitsData 14      milisecs')
        self.output(server, '__CIV6CLI_END_1__')
        self.assertEqual(connection.execute_read_lines('print(1)'), ['CITY|65536|开罗'])

    def test_lua_error_is_returned_and_connection_remains_usable(self):
        connection, server = self.pair()
        self.row(server, 1, 'ERROR|missing API')
        self.output(server, '__CIV6CLI_END_1__')
        encoded = 'STATUS|96'.encode().hex().upper()
        self.output(server, f'__CIV6CLI_ROW_2__H|1|1|1|{encoded}')
        self.output(server, '__CIV6CLI_END_2__')
        self.assertEqual(connection.execute_read_lines('print(1)'), ['ERROR|missing API'])
        self.assertEqual(connection.execute_read_lines('print(2)'), ['STATUS|96'])
        self.assertTrue(connection.connected)

    def test_stale_sentinel_cannot_complete_next_query(self):
        connection, server = self.pair()
        self.output(server, '__CIV6CLI_END_0__')
        self.row(server, 1, 'fresh')
        self.output(server, '__CIV6CLI_END_1__')
        self.assertEqual(connection.execute_read_lines('print(1)'), ['fresh'])

    def test_timeout_closes_partial_response_connection(self):
        connection, _ = self.pair()
        with self.assertRaises(FireTunerError):
            connection.execute_read_lines('print(1)', timeout=0.02)
        self.assertFalse(connection.connected)

    def test_aggregate_output_has_size_limit(self):
        connection, server = self.pair(max_packet_size=160)
        first = ('a'*50).encode().hex().upper()
        second = ('b'*50).encode().hex().upper()
        third = ('c'*50).encode().hex().upper()
        fourth = ('d'*50).encode().hex().upper()
        self.output(server, f'__CIV6CLI_ROW_1__H|1|1|1|{first}')
        self.output(server, f'__CIV6CLI_ROW_1__H|2|1|1|{second}')
        self.output(server, f'__CIV6CLI_ROW_1__H|3|1|1|{third}')
        self.output(server, f'__CIV6CLI_ROW_1__H|4|1|1|{fourth}')
        with self.assertRaisesRegex(FireTunerError, 'size limit'):
            connection.execute_read_lines('print(1)')
        self.assertFalse(connection.connected)

    def test_missing_context_fails_before_sending(self):
        connection, _ = self.pair()
        with self.assertRaisesRegex(FireTunerError, 'not advertised'):
            connection.execute_read_lines('print(1)', context='Unavailable')

    def test_query_is_wrapped_to_preserve_errors_and_completion(self):
        connection, server = self.pair()
        self.output(server, '__CIV6CLI_END_1__')
        connection.execute_read_lines('print(1)')
        header = self._recv_exact(server, 8)
        length, _ = struct.unpack('<Ii', header)
        command = self._recv_exact(server, length).decode('utf-8')
        self.assertIn('xpcall', command)
        self.assertIn('ERROR|', command)
        self.assertIn('__CIV6CLI_ROW_1__', command)
        self.assertIn('__civ6cli_raw_print', command)
        self.assertIn('__civ6cli_hex', command)
        self.assertIn('__CIV6CLI_END_1__', command)

    def test_long_multibyte_record_is_reassembled_without_mojibake(self):
        connection, server = self.pair()
        text = 'PRODUCTION_UNIT|name=射石炮|effect=' + '长说明。' * 100
        encoded = text.encode('utf-8').hex().upper()
        chunks = [encoded[index:index+240] for index in range(0, len(encoded), 240)]
        for part, chunk in enumerate(chunks, 1):
            self.output(server, f'__CIV6CLI_ROW_1__H|1|{part}|{len(chunks)}|{chunk}')
        self.output(server, '__CIV6CLI_END_1__')
        self.assertEqual(connection.execute_read_lines('print(1)'), [text])

    def test_incomplete_record_is_rejected(self):
        connection, server = self.pair()
        self.output(server, '__CIV6CLI_ROW_1__H|1|1|2|E5B084')
        self.output(server, '__CIV6CLI_END_1__')
        with self.assertRaisesRegex(FireTunerError, 'incomplete output record'):
            connection.execute_read_lines('print(1)')
        self.assertFalse(connection.connected)

    def test_send_lua_handles_fragmented_response(self):
        ready = threading.Event()

        def server() -> None:
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                listener.listen(1)
                self.port = listener.getsockname()[1]
                ready.set()
                conn, _ = listener.accept()
                with conn:
                    header = self._recv_exact(conn, 8)
                    (length, _) = struct.unpack("<Ii", header)
                    body = self._recv_exact(conn, length)
                    request = FireTunerPacket.decode(header, body)
                    self.assertEqual(request.message_type, 3)
                    self.assertTrue(request.payload.startswith(b"CMD:4:return 1"))
                    reply = FireTunerPacket(3, b"1\x00").encode()
                    conn.sendall(reply[:2])
                    conn.sendall(reply[2:])

        thread = threading.Thread(target=server, daemon=True)
        thread.start()
        ready.wait(2)
        # This fake server covers only one command, so bypass the connect
        # handshake for this framing test.
        connection = FireTunerConnection(port=self.port)
        connection._sock = socket.create_connection(("127.0.0.1", self.port))
        self.assertEqual(connection.send_lua(4, "return 1"), "1")
        connection.close()
        thread.join(2)

    @staticmethod
    def _recv_exact(conn: socket.socket, size: int) -> bytes:
        data = b""
        while len(data) < size:
            data += conn.recv(size - len(data))
        return data


if __name__ == "__main__":
    unittest.main()

import struct
import unittest

from civ6_cli.protocol import FireTunerPacket, ProtocolError, clean_response, encode_command


class ProtocolTests(unittest.TestCase):
    def test_command_frame(self):
        frame = encode_command("return 1")
        (length,) = struct.unpack("<I", frame[:4])
        self.assertEqual(length, len(frame) - 8)
        packet = FireTunerPacket.decode(frame[:8], frame[8:])
        self.assertEqual(packet.message_type, 3)
        self.assertEqual(packet.payload, b"CMD:65535:return 1\x00")

    def test_decode_rejects_short_body(self):
        with self.assertRaises(ProtocolError):
            FireTunerPacket.decode(b"\x01\x02", b"")

    def test_response_nul(self):
        self.assertEqual(clean_response(b"ok\x00"), "ok")


if __name__ == "__main__":
    unittest.main()

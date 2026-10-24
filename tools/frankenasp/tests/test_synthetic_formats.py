"""Public synthetic-only protocol regression tests; no factory payload required."""
import struct
import unittest


def clamp24(v):
    return max(-(1 << 23), min((1 << 23) - 1, v))


def pack_six(mics, stereo, cal=(1 << 30,) * 4):
    assert len(mics) == 4 and len(stereo) == 2
    packed = [clamp24(((sample >> 8) * gain) >> 30)
              for sample, gain in zip(mics, cal)]
    packed += [value << 16 for value in stereo]
    return struct.pack("<6i", *packed)


class ProtocolTests(unittest.TestCase):
    def test_quantum_lengths(self):
        self.assertEqual(768 * 6 * 4, 18432)
        self.assertEqual(128 * 2, 256)
        self.assertEqual(768 / 96000, 0.008)
        self.assertEqual(128 / 16000, 0.008)

    def test_stereo_reference_is_not_mono(self):
        data = pack_six([0] * 4, [32767, -32768])
        self.assertEqual(struct.unpack("<6i", data)[4:], (2147418112, -2147483648))

    def test_q30_unity_and_clamping(self):
        data = pack_six([0x40000000, -0x40000000, 0, 0], [0, 0])
        self.assertEqual(struct.unpack("<6i", data)[:2],
                         (0x400000, -0x400000))
        doubled = pack_six([0x7fffff00] * 4, [0, 0], (2 << 30,) * 4)
        self.assertEqual(struct.unpack("<6i", doubled)[:4], ((1 << 23) - 1,) * 4)


if __name__ == "__main__":
    unittest.main()

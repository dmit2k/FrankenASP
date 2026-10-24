#!/usr/bin/env python3
"""Read-only statistics of already captured Athena 4-mic + 2-AWB PCM.

No DSP execution, no audio playback and no PCM modifications. Uses only stdlib.
Never publishes raw audio, file paths, utterances or unit calibration values.
"""
import argparse
import json
import math
import struct
from pathlib import Path

MIC_CHANNELS, REF_CHANNELS, RATE = 4, 2, 96000
MIC_FORMAT = "<4i"
REF_FORMAT = "<2h"
CHUNK_FRAMES = 4096


class ChannelStats:
    def __init__(self, bit_depth, alignment_bits=0):
        self.bits = bit_depth
        self.shift = alignment_bits
        self.n = self.nonzero = self.clipped = self.aligned = 0
        self.peak = self.total = self.squared = 0

    def add(self, word):
        self.n += 1
        self.aligned += (word & ((1 << self.shift) - 1)) == 0
        value = word >> self.shift
        self.nonzero += value != 0
        self.clipped += value <= -(1 << (self.bits - 1)) or value >= (1 << (self.bits - 1)) - 1
        self.peak = max(self.peak, abs(value))
        self.total += value
        self.squared += value * value

    def summary(self):
        if not self.n:
            raise ValueError("no PCM samples")
        fs = 1 << (self.bits - 1)
        rms = math.sqrt(self.squared / self.n) / fs
        peak = self.peak / fs
        db = lambda x: round(20 * math.log10(x), 3) if x > 0 else None
        return {
            "samples": self.n,
            "rms_dbfs": db(rms),
            "peak_dbfs": db(peak),
            "mean_normalized": round(self.total / self.n / fs, 8),
            "nonzero_fraction": round(self.nonzero / self.n, 7),
            "clipped_fraction": round(self.clipped / self.n, 8),
            "aligned_fraction": round(self.aligned / self.n, 7),
        }


def inspect_pcm(path, channels, fmt, bit_depth, alignment_bits):
    frame_bytes = struct.calcsize(fmt)
    size = path.stat().st_size
    if size == 0 or size % frame_bytes:
        raise ValueError("empty PCM or partial interleaved frame: " + path.name)
    stats = [ChannelStats(bit_depth, alignment_bits) for _ in range(channels)]
    with path.open("rb") as fd:
        while True:
            block = fd.read(CHUNK_FRAMES * frame_bytes)
            if not block:
                break
            for frame in struct.iter_unpack(fmt, block):
                for j, value in enumerate(frame):
                    stats[j].add(value)
    return size // frame_bytes, [s.summary() for s in stats]


def inspect_capture(mics, ref, meta=None):
    mic_frames, mic_stats = inspect_pcm(mics, MIC_CHANNELS, MIC_FORMAT, 24, 8)
    ref_frames, ref_stats = inspect_pcm(ref, REF_CHANNELS, REF_FORMAT, 16, 0)
    problems = []
    if mic_frames != ref_frames:
        problems.append("microphone and AWB frame counts differ")
    metadata = {}
    if meta is not None:
        record = json.loads(meta.read_text())
        if record.get("reference_source") != "hardware_awb":
            problems.append("metadata does not identify hardware AWB reference")
        for key, expected in (("mic_channels", 4), ("ref_channels", 2),
                              ("mic_rate", RATE), ("ref_rate", RATE)):
            if record.get(key) != expected:
                problems.append("capture metadata " + key + " mismatch")
        if record.get("dropped_frames16", 0) != 0:
            problems.append("capture metadata reports dropped frames")
        if record.get("written_frames16") is not None and mic_frames != 6 * record["written_frames16"]:
            problems.append("PCM length does not match capture metadata")
        metadata = {
            "reference_source": record.get("reference_source"),
            "reported_dropped_frames16": record.get("dropped_frames16"),
            "reported_reference_valid_frames16": record.get("reference_valid_frames16"),
        }
    warnings = []
    has_reference_samples = any(ch["nonzero_fraction"] > 0 for ch in ref_stats)
    if not has_reference_samples:
        warnings.append("AWB frames were received but all PCM samples are zero; cannot assess AEC")
    # A full-scale reference does not certify correct acoustic synchronization.
    for ch, value in enumerate(mic_stats):
        if value["aligned_fraction"] < .9999:
            problems.append("microphone ch%d does not match 24-bit left-aligned format" % ch)
    return {
        "source": "read_only_existing_capture",
        "mic_frames96k": mic_frames,
        "ref_frames96k": ref_frames,
        "duration_seconds": round(min(mic_frames, ref_frames) / RATE, 6),
        "microphones": mic_stats,
        "awb_stereo": ref_stats,
        "awb_signal_present": has_reference_samples,
        "warnings": warnings,
        "capture_metadata": metadata,
        "problems": problems,
        "assessment": "input_format_preflight_pass" if not problems else "needs_manual_review",
        "not_evaluated": [
            "microphone_to_awb_start_offset_or_echo_path_delay",
            "absolute_calibration_or_double_calibration",
            "physical_mic_array_channel_order",
            "aec_quality_or_speech_intelligibility",
        ],
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mics", required=True, type=Path, help="existing four-channel 96 kHz S32_LE file")
    p.add_argument("--ref", required=True, type=Path, help="existing stereo 96 kHz S16_LE hardware AWB")
    p.add_argument("--capture-json", type=Path, help="existing capture.json, optional")
    a = p.parse_args()
    try:
        result = inspect_capture(a.mics, a.ref, a.capture_json)
    except (OSError, ValueError, KeyError, TypeError) as e:
        p.error(str(e))
    print(json.dumps(result, indent=2, sort_keys=True))
    if result["problems"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()

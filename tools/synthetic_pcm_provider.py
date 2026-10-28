#!/usr/bin/env python3
"""Offline synthetic protocol-v1 provider. Never opens capture or a device."""
import argparse
import math
import os
import socket
import struct
import time

HEADER = struct.Struct("<4sHHIHHHHQQQQQI")
SAMPLES = 320
RATE = 16000

def packet(generation, sequence, stamp):
    header = HEADER.pack(b"EPCS", 1, 64, RATE, 1, 1, SAMPLES, 0,
                         generation, sequence, sequence * SAMPLES, stamp, 0, 0)
    pcm = [int(1200 * math.sin(2 * math.pi * 440 * (sequence * SAMPLES + n) / RATE))
           for n in range(SAMPLES)]
    return header + struct.pack("<320h", *pcm)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", required=True, help="Explicit offline harness socket")
    parser.add_argument("--duration", type=float, default=1.0)
    parser.add_argument("--generation", type=int)
    parser.add_argument("--fault", choices=["none", "short", "oversize", "duplicate", "gap",
                                          "stale", "future", "stall", "crash", "overflow"],
                        default="none")
    args = parser.parse_args()
    if not 0 < args.duration <= 60:
        parser.error("duration must be in (0, 60]")
    generation = args.generation or time.monotonic_ns()
    with socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) as conn:
        conn.connect(args.socket)
        start = time.monotonic_ns()
        count = max(1, int(args.duration * 50))
        try:
            for seq in range(count):
                due = start + seq * 20_000_000
                wait = (due - time.monotonic_ns()) / 1e9
                if wait > 0:
                    time.sleep(wait)
                if seq == 5 and args.fault in ("stall", "crash"):
                    if args.fault == "stall":
                        time.sleep(0.2)
                        break
                    os._exit(17)
                chosen = seq
                stamp = due
                if seq == 5:
                    if args.fault == "duplicate":
                        chosen -= 1
                        stamp -= 20_000_000
                    elif args.fault == "gap":
                        chosen += 1
                    elif args.fault == "stale":
                        stamp -= 200_000_000
                    elif args.fault == "future":
                        stamp += 200_000_000
                data = packet(generation, chosen, stamp)
                if seq == 5:
                    if args.fault == "short":
                        data = data[:-1]
                    elif args.fault == "oversize":
                        data += b"X"
                    elif args.fault == "overflow":
                        # Deliberately repeats: malformed ordering is independently rejected.
                        for _ in range(8):
                            conn.send(data)
                conn.send(data)
        except (BrokenPipeError, ConnectionResetError):
            if args.fault == "none":
                raise
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

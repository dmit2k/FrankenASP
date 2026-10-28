"""Bounded Android v4 Brotli streams and selective requested-block caching."""
import importlib
from pathlib import Path

from installer_sources import Refusal, require

BLOCK = 4096
MAX_BLOCKS = 4 * 1024**3 // BLOCK


def transfer(raw):
    require(len(raw) <= 1024 * 1024, "oversized transfer.list")
    try:
        lines = raw.decode("ascii").splitlines()
        require(4 < len(lines) <= 65540 and lines[0] == "4", "only transfer.list v4 supported")
        total, stash_entries, stash_blocks = map(int, lines[1:4])
        require(0 < total <= MAX_BLOCKS and stash_entries == stash_blocks == 0,
                "incremental/stash transfer.list requires unsupported base")
        commands, targets = [], []
        counts = {"new": 0, "zero": 0, "erase": 0}
        new_ranges = []
        for line in lines[4:]:
            fields = line.split()
            require(len(fields) == 2 and fields[0] in counts,
                    "incremental/source-dependent or unknown transfer command refused")
            values = [int(v) for v in fields[1].split(",")]
            require(values and values[0] == len(values) - 1 and
                    0 < values[0] <= 131072 and values[0] % 2 == 0,
                    "malformed transfer range count")
            ranges = list(zip(values[1::2], values[2::2]))
            cursor = -1
            for start, end in ranges:
                require(0 <= start < end <= MAX_BLOCKS and start >= cursor,
                        "invalid/out-of-bound/unsorted transfer range")
                cursor = end
                counts[fields[0]] += end - start
            targets.extend(ranges)
            if fields[0] == "new":
                new_ranges.extend(ranges)
            commands.append(fields[0])
        require(len(targets) <= 131072 and counts["new"] > 0 and
                counts["new"] + counts["zero"] == total,
                "transfer declared block count disagrees with new/zero data")
        cursor = 0
        for start, end in sorted(targets):
            require(start == cursor, "full OTA targets overlap or leave source-dependent gaps")
            cursor = end
        require(cursor > 0, "empty full block image")
        return {"version": 4, "image_blocks": cursor, "image_bytes": cursor * BLOCK,
                "declared_write_blocks": total, "new_bytes": counts["new"] * BLOCK,
                "blocks_by_command": counts, "commands": len(commands),
                "new_ranges": new_ranges, "base_required": False}
    except (UnicodeError, ValueError) as e:
        raise Refusal("invalid/unsupported full transfer.list: " + str(e)) from e


def plans(archive):
    require(all(name in archive.namelist() for part in ("system", "vendor")
                for name in (part + ".transfer.list", part + ".new.dat.br")),
            "incomplete full block-transfer OTA: both components required")
    result = {}
    for part in ("system", "vendor"):
        info = archive.getinfo(part + ".transfer.list")
        require(0 < info.file_size <= 1024 * 1024, "invalid transfer.list size")
        patch = part + ".patch.dat"
        require(patch not in archive.namelist() or archive.getinfo(patch).file_size == 0,
                "incremental patch.dat is nonempty; unsupported base reconstruction")
        require(archive.getinfo(part + ".new.dat.br").file_size > 0,
                "missing compressed new-block data")
        result[part] = transfer(archive.read(info))
    return result


def summary(plan):
    return {k: v for k, v in plan.items() if k != "new_ranges"}


def stream(archive, part, plan, consume):
    """Consume the complete validated stream, without ever constructing an image."""
    import time
    try:
        brotli = importlib.import_module("brotli")
    except ImportError as e:
        raise Refusal("full .new.dat.br OTA requires existing Python brotli 1.2+; no automatic download") from e
    decoder = brotli.Decompressor()
    require(hasattr(decoder, "can_accept_more_data"), "Python brotli 1.2+ bounded streaming API required")
    ranges = plan["new_ranges"]
    index = offset = written = 0
    deadline = time.monotonic() + 600

    def accept(data):
        nonlocal index, offset, written
        require(time.monotonic() < deadline, "Brotli pass exceeded 600 second limit")
        require(written + len(data) <= plan["new_bytes"], "decoded new data exceeds transfer ranges")
        data = memoryview(data)
        while data:
            require(index < len(ranges), "unexpected decoded block data")
            start, end = ranges[index]
            amount = min((end - start) * BLOCK - offset, len(data))
            consume(start * BLOCK + offset, data[:amount])
            offset += amount
            written += amount
            data = data[amount:]
            if offset == (end - start) * BLOCK:
                index += 1
                offset = 0
    try:
        with archive.open(part + ".new.dat.br") as source:
            while True:
                raw = source.read(64 * 1024)
                if not raw:
                    break
                accept(decoder.process(raw, output_buffer_limit=1024 * 1024))
                while not decoder.can_accept_more_data():
                    accept(decoder.process(b"", output_buffer_limit=1024 * 1024))
            while not decoder.is_finished():
                data = decoder.process(b"", output_buffer_limit=1024 * 1024)
                if not data:
                    break
                accept(data)
    except brotli.error as e:
        raise Refusal("damaged Brotli new-block stream: " + part) from e
    require(decoder.is_finished() and written == plan["new_bytes"] and index == len(ranges) and offset == 0,
            "truncated/incomplete Brotli new-block stream: " + part)


def reconstruct(archive, part, output, plan):
    """Historical test/reference utility; production prepare NEVER calls this."""
    with Path(output).open("xb") as dest:
        dest.truncate(plan["image_bytes"])
        def consume(offset, data):
            dest.seek(offset)
            require(dest.write(data) == len(data), "short reconstructed image write")
        stream(archive, part, plan, consume)
    return summary(plan)


class SelectiveBlocks:
    """In-memory requested-block cache; not a sparse or complete partition image."""
    MAX_CACHE = 96 * 1024**2
    MAX_PASSES = 64

    def __init__(self, archive, part, plan):
        self.archive, self.part, self.plan = archive, part, plan
        self.size = plan["image_bytes"]
        self.cache, self.pending = {}, set()
        self.passes = self.peak_bytes = self.decoded_bytes = 0

    def read_at(self, offset, size):
        from installer_ext4 import NeedBlocks
        require(0 <= offset <= self.size and 0 <= size <= 64 * 1024**2 and offset + size <= self.size,
                "selective ext4 read outside image/bound")
        ids = range(offset // BLOCK, (offset + size + BLOCK - 1) // BLOCK)
        absent = set(ids) - self.cache.keys()
        if absent:
            self.pending.update(absent)
            require((len(self.cache) + len(self.pending)) * BLOCK <= self.MAX_CACHE,
                    "selective ext4 block cache exceeds 96MiB per partition")
            raise NeedBlocks()
        data = b"".join(self.cache[i] for i in ids)
        start = offset % BLOCK
        return data[start:start + size]

    def fill(self):
        import bisect
        require(self.pending and self.passes < self.MAX_PASSES, "selective OTA pass limit exceeded")
        ids = sorted(self.pending)
        # Zero/erase targets remain zero. A full stream still validates exact EOF/CRC.
        buffers = {i: bytearray(BLOCK) for i in ids}
        def consume(offset, data):
            end = offset + len(data)
            at = bisect.bisect_left(ids, offset // BLOCK)
            while at < len(ids) and ids[at] * BLOCK < end:
                block_id = ids[at]
                lo, hi = max(offset, block_id * BLOCK), min(end, (block_id + 1) * BLOCK)
                if lo < hi:
                    buffers[block_id][lo - block_id * BLOCK:hi - block_id * BLOCK] = data[lo - offset:hi - offset]
                at += 1
        stream(self.archive, self.part, self.plan, consume)
        self.cache.update((i, bytes(data)) for i, data in buffers.items())
        self.pending.clear()
        self.passes += 1
        self.decoded_bytes += self.plan["new_bytes"]
        self.peak_bytes = max(self.peak_bytes, len(self.cache) * BLOCK)

    def metrics(self):
        return dict(summary(self.plan), selective=True, complete_image_created=False,
                    passes=self.passes, retained_block_bytes=self.peak_bytes,
                    decompressed_bytes=self.decoded_bytes, temporary_image_bytes=0)

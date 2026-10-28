"""Portable bounded read-only ext4 subset. No debugfs, mounts or image hashing."""
import struct
import time
from pathlib import Path

from installer_sources import LIMIT, MissingSource, relative, require

MAX_IMAGE = 4 * 1024**3


class NeedBlocks(Exception):
    """A selective source will satisfy these requests in the next streaming pass."""


class Raw:
    def __init__(self, path):
        self.path = Path(path)
        require(self.path.is_file() and not self.path.is_symlink(), "image missing or symlink: " + str(path))
        self.size = self.path.stat().st_size

    def read_at(self, offset, size):
        with self.path.open("rb") as f:
            f.seek(offset)
            data = f.read(size)
        require(len(data) == size, "truncated raw ext4 image")
        return data


class ZipRaw:
    def __init__(self, archive, member):
        self.archive, self.member = archive, member
        self.size = archive.getinfo(member).file_size
        require(0 < self.size <= MAX_IMAGE, "raw ZIP image exceeds 4GiB bound")
        # Preserve ZIP CRC integrity without writing an intermediate image or
        # calculating a source hash. Direct raw backups never take this path.
        deadline, count = time.monotonic() + 600, 0
        with archive.open(member) as stream:
            while True:
                raw = stream.read(1024 * 1024)
                if not raw:
                    break
                count += len(raw)
                require(count <= self.size and time.monotonic() < deadline,
                        "raw ZIP integrity read exceeds size/time bound")
        require(count == self.size, "truncated raw ZIP image")

    def read_at(self, offset, size):
        with self.archive.open(self.member) as f:
            f.seek(offset)
            data = f.read(size)
        require(len(data) == size, "truncated OTA ext4 member")
        return data


class Ext4:
    def __init__(self, path, prefix, source=None, label=None):
        self.source = source if source is not None else Raw(path)
        self.prefix = prefix
        self.label = label or str(path)
        self.sb = None
        if isinstance(self.source, Raw):
            self.init()

    def init(self):
        if self.sb is not None:
            return
        s = self.source.read_at(1024, 1024)
        u32 = lambda off: struct.unpack_from("<I", s, off)[0]
        require(s[56:58] == b"\x53\xef", "only raw ext4 images supported (not sparse/EROFS)")
        log = u32(24)
        require(log <= 6, "unsupported ext4 block size")
        bs = 1024 << log
        compat, incompat, ro = u32(92), u32(96), u32(100)
        # FILETYPE, EXTENTS, 64BIT, FLEX_BG. Recovery, meta_bg, inline,
        # encryption, compression, casefold and other unimplemented layouts refuse.
        require(incompat & ~0x2c2 == 0 and ro & ~0x47f == 0,
                "unsupported ext4 feature flags: incompat=%x ro=%x" % (incompat, ro))
        blocks = u32(4) | (u32(336) << 32 if incompat & 0x80 else 0)
        first, bpg, ipg, inodes = u32(20), u32(32), u32(40), u32(0)
        isize = struct.unpack_from("<H", s, 88)[0] if u32(76) else 128
        dsize = struct.unpack_from("<H", s, 254)[0] if incompat & 0x80 else 32
        require(0 < blocks * bs <= min(MAX_IMAGE, self.source.size) and
                first == (1 if bs == 1024 else 0) and 0 < bpg <= bs * 8 and
                0 < ipg <= bs * 8 and 128 <= isize <= bs and isize % 4 == 0 and
                32 <= dsize <= bs and dsize % 8 == 0 and (not incompat & 0x80 or dsize >= 64),
                "invalid ext4 superblock geometry")
        groups = (blocks - first + bpg - 1) // bpg
        require(0 < groups <= 131072 and 0 < inodes <= groups * ipg,
                "invalid ext4 inode/group count")
        self.sb = s
        self.bs, self.blocks, self.first = bs, blocks, first
        self.bpg, self.ipg, self.inodes = bpg, ipg, inodes
        self.isize, self.dsize, self.groups = isize, dsize, groups

    def block(self, number):
        require(0 < number < self.blocks, "ext4 block outside filesystem")
        return self.source.read_at(number * self.bs, self.bs)

    def inode(self, number):
        self.init()
        require(0 < number <= self.inodes, "ext4 inode outside filesystem")
        group, slot = divmod(number - 1, self.ipg)
        gd = self.source.read_at((self.first + 1) * self.bs + group * self.dsize, self.dsize)
        table = struct.unpack_from("<I", gd, 8)[0]
        if self.dsize >= 64:
            table |= struct.unpack_from("<I", gd, 40)[0] << 32
        offset = table * self.bs + slot * self.isize
        require(table > 0 and offset + self.isize <= self.blocks * self.bs,
                "ext4 inode table outside filesystem")
        raw = self.source.read_at(offset, self.isize)
        mode = struct.unpack_from("<H", raw)[0]
        size = struct.unpack_from("<I", raw, 4)[0] | struct.unpack_from("<I", raw, 108)[0] << 32
        flags = struct.unpack_from("<I", raw, 32)[0]
        require(struct.unpack_from("<I", raw, 20)[0] == 0 and
                struct.unpack_from("<H", raw, 26)[0] > 0, "deleted/unlinked ext4 inode")
        require(flags & (0x4 | 0x800 | 0x1000 | 0x80000 | 0x100000 | 0x10000000) == flags & 0x80000,
                "unsupported compressed/encrypted/indexed/inline ext4 inode")
        return mode, size, flags, raw[40:100]

    def extents(self, inode):
        mode, size, flags, body = inode
        require(size <= LIMIT, "ext4 file/directory exceeds 64MiB bound")
        require(flags & 0x80000, "unsupported ext4 non-extent inode")
        extents, visited = [], set()

        def visit(data, expected=None):
            require(len(data) >= 12, "truncated ext4 extent header")
            magic, count, capacity, depth = struct.unpack_from("<4H", data)
            require(magic == 0xf30a and 0 <= depth <= 5 and
                    (expected is None or depth == expected) and
                    0 < capacity <= (len(data) - 12) // 12 and count <= capacity,
                    "invalid ext4 extent tree")
            keys = []
            for i in range(count):
                a, b, c = struct.unpack_from("<III", data, 12 + i * 12)
                keys.append(a)
                if depth:
                    physical = b | ((c & 0xffff) << 32)
                    require(c >> 16 == 0 and physical not in visited and len(visited) < 4096,
                            "cyclic/oversized ext4 extent index")
                    visited.add(physical)
                    child = self.block(physical)
                    visit(child, depth - 1)
                else:
                    length = b & 0xffff
                    physical = c | ((b >> 16) << 32)
                    unwritten = length > 32768
                    length = length - 32768 if unwritten else length
                    require(length > 0 and physical > 0 and physical + length <= self.blocks,
                            "ext4 extent outside filesystem")
                    extents.append((a, length, physical, unwritten))
            require(keys == sorted(set(keys)), "unsorted ext4 extent keys")
        visit(body)
        end = 0
        for logical, length, physical, unwritten in extents:
            require(logical >= end and logical * self.bs < max(size, 1),
                    "overlapping/out-of-file ext4 extents")
            end = logical + length
        require(len(extents) <= 16384, "too many ext4 extents")
        return extents

    def data(self, inode):
        size = inode[1]
        extents = self.extents(inode)
        result = bytearray(size)
        # Ask for all data ranges before a streaming pass (not one pass per block).
        pending = False
        for logical, length, physical, unwritten in extents:
            start = logical * self.bs
            amount = min(length * self.bs, size - start)
            if unwritten:
                continue
            try:
                result[start:start + amount] = self.source.read_at(physical * self.bs, amount)
            except NeedBlocks:
                pending = True
        if pending:
            raise NeedBlocks()
        return bytes(result)

    def entries(self, inode):
        require(inode[0] & 0xf000 == 0x4000, "ext4 path is not a directory")
        data, result = self.data(inode), {}
        for base in range(0, len(data), self.bs):
            at, end = base, min(base + self.bs, len(data))
            while at < end:
                require(at + 8 <= end, "truncated ext4 directory entry")
                ino, size, nlen, kind = struct.unpack_from("<IHBB", data, at)
                require(size >= 8 and size % 4 == 0 and at + size <= end and nlen <= size - 8,
                        "malformed ext4 directory entry")
                if ino:
                    require(0 < nlen <= 255 and ino <= self.inodes, "invalid ext4 directory name/inode")
                    name = data[at + 8:at + 8 + nlen].decode("utf-8", "strict")
                    require("/" not in name and "\0" not in name and name not in result,
                            "unsafe/duplicate ext4 directory name")
                    result[name] = ino
                at += size
        return result

    def lookup(self, name):
        self.init()
        parts = ([self.prefix] if self.prefix else []) + relative(name).split("/")
        number = 2
        for part in parts:
            entries = self.entries(self.inode(number))
            if part not in entries:
                raise MissingSource("missing ext4 source: " + name)
            number = entries[part]
        return self.inode(number)

    def locate(self, name):
        self.lookup(name)
        return True

    def read(self, name):
        inode = self.lookup(name)
        require(inode[0] & 0xf000 == 0x8000 and 0 < inode[1] <= LIMIT,
                "missing/non-regular ext4 file: " + name)
        return self.data(inode)

    def files(self, name):
        entries = self.entries(self.lookup(name))
        require(len(entries) <= 4096, "ext4 directory exceeds entry bound")
        result, pending = [], False
        for key, number in sorted(entries.items()):
            if key in (".", ".."):
                continue
            try:
                node = self.inode(number)
                require(node[0] & 0xf000 == 0x8000, "non-regular ext4 config/library entry: " + name + "/" + key)
                result.append(name + "/" + relative(key))
            except NeedBlocks:
                pending = True
        if pending:
            raise NeedBlocks()
        require(result, "empty/missing ext4 directory: " + name)
        return result


def resolve(jobs, missing=False):
    """Batch independent filesystem requests across bounded sequential OTA passes."""
    results, todo = {}, list(enumerate(jobs))
    for iteration in range(64):
        again, stores = [], {}
        for key, (reader, method, name) in todo:
            try:
                results[key] = getattr(reader, method)(name)
                require(sum(len(v) for v in results.values() if isinstance(v, bytes)) <= 128 * 1024**2,
                        "requested runtime files exceed 128MiB batch bound")
            except MissingSource:
                if not missing:
                    raise
                results[key] = None
            except NeedBlocks:
                again.append((key, (reader, method, name)))
                stores[id(reader.source)] = reader.source
        if not again:
            return [results[i] for i in range(len(jobs))]
        for source in stores.values():
            source.fill()
        todo = again
    raise ValueError("selective ext4 resolution exceeded 64 passes")

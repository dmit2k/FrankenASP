"""Read-only owner source readers. No firmware execution, mounts or network."""
import hashlib
import json
import re
import stat
import struct
import subprocess
import zipfile
from pathlib import Path, PurePosixPath

LIVE = "LIVE_VENDOR_MATCHED"
BUNDLE = "OTA_VENDOR_BUNDLED_MATCHED"
META = "META-INF/com/android/metadata"
LIMIT = 64 * 1024 * 1024
NAME = re.compile(r"[A-Za-z0-9_.@+/-]+\Z")
LIBDIRS = ("vendor/lib", "system/lib/vndk-28", "system/lib/vndk-sp-28", "system/lib")
SYSTEM_CONFIGS = ("build.prop", "etc/ld.config.28.txt",
                  "etc/public.libraries.txt", "etc/public.libraries-AMAZON.txt")


class Refusal(ValueError):
    pass


class MissingSource(Refusal):
    pass


def require(ok, message):
    if not ok:
        raise Refusal(message)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def relative(name):
    p = PurePosixPath(name)
    require(bool(NAME.fullmatch(name)) and not p.is_absolute() and
            all(x not in ("", ".", "..") for x in name.split("/")),
            "unsafe source path: " + name)
    return name


def properties(raw):
    result = {}
    for line in raw.decode("utf-8", "strict").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        require(key not in result or result[key] == value, "conflicting property: " + key)
        result[key] = value
    return result


def json_file(path):
    require(Path(path).is_file() and Path(path).stat().st_size < 1024 * 1024,
            "missing/oversized JSON receipt")
    value = json.loads(Path(path).read_text())
    require(isinstance(value, dict), "JSON receipt/config must be an object")
    return value


def elf(raw, interpreter=None, shared=False, native_static=False):
    require(len(raw) >= 52 and raw[:7] == b"\x7fELF\x01\x01\x01",
            "expected ELF32 little-endian")
    h = struct.unpack_from("<HHIIIIIHHHHHH", raw, 16)
    kind, machine, version, _, phoff, _, flags, ehsize, phsize, count = h[:10]
    require(machine == 40 and version == 1 and kind in (2, 3) and
            flags & 0xff000000 == 0x05000000 and ehsize == 52 and
            phsize == 32 and 0 < count <= 128 and phoff + count * 32 <= len(raw),
            "expected bounded ARM EABI5 executable/shared ELF")
    require(not shared or kind == 3, "expected ARM shared object")
    headers = [struct.unpack_from("<8I", raw, phoff + i * 32) for i in range(count)]
    for p in headers:
        require(p[1] + p[4] <= len(raw), "ELF segment outside file")
    require(any(p[0] == 1 for p in headers), "ELF has no LOAD")
    interps = [raw[p[1]:p[1] + p[4]] for p in headers if p[0] == 3]
    expected = [] if interpreter is None else [interpreter.encode() + b"\0"]
    # One original Athena DSO (libedgeflow_core_neon) also has Bionic PT_INTERP.
    # Preserve it unchanged; shared objects may never select a Linux interpreter.
    require(interps == expected or shared and interps == [b"/system/bin/linker\0"],
            "wrong ELF interpreter: native static launcher vs original Bionic child")
    require(not native_static or not any(p[0] == 2 for p in headers),
            "Linux launcher must be static without PT_DYNAMIC")
    needed = []
    for p in headers:
        if p[0] != 2:
            continue
        require(p[4] % 8 == 0, "malformed ELF dynamic section")
        entries = [struct.unpack_from("<II", raw, i)
                   for i in range(p[1], p[1] + p[4], 8)]
        strings = next((v for k, v in entries if k == 5), None)
        size = next((v for k, v in entries if k == 10), None)
        if strings is None:
            require(not any(k == 1 for k, _ in entries), "missing ELF string table")
            continue
        offset = next((q[1] + strings - q[2] for q in headers if q[0] == 1 and
                       q[2] <= strings < q[2] + q[4]), None)
        require(offset is not None and size is not None and offset + size <= len(raw),
                "bad ELF string table")
        for tag, value in entries:
            if tag != 1:
                continue
            require(value < size, "bad DT_NEEDED index")
            end = raw.find(b"\0", offset + value, offset + size)
            require(end >= 0, "unterminated DT_NEEDED")
            name = raw[offset + value:end].decode("ascii")
            require("/" not in name and bool(NAME.fullmatch(name)), "unsafe DT_NEEDED")
            needed.append(name)
    require(b"GLIBC_" not in raw or interpreter is None and not shared,
            "Linux libc cannot enter the Bionic runtime")
    return needed


class Directory:
    def __init__(self, path):
        self.path = Path(path).absolute()
        require(self.path.is_dir() and not self.path.is_symlink(), "source directory missing")
        self.label = str(self.path)

    def node(self, name):
        p = self.path
        for item in relative(name).split("/"):
            p = p / item
            require(not p.is_symlink(), "source symlinks unsupported: " + name)
        return p

    def locate(self, name):
        p = self.node(name)
        if not p.exists():
            raise MissingSource("missing source: " + name)
        return True

    def read(self, name):
        p = self.node(name)
        if not p.exists():
            raise MissingSource("missing source: " + name)
        require(p.is_file() and 0 < p.stat().st_size <= LIMIT, "missing/oversized source: " + name)
        return p.read_bytes()

    def files(self, name):
        p = self.node(name)
        require(p.is_dir(), "missing source directory: " + name)
        result = []
        for x in sorted(p.iterdir()):
            require(x.is_file() and not x.is_symlink(), "non-flat source directory: " + name)
            result.append(name + "/" + x.name)
        return result


from installer_ext4 import Ext4, resolve


class ZipTree:
    def __init__(self, archive, prefix):
        self.archive, self.prefix = archive, prefix
        self.label = str(archive.filename) + ":" + prefix

    def locate(self, name):
        key = self.prefix + "/" + relative(name)
        if key not in self.archive.namelist():
            raise MissingSource("missing OTA entry: " + key)
        return True

    def read(self, name):
        key = self.prefix + "/" + relative(name)
        try:
            info = self.archive.getinfo(key)
        except KeyError as e:
            raise MissingSource("missing OTA entry: " + key) from e
        require(0 < info.file_size <= LIMIT, "oversized/empty OTA entry: " + key)
        return self.archive.read(info)

    def files(self, name):
        prefix = self.prefix + "/" + relative(name) + "/"
        result = []
        for info in self.archive.infolist():
            if info.filename.startswith(prefix) and not info.is_dir():
                tail = info.filename[len(prefix):]
                require("/" not in tail, "nested OTA config/library directory unsupported")
                result.append(name + "/" + tail)
        require(result, "missing OTA directory: " + prefix)
        return sorted(result)


def ota_open(path):
    require(Path(path).is_file() and not Path(path).is_symlink(), "local OTA file required")
    try:
        z = zipfile.ZipFile(path)
        infos = z.infolist()
        require(0 < len(infos) <= 100000 and len({x.filename for x in infos}) == len(infos),
                "duplicate/too many OTA entries")
        require(sum(x.file_size for x in infos) <= 8 * 1024**3, "OTA exceeds 8GiB bound")
        for x in infos:
            relative(x.filename.rstrip("/"))
            mode = x.external_attr >> 16
            require(not stat.S_ISLNK(mode) and not x.flag_bits & 1, "OTA symlink/encryption unsupported")
            require(not stat.S_IFMT(mode) or stat.S_ISREG(mode) or stat.S_ISDIR(mode),
                    "OTA special file unsupported")
        require(META in z.namelist() and z.getinfo(META).file_size <= 65536,
                "OTA metadata missing/oversized")
        meta = properties(z.read(META))
        names = set(z.namelist())
        require(not any(k.startswith("pre-build") for k in meta) and "payload.bin" not in names,
                "incremental/payload OTA unsupported; missing-base reconstruction refused")

        block = any(n.endswith((".transfer.list", ".new.dat", ".new.dat.br", ".patch.dat"))
                    for n in names)
        if block:
            require(meta.get("ota-type") == "BLOCK" and
                    not any(n.endswith(".new.dat") for n in names),
                    "only complete Brotli v4 block-transfer OTA supported")
            from installer_block_ota import plans
            plans(z)
            kind = "ZIP_FULL_BLOCK_BROTLI_V4"
        elif {"system.img", "vendor.img"} <= names:
            require(meta.get("ota-type") == "BLOCK", "raw image ZIP requires ota-type=BLOCK")
            kind = "ZIP_RAW_EXT4_IMAGES"
        else:
            require(meta.get("ota-type") == "FILE" and "system/build.prop" in names and
                    "vendor/build.prop" in names, "unsupported/incomplete OTA format")
            kind = "ZIP_FULL_FILE_TREE"
        return z, meta, kind
    except (zipfile.BadZipFile, KeyError, UnicodeError) as e:
        raise Refusal("damaged OTA ZIP/metadata") from e


def pair(system, vendor, authority=None, package_sha=None, metadata=None):
    # Source trust belongs to the user. Only runtime contents/structure qualify.
    asp, configs = resolve([(vendor, "read", "lib/libasp.so"),
                            (vendor, "files", "etc/audio-algorithms")])
    try:
        elf(asp, shared=True)
    except Refusal as e:
        raise Refusal("vendor/lib/libasp.so: " + str(e)) from e
    values = resolve([(vendor, "read", p) for p in configs])
    observed = {p.split("/")[-1]: len(raw) for p, raw in zip(configs, values)}
    require(all(observed.get(x, 0) > 0 for x in ("asp.cfg", "AFE.cfg")),
            "missing factory config: asp.cfg or AFE.cfg")
    # Informational build labels, never a source/fingerprint gate.
    s = properties(resolve([(system, "read", "build.prop")])[0])
    return {"platform": "athena", "fingerprint": s.get("ro.build.fingerprint"),
            "build_id": s.get("ro.build.id"), "config_inventory": observed,
            "factory_authentication": "USER_SELECTED_UNAUTHENTICATED",
            "runtime_structure_verified": True}


def digest_bytes(data):
    return hashlib.sha256(data).hexdigest()


def closure(system, vendor, child):
    readers = {"system": system, "vendor": vendor}
    configs = resolve([(vendor, "files", "etc/audio-algorithms")])[0]
    require(0 < len(configs) <= 512, "factory config directory exceeds 512-file bound")
    paths = ["system/" + x for x in SYSTEM_CONFIGS] + ["vendor/" + x for x in configs]
    paths += ["vendor/build.prop", "system/bin/linker", "vendor/lib/libasp.so", "system/lib/ld-android.so"]
    def jobs(names):
        return [(readers[p.split("/", 1)[0]], "read", p.split("/", 1)[1]) for p in names]
    result = dict(zip(paths, resolve(jobs(paths))))
    try:
        elf(result["system/bin/linker"])
    except Refusal as e:
        raise Refusal("system/bin/linker: " + str(e)) from e
    queue = [("factory/asp2-child", child), ("vendor/lib/libasp.so", result["vendor/lib/libasp.so"]),
             ("system/lib/ld-android.so", result["system/lib/ld-android.so"])]
    edges, seen = [], set()
    while queue:
        batch, queue = queue, []
        requests = []
        for parent, data in batch:
            if parent in seen:
                continue
            seen.add(parent)
            needed = elf(data, "/system/bin/linker" if parent.startswith("factory/") else None,
                         shared=not parent.startswith("factory/"))
            requests.extend((parent, soname) for soname in needed)
        # Probe directory/inode metadata in loader priority order. Never read
        # lower-priority duplicate file data once a preferred object exists.
        selections = {}
        sonames = list(dict.fromkeys(n for _, n in requests))
        for directory in LIBDIRS:
            candidates = [directory + "/" + n for n in sonames if n not in selections]
            probe_jobs = [(reader, "locate", name) for reader, _, name in jobs(candidates)]
            for candidate, exists in zip(candidates, resolve(probe_jobs, missing=True)):
                if exists:
                    selections[candidate.rsplit("/", 1)[1]] = candidate
        for parent, soname in requests:
            require(soname in selections, "missing Bionic dependency: " + soname + " needed by " + parent)
        paths = list(dict.fromkeys(selections.values()))
        found = dict(zip(paths, resolve(jobs(paths))))
        for parent, soname in requests:
            selected = selections[soname]
            raw = found[selected]
            try:
                elf(raw, shared=True)
            except Refusal as e:
                raise Refusal(selected + ": " + str(e)) from e
            result[selected] = raw
            queue.append((selected, raw))
            edges.append({"parent": parent, "needed": soname, "selected": selected})
        require(len(seen) <= 256 and sum(map(len, result.values())) <= 128 * 1024**2, "dependency closure exceeds bound")
    return result, edges

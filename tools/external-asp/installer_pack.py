"""Portable deterministic packing of an already prepared I2-S payload."""
import gzip
import os
from pathlib import Path
import tarfile

from installer_payload import ALIASES, RECEIPT, safe_output, validate
from installer_sources import require


def pack(args):
    payload = Path(args.payload).absolute()
    # Missing approved aliases are represented directly in TAR. Windows needs
    # no symlink privilege; any present alias must still have the exact target.
    receipt = validate(payload, virtual_aliases=True)
    output = safe_output(args.output)
    require(not output.is_relative_to(payload), "archive output cannot be inside payload")
    aliases = {"lib/rootfs/proc/" + name: target for name, target in ALIASES.items()}
    entries = {p.relative_to(payload).as_posix(): p for p in payload.rglob("*")}
    for name in aliases:
        entries.setdefault(name, None)
    require(len(entries) <= 2048, "too many payload entries")
    total = sum(p.stat().st_size for p in entries.values()
                if p is not None and p.is_file() and not p.is_symlink())
    require(total <= 48 * 1024**2, "payload exceeds Go 48MiB bound")
    created = False
    try:
        with output.open("xb") as stream:
            created = True
            if os.name != "nt":
                os.chmod(output, 0o600)
            with gzip.GzipFile(filename="", mode="wb", fileobj=stream, mtime=0, compresslevel=9) as gz:
                with tarfile.open(fileobj=gz, mode="w|", format=tarfile.USTAR_FORMAT) as archive:
                    for name, p in sorted(entries.items()):
                        info = tarfile.TarInfo(name)
                        info.uid = info.gid = info.mtime = 0
                        info.uname = info.gname = ""
                        if name in aliases:
                            if p is not None:
                                require(p.is_symlink() and os.readlink(p) == aliases[name],
                                        "unexpected proc/IDME alias")
                            info.type, info.linkname, info.mode = tarfile.SYMTYPE, aliases[name], 0o777
                            archive.addfile(info)
                        elif p.is_dir():
                            info.type = tarfile.DIRTYPE
                            info.mode = 0o700 if os.name == "nt" else p.stat().st_mode & 0o7777
                            archive.addfile(info)
                        else:
                            require(p.is_file() and not p.is_symlink(), "special/unknown pack inode")
                            info.mode = (0o600 if name == RECEIPT else
                                         0o500 if name in ("bin/external-asp",
                                                          "lib/rootfs/factory/asp2-child",
                                                          "lib/rootfs/system/bin/linker") else 0o400)
                            if os.name != "nt":
                                info.mode = p.stat().st_mode & 0o7777
                            info.size = p.stat().st_size
                            require(0 < info.size <= 16 * 1024**2, "empty/oversized payload file")
                            with p.open("rb") as source:
                                archive.addfile(info, source)
            stream.flush()
            os.fsync(stream.fileno())
        return {"bundle": str(output), "bytes": output.stat().st_size,
                "mode": receipt["mode"], "deterministic": True, "activation": False}
    except BaseException:
        if created:
            output.unlink(missing_ok=True)
        raise

"""F2-A real FD4 tests; synthetic bytes/ELF only, no device or mount access."""
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import select
import shutil
import struct
import subprocess
import tempfile
import threading
import time
import unittest

BUILD = Path(os.environ['OUT_DIR'])
SAN = os.environ.get('ASSET_SANITIZED') == '1'
BIN = BUILD / ('asset-preflight-sanitized' if SAN else 'asset-preflight-test')
FAULT = BUILD / ('asset-faults-sanitized' if SAN else 'asset-faults')
PROFILE = b'ASP2-FD4-OFFLINE-V1\nplatform=athena\nbackend=synthetic\nfactory_admission=disabled\nmanifest=etc/assets.sha256\n'
PATHS = [
    'etc/profile.conf',
    'lib/rootfs/opt/external-asp/offline-child.elf',
    'lib/rootfs/system/bin/linker',
    'lib/rootfs/system/lib/libfixture-base.so',
    'lib/rootfs/vendor/etc/fixture.conf',
    'lib/rootfs/vendor/etc/optional.conf',
    'lib/rootfs/vendor/lib/libfixture-top.so',
]
DIRS = ['etc', 'lib', 'lib/rootfs', 'lib/rootfs/system',
        'lib/rootfs/system/bin', 'lib/rootfs/system/lib', 'lib/rootfs/vendor',
        'lib/rootfs/vendor/etc', 'lib/rootfs/vendor/lib', 'lib/rootfs/opt',
        'lib/rootfs/opt/external-asp']


def cc(*args):
    subprocess.run(['cc', *map(str, args)], check=True, timeout=20,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def build_elf():
    d = BUILD / 'synthetic-elf'
    d.mkdir(exist_ok=True)
    sources = {
        'base.c': 'int fixture_base(void){return 19;}\n',
        'top.c': 'extern int fixture_base(void); int fixture_top(void){return fixture_base()+23;}\n',
        'entry.c': 'extern int fixture_top(void); void _start(void){long x=fixture_top(); __asm__ volatile("syscall"::"a"(60L),"D"(x):"rcx","r11","memory"); __builtin_unreachable();}\n',
        'linker.c': 'int offline_loader_placeholder(void){return 0;}\n',
        'libc.c': '#include <stdio.h>\nint main(void){return puts("native libc fixture only")<0;}\n',
    }
    for name, data in sources.items():
        (d / name).write_text(data)
    flags = ['-nostdlib', '-fno-stack-protector', '-fPIC', '-Wl,--build-id=none']
    cc(*flags, '-shared', '-Wl,-soname,libfixture-base.so', d/'base.c', '-o', d/'libfixture-base.so')
    cc(*flags, '-shared', '-Wl,-soname,libfixture-top.so', '-Wl,--no-as-needed',
       d/'top.c', '-L'+str(d), '-lfixture-base', '-o', d/'libfixture-top.so')
    cc(*flags, '-shared', d/'linker.c', '-o', d/'linker')
    cc(*flags, '-pie', '-Wl,-e,_start', '-Wl,--dynamic-linker=/system/bin/linker',
       '-Wl,--no-as-needed', d/'entry.c', '-L'+str(d), '-lfixture-top',
       '-Wl,-rpath-link,'+str(d), '-o', d/'offline-child.elf')
    cc(d/'libc.c', '-o', d/'native-libc.elf')
    analysis = {}
    for name in ['offline-child.elf', 'linker', 'libfixture-base.so', 'libfixture-top.so', 'native-libc.elf']:
        data = subprocess.check_output(['readelf', '-h', '-l', '-d', str(d/name)], text=True, timeout=5)
        (d/(name+'.readelf.txt')).write_text(data)
        analysis[name] = {'sha256': hashlib.sha256((d/name).read_bytes()).hexdigest(),
                          'bytes': (d/name).stat().st_size}
    (d/'SHA256.json').write_text(json.dumps(analysis, indent=2)+'\n')
    return d


class Fixture:
    def __init__(self, base, elf):
        self.base = base
        self.root = base/'external-asp'
        self.root.mkdir(mode=0o700)
        for path in DIRS:
            (self.root/path).mkdir(mode=0o700)
        self.put(PATHS[0], PROFILE)
        for path, name in [(PATHS[1], 'offline-child.elf'), (PATHS[2], 'linker'),
                           (PATHS[3], 'libfixture-base.so'), (PATHS[6], 'libfixture-top.so')]:
            self.put(path, (elf/name).read_bytes())
        self.put(PATHS[4], b'SYNTHETIC VENDOR SHAPED PLACEHOLDER\n')
        self.manifest()
        self.fd = os.open(self.root, os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC)
    def put(self, path, data):
        p = self.root/path
        p.write_bytes(data)
        p.chmod(0o600)
    def manifest(self):
        lines = [hashlib.sha256((self.root/p).read_bytes()).hexdigest()+'  '+p+'\n'
                 for p in PATHS if (self.root/p).is_file()]
        self.put('etc/assets.sha256', ''.join(lines).encode())
    def close(self):
        os.close(self.fd)


@contextlib.contextmanager
def fd4(fd):
    if fd == 4:
        yield
        return
    try:
        backup = fcntl.fcntl(4, fcntl.F_DUPFD_CLOEXEC, 200)
    except OSError:
        backup = None
    os.dup2(fd, 4)
    try:
        yield
    finally:
        if backup is None:
            os.close(4)
        else:
            os.dup2(backup, 4)
            os.close(backup)


def launch(f, args=(), binary=BIN, env=None):
    with fd4(f.fd):
        return subprocess.Popen([str(binary), *args], pass_fds=(4,), stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0,
                                env={**os.environ, **(env or {})})


class AssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.elf = build_elf()
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='assets-', dir=BUILD)
        self.addCleanup(self.tmp.cleanup)
        self.f = Fixture(Path(self.tmp.name), self.elf)
        self.addCleanup(self.f.close)
    def run_child(self, args=(), good=True, binary=BIN, env=None, f=None):
        p = launch(f or self.f, args, binary, env)
        out, err = p.communicate(timeout=10)
        text = out.decode()
        self.assertNotIn(b'AddressSanitizer', err)
        self.assertNotIn(b'runtime error:', err)
        self.assertEqual(err, b'', err)
        if good:
            self.assertEqual(p.returncode, 0, text)
            self.assertIn('RESULT ok', text)
        else:
            self.assertTrue(20 < p.returncode < 40, (p.returncode, text))
            self.assertNotIn('ASSET ', text)
        self.assertRegex(text, r'fd=(\d+):\1\n$')
        return text
    def paused(self, event, path):
        p = launch(self.f, ['--pause', event, path])
        self.addCleanup(lambda: self.cleanup_child(p))
        line = b''
        deadline = time.monotonic()+5
        while not line.endswith(b'\n'):
            self.assertTrue(select.select([p.stdout], [], [], max(0, deadline-time.monotonic()))[0])
            b = os.read(p.stdout.fileno(), 1)
            self.assertTrue(b, line)
            line += b
        self.assertIn(b'PAUSED ', line)
        return p
    @staticmethod
    def cleanup_child(p):
        if p.poll() is None:
            p.kill()
        p.communicate(timeout=5)
    def resume(self, p, good=None):
        out, err = p.communicate(b'\n', timeout=5)
        self.assertEqual(err, b'')
        self.assertNotIn(p.returncode, [91, 92, 93, 94])
        if good is True:
            self.assertEqual(p.returncode, 0, out)
        elif good is False:
            self.assertTrue(20 < p.returncode < 40, out)
        else:
            self.assertTrue(p.returncode == 0 or 20 < p.returncode < 40, out)
        return out.decode()
    def assert_original(self, text, identities):
        for path, (dev, ino, size, digest) in identities.items():
            self.assertIn(f'ASSET {path} {dev}:{ino} {size} {digest}\n', text)
    def identities(self):
        result = {}
        for path in PATHS:
            p = self.f.root/path
            if p.exists():
                s = p.stat()
                result[path] = (s.st_dev, s.st_ino, s.st_size, hashlib.sha256(p.read_bytes()).hexdigest())
        return result
    def test_good_pinned_inode_and_sealed_bytes(self):
        ids = self.identities()
        text = self.run_child()
        self.assert_original(text, ids)
        self.run_child(['--repeat', '128'])
        self.f.put(PATHS[5], b'optional synthetic\n')
        self.f.manifest()
        self.assert_original(self.run_child(), self.identities())
    def test_sha256_boundaries_against_independent_manifest(self):
        for data in [b'a', b'abc', *[b'x'*n for n in [55, 56, 63, 64, 65, 8192, 1048576]]]:
            self.f.put(PATHS[4], data)
            self.f.manifest()
            self.assert_original(self.run_child(), self.identities())
    def test_preopen_metadata_replacements_fail_closed(self):
        for event, at, target in [('directory', 'etc', 'etc/assets.sha256'),
                                  ('snapshot', 'etc/assets.sha256', PATHS[0])]:
            p = self.paused(event, at)
            file = self.f.root/target
            old = Path(self.tmp.name)/'saved-metadata'
            file.rename(old)
            self.f.put(target, b'DECOY METADATA')
            self.resume(p, good=False)
            file.unlink();old.rename(file)
    def test_root_fd_contract_and_production_owner(self):
        self.run_child(['--production-owner'], good=False)
        self.run_child(binary=BUILD/'asset-preflight-root', good=False)
        p = subprocess.run([str(BIN)], close_fds=True, capture_output=True, timeout=5)
        self.assertNotEqual(p.returncode, 0)
        old = self.f.fd
        self.f.fd = os.open(self.f.root/'etc/profile.conf', os.O_RDONLY)
        self.run_child(good=False)
        os.close(self.f.fd)
        self.f.fd = old
    def test_manifest_format_and_path_adversaries(self):
        good = (self.f.root/'etc/assets.sha256').read_bytes()
        lines = good.splitlines(keepends=True)
        mutations = [b'', good[:-1], good+b'\n', b'X'+good[1:], good.replace(b'  ', b' ', 1),
                     good.replace(b'\n', b'\r\n'), lines[0]+good, b''.join(reversed(lines)),
                     b''.join(lines[1:]), good.replace(b'etc/profile.conf', b'etc/Profile.conf'),
                     good.replace(b'etc/profile.conf', b'etc/profile.conf\x00decoy')]
        for bad in [b'../etc/profile.conf', b'/etc/profile.conf', b'etc//profile.conf',
                    b'etc/./profile.conf', b'etc/../profile.conf', b'etc/profile.conf/',
                    b'etc/.. /profile.conf', b'', b'etc/\xff', b'a'*160, b'etc/unknown.conf']:
            mutations.append(good.replace(b'etc/profile.conf', bad))
        for ix, data in enumerate(mutations):
            with self.subTest(ix=ix):
                self.f.put('etc/assets.sha256', data)
                self.run_child(good=False)
        self.f.put('etc/assets.sha256', b'0'*4097)
        self.run_child(['--repeat', '256'], good=False)
    def test_missing_and_corrupt_every_required_file(self):
        for path in [p for p in PATHS if 'optional' not in p]:
            with self.subTest(path=path):
                p = self.f.root/path
                data = p.read_bytes()
                p.unlink()
                self.run_child(good=False)
                self.f.put(path, b'X'+data[1:])
                self.run_child(good=False)
                self.f.put(path, data)
        self.run_child()
    def test_profile_policy_and_limits(self):
        for data in [PROFILE+b'X', PROFILE.replace(b'disabled', b'enabled'),
                     PROFILE.replace(b'synthetic', b'bionic'), PROFILE.replace(b'athena', b'cronos'),
                     PROFILE.replace(b'etc/assets.sha256', b'../elsewhere'), PROFILE+b'\x00', b'x'*257]:
            self.f.put(PATHS[0], data)
            self.f.manifest()
            self.run_child(good=False)
        self.f.put(PATHS[0], PROFILE)
        self.f.put(PATHS[4], b'x'*(1024*1024+1))
        self.f.manifest()
        self.run_child(good=False)
        for path in [PATHS[1], PATHS[2], PATHS[3], PATHS[6]]:
            p = self.f.root/path
            self.f.put(path, p.read_bytes().ljust(1024*1024, b'\x00'))
        self.f.put(PATHS[4], b'x')
        self.f.manifest()
        self.assertIn('RESULT limit', self.run_child(good=False))
    def test_permissions_every_directory_and_file(self):
        for path in ['', *DIRS, *[p for p in PATHS if 'optional' not in p], 'etc/assets.sha256']:
            p = self.f.root/path
            mode = p.stat().st_mode & 0o7777
            for extra in [0o020, 0o002, 0o4000, 0o2000, 0o1000]:
                with self.subTest(path=path, extra=extra):
                    p.chmod(mode|extra)
                    self.assertIn('RESULT policy', self.run_child(good=False))
                    p.chmod(mode)
    def test_uid_fstat_every_level_test_only_fault(self):
        # Root, 11 directories, metadata and each file fstat. No chown or root.
        for call in [*range(1, 14), *range(15, 26, 2)]:
            with self.subTest(call=call):
                text = self.run_child(binary=FAULT, env={'AF_UID_AT': str(call)}, good=False)
                self.assertIn('RESULT policy', text)
    def test_symlink_and_wrong_type_every_component(self):
        for path in [*DIRS, *[p for p in PATHS if 'optional' not in p], 'etc/assets.sha256']:
            with self.subTest(path=path):
                p = self.f.root/path
                old = p.with_name(p.name+'.saved')
                p.rename(old)
                p.symlink_to(old.name, target_is_directory=old.is_dir())
                self.run_child(good=False)
                p.unlink()
                if old.is_dir():
                    p.write_bytes(b'not a directory')
                else:
                    p.mkdir(mode=0o700)
                self.run_child(good=False)
                if p.is_dir():
                    p.rmdir()
                else:
                    p.unlink()
                old.rename(p)
    def test_fifo_hardlink_unexpected_and_unmanifested(self):
        p = self.f.root/PATHS[4]
        data = p.read_bytes()
        p.unlink()
        os.mkfifo(p, 0o600)
        self.run_child(['--repeat', '128'], good=False)
        p.unlink()
        self.f.put(PATHS[4], data)
        hard = Path(self.tmp.name)/'hard'
        os.link(p, hard)
        self.assertIn('RESULT policy', self.run_child(good=False))
        hard.unlink()
        self.f.put('lib/rootfs/vendor/etc/UNEXPECTED', b'x')
        self.run_child(good=False)
        (self.f.root/'lib/rootfs/vendor/etc/UNEXPECTED').unlink()
        self.f.put(PATHS[5], b'undeclared optional')
        self.run_child(good=False)
    def test_read_errors_short_eintr_and_fd_leaks(self):
        self.run_child(binary=FAULT, env={'AF_READ': 'short', 'AF_WRITE': 'short'})
        for env in [{'AF_READ': 'fail'}, {'AF_WRITE': 'fail'}, {'AF_MEMFD': '1'}]:
            self.run_child(['--repeat', '512'], binary=FAULT, env=env, good=False)
        (self.f.root/PATHS[6]).unlink()
        self.run_child(['--repeat', '512'], good=False)
    def test_root_rename_before_and_during_open(self):
        for event, path in [('root', ''), ('ready', '')]:
            p = self.paused(event, path)
            ids = self.identities()
            original = self.f.root.with_name('original')
            self.f.root.rename(original)
            self.f.root.mkdir(mode=0o700)
            (self.f.root/'etc').mkdir(mode=0o700)
            self.f.put('etc/profile.conf', b'DECOY')
            self.assert_original(self.resume(p, good=True), ids)
            shutil.rmtree(self.f.root)
            original.rename(self.f.root)
        # Root name is a symlink after FD4 was pinned; no resolution of it.
        original = self.f.root.with_name('original')
        ids = self.identities()
        self.f.root.rename(original)
        self.f.root.symlink_to('does-not-exist', target_is_directory=True)
        self.assert_original(self.run_child(), ids)
        self.f.root.unlink()
        original.rename(self.f.root)
    def test_directory_swap_after_pin_and_file_before_snapshot(self):
        for path in ['etc', 'lib/rootfs/vendor', 'lib/rootfs/system/lib']:
            p = self.paused('directory', path)
            d = self.f.root/path
            old = d.with_name(d.name+'.original')
            d.rename(old)
            d.symlink_to(old.name, target_is_directory=True)
            self.resume(p)  # original snapshots or terminal changed; never symlink content
            d.unlink()
            old.rename(d)
        # Replacing a library before its open must fail its committed hash.
        p = self.paused('snapshot', 'etc/assets.sha256')
        file = self.f.root/PATHS[6]
        old = Path(self.tmp.name)/'saved-lib'
        file.rename(old)
        self.f.put(PATHS[6], b'DECOY LIBRARY')
        self.resume(p, good=False)
        file.unlink()
        old.rename(file)
    def test_metadata_and_assets_replaced_after_snapshot(self):
        for path in ['etc/assets.sha256', PATHS[0], PATHS[6]]:
            p = self.paused('snapshot', path)
            file = self.f.root/path
            old = Path(self.tmp.name)/'original-file'
            file.rename(old)
            self.f.put(path, b'DECOY')
            self.resume(p, good=False)  # end-of-scan identity mismatch is terminal
            file.unlink()
            old.rename(file)
    def test_immutable_consumption_after_ready_all_swaps(self):
        ids = self.identities()
        p = self.paused('ready', '')
        for path in ['etc/assets.sha256', *[p for p in PATHS if 'optional' not in p]]:
            self.f.put(path, b'IN PLACE MUTATION AFTER VERIFICATION')
        # Replace entire tree and leave only decoys at visible names.
        original = self.f.root.with_name('original')
        self.f.root.rename(original)
        self.f.root.mkdir(mode=0o700)
        self.assert_original(self.resume(p, good=True), ids)
    def test_concurrent_rename_race_bounded(self):
        target = self.f.root/PATHS[6]
        good = target.read_bytes()
        decoy = Path(self.tmp.name)/'decoy'
        decoy.write_bytes(b'DECOY');decoy.chmod(0o600)
        slot = Path(self.tmp.name)/'slot'
        stop = threading.Event()
        count = [0]
        def swap():
            while not stop.is_set() and count[0] < 20000:
                target.rename(slot); decoy.rename(target); slot.rename(decoy)
                count[0] += 1
        thread = threading.Thread(target=swap)
        thread.start()
        successes = 0
        try:
            for _ in range(32):
                p = launch(self.f)
                out, err = p.communicate(timeout=5)
                self.assertEqual(err, b'')
                self.assertTrue(p.returncode == 0 or 20 < p.returncode < 40, out)
                if p.returncode == 0:
                    successes += 1
                    self.assertIn(hashlib.sha256(good).hexdigest().encode(), out)
                    self.assertNotIn(hashlib.sha256(b'DECOY').hexdigest().encode(), out)
        finally:
            stop.set();thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertGreater(count[0], 0)
        print(f'RACE cycles={count[0]} launches=32 original={successes} reject={32-successes}', flush=True)
    def test_elf_closure_and_native_libc_rejection(self):
        report = (self.elf/'offline-child.elf.readelf.txt').read_text()
        self.assertIn('/system/bin/linker', report)
        self.assertIn('libfixture-top.so', report)
        self.assertIn('libfixture-base.so', (self.elf/'libfixture-top.so.readelf.txt').read_text())
        self.assertNotIn('libc.so', report)
        # Synthetic PT_INTERP cannot execute on host; never invoke ldd.
        with self.assertRaises(FileNotFoundError):
            subprocess.run([str(self.elf/'offline-child.elf')], check=True, timeout=2)
        self.f.put(PATHS[1], (self.elf/'native-libc.elf').read_bytes())
        self.f.manifest()
        self.assertIn('RESULT elf', self.run_child(good=False))
        self.f.put(PATHS[1], (self.elf/'offline-child.elf').read_bytes())
        top = (self.elf/'libfixture-top.so').read_bytes()
        self.f.put(PATHS[6], top.replace(b'libfixture-base.so', b'libmissing-base.so'))
        self.f.manifest()
        self.assertIn('RESULT elf', self.run_child(good=False))
    def test_elf_malformed_bounds_and_loader_paths(self):
        original = (self.elf/'offline-child.elf').read_bytes()
        mutations = [b'\x7fELF', original[:63], b'BAD!'+original[4:],
                     original[:4]+b'\x01'+original[5:],
                     original[:5]+b'\x02'+original[6:],
                     original.replace(b'/system/bin/linker', b'/xxxxxx/bin/linker'),
                     original.replace(b'libfixture-top.so', b'../fixture-top.so')]
        bad = bytearray(original);struct.pack_into('<Q', bad, 32, 2**64-1);mutations.append(bad)
        bad = bytearray(original);struct.pack_into('<H', bad, 56, 65535);mutations.append(bad)
        # Replace DT_NEEDED with DT_RUNPATH without relying on section offsets.
        phoff, = struct.unpack_from('<Q', original, 32)
        phsize, phnum = struct.unpack_from('<HH', original, 54)
        for i in range(phnum):
            ph = struct.unpack_from('<IIQQQQQQ', original, phoff+i*phsize)
            if ph[0] == 2:
                for pos in range(ph[2], ph[2]+ph[5], 16):
                    tag, value = struct.unpack_from('<qQ', original, pos)
                    if tag == 1:
                        bad = bytearray(original);struct.pack_into('<q', bad, pos, 29);mutations.append(bad)
                        bad = bytearray(original);struct.pack_into('<Q', bad, pos+8, 2**64-1);mutations.append(bad)
                        break
        for ix, data in enumerate(mutations):
            with self.subTest(ix=ix):
                self.f.put(PATHS[1], data);self.f.manifest()
                self.assertIn('RESULT elf', self.run_child(good=False))


if __name__ == '__main__':
    unittest.main(verbosity=2)

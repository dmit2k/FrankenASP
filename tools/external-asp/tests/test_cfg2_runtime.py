"""F1-A real native pipes and independent numerical oracle. OFFLINE ONLY."""
import hashlib
import itertools
import json
import os
from pathlib import Path
import select
import struct as S
import subprocess
import time
import unittest

BUILD = Path(os.environ["ASP2_BUILD_DIR"])
ROOT = Path(__file__).resolve().parent
FIX = ROOT / "cfg2_v2"
GOOD = (FIX / "athena_confirmed_complete_4mic.cfg2").read_bytes()
NO = 2**64 - 1
LEGACY = (ROOT / "rejected_fixed_cfg2.bin").read_bytes()

def tags(raw=GOOD):
    pos, out = 16, []
    while pos < len(raw):
        typ, flags, n = S.unpack_from("<HHI", raw, pos)
        out.append((typ, flags, raw[pos+8:pos+8+n]))
        pos += 8+n
    return out

def packet(items=None, flags=7):
    body = b"".join(S.pack("<HHI", t, f, len(v))+v for t, f, v in (tags() if items is None else items))
    return S.pack("<4sHHII", b"CFG2", 2, 16, 16+len(body), flags)+body

def change(typ, off, fmt, value, raw=GOOD):
    items = []
    for t, flags, v in tags(raw):
        if t == typ:
            v = bytearray(v)
            S.pack_into(fmt, v, off, value)
            v = bytes(v)
        items.append((t, flags, v))
    return packet(items)

def input_pcm(tick=0, high=False):
    m, r = bytearray(), bytearray()
    for f in range(1920):
        vals = [((tick*19033+f*31+c*991) % 16777216)-8388608 for c in range(4)]
        m.extend(S.pack("<4i", *(v*256 if high else v for v in vals)))
        r.extend(S.pack("<2h", *[((tick*101+f*13+c*1009) % 65536)-32768 for c in range(2)]))
    return bytes(m), bytes(r)

def oracle(m, r, micmap=(0,1,2,3), refmap=(0,1), high=False):
    # Independent Python conversion and FNV oracle over EVERY input word.
    mi = list(S.iter_unpack("<4i", m))
    re = list(S.iter_unpack("<2h", r))
    out = []
    for j in range(320):
        h = 2166136261
        for f in range(j*6, j*6+6):
            frame = [(mi[f][c] >> 8) if high else mi[f][c] for c in micmap]
            frame += [re[f][c]*65536 for c in refmap]
            for v in frame:
                h = ((h ^ (v & 0xffffffff))*16777619) & 0xffffffff
        v = ((h >> 16) ^ h) & 65535
        out.append(v-65536 if v >= 32768 else v)
    return S.pack("<320h", *out)

class Child:
    def __init__(self, binary="test-cfg2-synthetic", maps=(), args=None, env=None):
        if os.getenv("ASP2_CFG2_SANITIZED") == "1" and binary.startswith("test-cfg2-"):
            binary += "-sanitized"
        self.p = subprocess.Popen([str(BUILD/binary), *(args if args is not None else ["--offline-synthetic-cfg2", *maps])],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  bufsize=0, env={**os.environ, **(env or {})})
        self.hello_ns = time.monotonic_ns()
        assert self.read(4) == b"ASP2"
    def read(self, n, timeout=2):
        out = b""
        end = time.monotonic()+timeout
        while len(out) < n:
            if not select.select([self.p.stdout], [], [], max(0, end-time.monotonic()))[0]:
                raise TimeoutError("protocol read")
            data = os.read(self.p.stdout.fileno(), n-len(out))
            if not data:
                raise EOFError(out)
            out += data
        return out
    def write(self, data, chunk=65536):
        while data:
            n = os.write(self.p.stdin.fileno(), data[:chunk])
            data = data[n:]
    def ack(self):
        h = S.unpack("<4sBBHHH", self.read(12))
        assert h[0] == b"ACK2"
        return h, self.read(h[4])
    def configure(self, cfg=GOOD, chunk=65536):
        self.write(cfg, chunk)
        return self.ack()
    def request(self, seq, m, r, chunk=65536):
        self.write(S.pack("<4sQII", b"INP2", seq, len(m), len(r))+m+r, chunk)
        return self.reply()
    def reply(self):
        h = S.unpack("<4sBBHHHQQI", self.read(32))
        assert h[0] == b"RSP2"
        return h, self.read(h[4]), self.read(h[8])
    def ended(self, code=0):
        assert self.p.wait(timeout=2) == code
        assert self.read_eof() == b""
    def read_eof(self):
        return self.p.stdout.read()
    def close(self):
        if self.p.poll() is None:
            self.p.terminate()
            try:
                self.p.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.p.kill()
                self.p.wait(timeout=2)
        diagnostics = b"" if self.p.stderr.closed else self.p.stderr.read()
        for f in [self.p.stdin, self.p.stdout, self.p.stderr]:
            f.close()
        assert b"ERROR: AddressSanitizer" not in diagnostics and b"runtime error:" not in diagnostics, diagnostics

class RuntimeTests(unittest.TestCase):
    def child(self, *a, **kw):
        c = Child(*a, **kw)
        self.addCleanup(c.close)
        return c
    def accepted(self, c, cfg=GOOD):
        h, msg = c.configure(cfg)
        self.assertEqual((h[1], h[2], h[3], h[5]), (1, 1, 299, 0))
        self.assertIn(b"Synthetic only", msg)
        self.assertIn(b"factory qualification unavailable", msg)
    def terminal(self, c, code=523, seq=0):
        h, _, pcm = c.reply()
        self.assertEqual((h[1], h[2], h[3], h[5], h[6], h[7], h[8]), (3,1,code,0,seq,NO,0))
        self.assertEqual(pcm, b"")
        c.ended()
    def test_six_golden_runtime_policy(self):
        for f in sorted(FIX.glob("*.cfg2")):
            c = self.child()
            h, _ = c.configure(f.read_bytes())
            self.assertEqual((h[1], h[3]), (1,299) if f.read_bytes() == GOOD else (2,522), f.name)
            if h[1] == 2:
                c.ended()
    def test_all_pcm_maps_alignments_and_immutable_q30(self):
        for perm in itertools.permutations(range(4)):
            for ref in [(0,1), (1,0)]:
                for high in [False, True]:
                    c = self.child(maps=(",".join(map(str, perm)), ",".join(map(str, ref))))
                    cfg = GOOD
                    if high:
                        cfg = change(1, 9, "<H", 0x011f)
                    self.accepted(c, cfg)
                    previous = None
                    for seq in range(3):
                        m, r = input_pcm(seq, high)
                        before = hashlib.sha256(m+r).digest()
                        h, msg, pcm = c.request(seq, m, r)
                        self.assertEqual((h[2],h[3],h[4],h[5],h[6]), (0,0,0,0,seq))
                        self.assertEqual(msg, b"")
                        self.assertEqual((h[1],h[7],h[8]), (2,NO,0) if seq == 0 else (1,(seq-1)*320,640))
                        self.assertEqual(pcm, b"" if seq == 0 else previous)
                        previous = oracle(m,r,perm,ref,high)
                        self.assertEqual(hashlib.sha256(m+r).digest(), before)
                    c.close()
    def test_q30_does_not_modify_pcm_or_infer_unity(self):
        m, r = input_pcm()
        want = oracle(m,r)
        for values in [(1,2,3,4), (0x7fffffff,0x40000000,1,0x30000000)]:
            cfg = GOOD
            for i,v in enumerate(values):
                cfg = change(0x101,16+i*8,"<q",v,cfg)
            c = self.child()
            self.accepted(c,cfg)
            c.request(0,m,r)
            self.assertEqual(c.request(1,m,r)[2], want)
    def test_valid_codec_but_unsupported_runtime_shapes(self):
        # All these fields require independent validation beyond the board name.
        cases = [change(1,0,"<H",3), change(1,8,"<I",0x10000f01),
                 change(1,9,"<I",0x00170016), change(2,0,"<H",1), change(2,10,"<B",1)]
        for typ in [1,2]:
            items = []
            for t,f,v in tags():
                if t==typ:
                    v=bytearray(v)
                    S.pack_into("<HI",v,2,960,48000)
                    v=bytes(v)
                items.append((t,f,v))
            cases.append(packet(items))
        cases += [packet([x for x in tags() if x[0] != 3]),
                  change(3,1,"<B",2), change(3,4,"<6s",b"cronos"),
                  packet([x for x in tags() if x[0] != 0x101]),
                  change(0x101,3,"<B",2)]
        # Proper PARTIAL and NONE descriptors, rather than malformed metadata.
        items=tags();v=bytearray(items[-1][2]);v[3]=2;S.pack_into("<I",v,8,5);S.pack_into("<q",v,24,0);S.pack_into("<q",v,40,0)
        cases.append(packet(items[:-1]+[(0x101,0,bytes(v))]))
        v=S.pack("<HBBBBHII",1,0,0,0,0,4,0,0)
        cases.append(packet(items[:-1]+[(0x101,0,v)]))
        # Valid absent REF with matching stream_flags.
        cases.append(packet([(t,f,bytes(16) if t==2 else v) for t,f,v in tags()],1))
        for cfg in cases:
            c=self.child();h,_=c.configure(cfg);self.assertEqual((h[1],h[3]),(2,522));c.ended()
    def test_header_validation_before_payload_read(self):
        for off,fmt,values in [(4,"<H",[0,3]),(6,"<H",[15,40]),(8,"<I",[0,15,8193,0xffffffff]),
                               (12,"<I",[0,3,8,0xffffffff])]:
            for value in values:
                c=self.child();h=bytearray(GOOD[:16]);S.pack_into(fmt,h,off,value)
                # Keep stdin OPEN: invalid header must not wait for a body.
                c.write(h);a,_=c.ack();self.assertEqual((a[1],a[3]),(2,522));c.ended()
        c=self.child();a,_=c.configure(S.pack("<4sHHII",b"CFG2",2,16,16,7));self.assertEqual(a[1],2);c.ended()
    def test_all_golden_prefixes_terminal_reject(self):
        for f in FIX.glob("*.cfg2"):
            raw=f.read_bytes()
            for n in range(len(raw)):
                c=self.child();c.write(raw[:n]);c.p.stdin.close()
                h,_=c.ack();self.assertEqual((h[1],h[3]),(2,522),(f.name,n));c.ended();c.close()
    def test_unknown_optional_max8192_and_exact_next_message(self):
        m,r=input_pcm()
        for raw in [packet(tags()+[(0x200,0,b"ignored")]),
                    packet(tags()+[(0x200,0,bytes(8192-len(GOOD)-8))]),
                    packet(tags()+[(0x200+i,0,b"") for i in range(60)])]:
            c=self.child()
            # Pipeline next INP2; CFG reader must consume exactly total_bytes.
            c.write(raw+S.pack("<4sQII",b"INP2",0,len(m),len(r))+m+r)
            h,_=c.ack();self.assertEqual(h[1],1)
            self.assertEqual(c.reply()[0][1],2)
            self.assertEqual(c.request(1,m,r)[2],oracle(m,r))
        for raw in [packet(tags()+[(0x200,1,b"required")]),packet(tags()+[(0x200+i,0,b"") for i in range(61)]),
                    packet(tags()+[tags()[-1]]),packet(list(reversed(tags())))]:
            c=self.child();h,_=c.configure(raw);self.assertEqual((h[1],h[3]),(2,522));c.ended()
    def test_no_implicit_mode_or_legacy_downgrade(self):
        for args in [[],["--offline-replay","unused"],["--offline-synthetic-cfg2","0,0,2,3","0,1"],
                     ["--offline-synthetic-cfg2","0,1,2,3","1,1"],["--offline-synthetic-cfg2","extra"]]:
            c=self.child(args=args);h,_=c.ack();self.assertEqual((h[1],h[3]),(2,524));c.ended()
        c=self.child();h,_=c.configure(LEGACY);self.assertEqual((h[1],h[3]),(2,522));c.ended()
        c=self.child(binary="test-external-asp",args=[])
        h,_=c.configure(GOOD);self.assertEqual((h[1],h[3]),(2,524));c.ended()
    def test_short_syscalls_eintr_and_fragmented_host(self):
        c=self.child(binary="test-cfg2-synthetic-fragmented")
        h,_=c.configure(GOOD,1);self.assertEqual(h[1],1)
        for seq in range(4):
            m,r=input_pcm(seq)
            h,_,pcm=c.request(seq,m,r,7)
            self.assertEqual(h[6],seq)
            if seq:self.assertEqual(pcm,previous)
            previous=oracle(m,r)
    def test_terminal_sequence_lengths_repeat_config_and_truncation(self):
        m,r=input_pcm()
        bad=[S.pack("<4sQII",b"INP2",1,len(m),len(r)),S.pack("<4sQII",b"INP2",0,0xffffffff,len(r)),
             S.pack("<4sQII",b"INP2",0,len(m),0),GOOD[:20],b"X"*20]
        for data in bad:
            c=self.child();self.accepted(c);c.write(data);self.terminal(c)
        for data in [b"I",S.pack("<4sQII",b"INP2",0,len(m),len(r))+m[:17],
                     S.pack("<4sQII",b"INP2",0,len(m),len(r))+m+r[:17]]:
            c=self.child();self.accepted(c);c.write(data);c.p.stdin.close();self.terminal(c)
        c=self.child();self.accepted(c);c.request(0,m,r);c.write(S.pack("<4sQII",b"INP2",0,len(m),len(r)));self.terminal(c,seq=1)
        c=self.child();self.accepted(c);bad=S.pack("<i",8388608)+m[4:]
        c.write(S.pack("<4sQII",b"INP2",0,len(m),len(r))+bad+r);self.terminal(c,503)
        # Failure after successful DSP quanta must suppress all PCM for this request.
        c=self.child();self.accepted(c);c.request(0,m,r)
        bad=bytearray(m);S.pack_into("<i",bad,len(bad)-4,-8388609)
        c.write(S.pack("<4sQII",b"INP2",1,len(m),len(r))+bad+r);self.terminal(c,503,1)
    def test_backend_fatal_crash_hang_and_clean_restart(self):
        m,r=input_pcm()
        for fault in ["fatal","crash","hang"]:
            c=self.child(env={"ASP2_TEST_FAULT":fault});self.accepted(c)
            for seq in range(8):c.request(seq,m,r)
            c.write(S.pack("<4sQII",b"INP2",8,len(m),len(r))+m+r)
            if fault=="fatal":self.terminal(c,503,8)
            elif fault=="crash":c.ended(17)
            else:
                with self.assertRaises(TimeoutError):c.read(32,0.05)
                c.close()
            # New explicitly started session has zero sequence and NotReady.
            fresh=self.child();self.accepted(fresh);self.assertEqual(fresh.request(0,m,r)[0][1],2)
    def test_bounded_stress_timing_and_process_cleanup(self):
        before=len(list(Path("/proc/self/fd").iterdir()))
        m,r=input_pcm();want=oracle(m,r);times=[];rss=[]
        start=time.monotonic_ns();c=self.child();hello=time.monotonic_ns()-start
        self.assertLess(hello,500_000_000)
        start=time.monotonic_ns();self.accepted(c);self.assertEqual(c.request(0,m,r)[0][1],2)
        first=time.monotonic_ns()-start
        for seq in range(1,2001):
            start=time.monotonic_ns();h,_,pcm=c.request(seq,m,r);times.append(time.monotonic_ns()-start)
            self.assertEqual((h[6],h[7],pcm),(seq,(seq-1)*320,want))
            if seq%500==0:rss.append(next(int(x.split()[1]) for x in Path(f"/proc/{c.p.pid}/status").read_text().splitlines() if x.startswith("VmRSS:")))
        c.p.stdin.close();c.ended();c.close()
        for _ in range(32):
            c=Child();self.accepted(c);c.request(0,m,r);c.close()
        after=len(list(Path("/proc/self/fd").iterdir()))
        self.assertLessEqual(after,before+1)
        # ASan lazily populates its shadow/runtime pages; only the native build
        # has the fixed-RSS guard. Sanitized runs still log the measurements.
        if os.getenv("ASP2_CFG2_SANITIZED") != "1":
            self.assertLessEqual(max(rss)-min(rss),64)
        times.sort()
        report={"backend":"SYNTHETIC ONLY","hello_ns":hello,"cfg_ack_first_ns":first,"exchanges":2001,
                "p50_ns":times[1000],"p99_ns":times[1980],"max_ns":max(times),
                "over25ms":sum(x>25_000_000 for x in times),"rss_kib":rss,"fd_before":before,"fd_after":after}
        print(json.dumps(report),flush=True)
        out=os.getenv("ASP2_EVIDENCE_DIR")
        if out:Path(out,"runtime_metrics_sanitized.json" if os.getenv("ASP2_CFG2_SANITIZED")=="1" else "runtime_metrics.json").write_text(json.dumps(report,indent=2)+"\n")

if __name__=="__main__":
    unittest.main(verbosity=2)

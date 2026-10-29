"""Standalone synthetic source tests. Never claims factory DSP execution.
Set ASP2_BUILD_DIR and ASP2_TEST_DIR outside the source tree. No live hardware.
"""
import os,sys,pathlib,unittest,ctypes as C,struct as S,subprocess,time,select,json,hashlib,itertools,statistics
BUILD=pathlib.Path(os.environ['ASP2_BUILD_DIR']); ROOT=pathlib.Path(os.environ['ASP2_TEST_DIR'])
ROOT.mkdir(parents=True,exist_ok=True)
BIN=BUILD/'test-external-asp'; LIB=C.CDLL(str(BUILD/'libbridge-test.so'))
MIC=S.pack('<4i',17*256,-257,8388607,-8388608)*1920
REF=S.pack('<2h',-32768,32767)*1920
class Profile(C.Structure):_fields_=[('mic',C.c_int*4),('ref',C.c_int*2),('experiment',C.c_int)]
LIB.parse_profile.argtypes=[C.c_char_p,C.POINTER(Profile),C.c_void_p]
LIB.prepare_frame.argtypes=[C.POINTER(Profile),C.c_void_p,C.c_void_p,C.c_uint,C.c_int,C.c_void_p]
LIB.secure_open.argtypes=[C.c_char_p,C.c_int]
LIB.sha256_bytes.argtypes=[C.c_void_p,C.c_size_t,C.c_void_p]
def profile(name='profile',mic='0,1,2,3',ref='0,1'):
 p=ROOT/name;p.write_text('ASP2-ATHENA-OFFLINE-V1\nmic='+mic+'\nref='+ref+'\ncalibration=libasp-unverified\nmanifest=/unused/test-manifest\n');p.chmod(0o600);return p
from test_cfg2_runtime import Child, GOOD, oracle
class Tests(unittest.TestCase):
 def child(self,*args,**kwargs):
  c=Child(*args,**kwargs);self.addCleanup(c.close);return c
 def test_profile_permutations_and_bad_maps(self):
  for perm in itertools.permutations(range(4)):
   p=profile('p',','.join(map(str,perm)),'1,0');out=Profile();buf=C.create_string_buffer(256)
   self.assertEqual(LIB.parse_profile(str(p).encode(),C.byref(out),buf),0)
   self.assertEqual(list(out.mic),list(perm));self.assertEqual(list(out.ref),[1,0])
  for m,r in [('0,0,2,3','0,1'),('-1,1,2,3','0,1'),('0,1,2,4','0,1'),('0,1,2','0,1'),('','0,1'),('0,1,2,3','0,0'),('0,1,2,3','-1,0')]:
   p=profile('bad',m,r);self.assertNotEqual(LIB.parse_profile(str(p).encode(),C.byref(Profile()),C.create_string_buffer(256)),0)
 def test_signed_scales_mapping_reference(self):
  p=Profile((2,0,3,1),(1,0),1)
  vals=[-8388608,-257,-1,0,1,257,8388607]
  for v in vals:
   low=S.pack('<4i',v,257,-257,-1);high=S.pack('<4i',v*256,257*256,-257*256,-256)
   want=[-257,v,-1,257,2147418112,-2147483648]
   for data,alignment in [(low,0),(high,1)]:
    out=(C.c_int32*6)();self.assertEqual(LIB.prepare_frame(C.byref(p),data,S.pack('<2h',-32768,32767),0,alignment,out),0);self.assertEqual(list(out),want)
  out=(C.c_int32*6)();self.assertNotEqual(LIB.prepare_frame(C.byref(p),S.pack('<4i',8388608,0,0,0),REF,0,0,out),0)
 def test_profile_security(self):
  p=profile('security');buf=C.create_string_buffer(256);out=Profile()
  self.assertEqual(LIB.parse_profile(str(p).encode(),C.byref(out),buf),0)
  p.chmod(0o666)
  self.assertNotEqual(LIB.parse_profile(str(p).encode(),C.byref(out),buf),0)
  p.chmod(0o600)
  sy=ROOT/'symlink'
  if sy.exists():sy.unlink()
  sy.symlink_to(p)
  self.assertNotEqual(LIB.parse_profile(str(sy).encode(),C.byref(out),buf),0)
 def test_full_width_sample_id_fifo_100k(self):
  subprocess.run([str(BUILD/"test-fifo")],check=True,timeout=60)
 def test_sha256_known_vectors(self):
  for b in [b'',b'abc',b'x'*100000]:
   out=C.create_string_buffer(32);LIB.sha256_bytes(b,len(b),out);self.assertEqual(out.raw,hashlib.sha256(b).digest())
 def test_factory_admission_closed(self):
  c=Child(binary="external-asp-host-diagnostic",args=[])
  self.addCleanup(c.close)
  h,_=c.configure(GOOD)
  self.assertEqual((h[1],h[3]),(2,575));c.ended()
 def test_long_real_protocol(self):
  if os.getenv('ASP2_LONG')!='1':self.skipTest('explicit 100k stress')
  c=self.child();self.assertEqual(c.configure(GOOD)[0][1],1);expected=oracle(MIC,REF);times=[];rss=[];start=time.monotonic()
  for seq in range(100000):
   tick=time.monotonic_ns();h,_,pcm=c.request(seq,MIC,REF);times.append(time.monotonic_ns()-tick)
   self.assertEqual(h[6],seq)
   if seq:self.assertEqual((h[1],h[7],pcm),(1,(seq-1)*320,expected))
   else:self.assertEqual(h[1],2)
   if seq%10000==0:
    rss.append(next(int(l.split()[1]) for l in pathlib.Path('/proc/%d/status'%c.p.pid).read_text().splitlines() if l.startswith('VmRSS:')))
  times.sort();result={'frames':100000,'emitted_samples':99999*320,'native_quanta':250000,'pending_samples':320,'p50_ns':times[50000],'p95_ns':times[95000],'p99_ns':times[99000],'max_ns':times[-1],'over25ms':sum(x>25000000 for x in times),'rss_kib':rss,'seconds':time.monotonic()-start,'backend':'SYNTHETIC ONLY'}
  (ROOT/'long-result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)
if __name__=='__main__':unittest.main(verbosity=2)

"""F1-B independent factory ABI pipes, oracle and cleanup. Synthetic data only."""
import os
import signal
import unittest
import test_cfg2_runtime as rt

BaseChild = rt.Child
class FactoryChild(BaseChild):
    def __init__(self, binary="test-cfg2-synthetic", maps=(), args=None, env=None):
        binary = binary.replace("test-cfg2-synthetic", "test-cfg2-factory-mock")
        if args is None:
            args = ["--offline-factory-mock-cfg2", *maps]
        else:
            args = [s.replace("--offline-synthetic-cfg2", "--offline-factory-mock-cfg2") for s in args]
        super().__init__(binary, maps, args, {"ASP2_MOCK_TRACE":"1", **(env or {})})

# Reuse the existing wire corpus and independently written Python numerical
# oracle against a different C backend. Keep F1-A source/tests unchanged.
rt.Child = FactoryChild
class FactoryRuntimeTests(rt.RuntimeTests):
    def accepted(self, c, cfg=rt.GOOD):
        h,msg=c.configure(cfg)
        self.assertEqual((h[1],h[2],h[3],h[5]),(1,1,299,0))
        self.assertEqual(msg,b"Experimental factory mock; unqualified")
    def lifecycle(self,c,want,code=0):
        c.p.stdin.close()
        c.ended(code)
        diag=c.p.stderr.read()
        self.assertIn(want,diag)
        self.assertIn(b"violations=0",diag)
        self.assertNotIn(b"runtime error:",diag)
        self.assertNotIn(b"ERROR: AddressSanitizer",diag)
    def test_missing_abi_and_startup_failure(self):
        for part in ["init","create","ref","process","destroy","deinit"]:
            c=self.child(env={"ASP2_TEST_FAULT":"missing-"+part})
            h,_=c.ack()
            self.assertEqual((h[1],h[3]),(2,524))
            c.ended()
        for fault,want in [("init",None),("create",b"lifecycle=ICX"),
                           ("ref",b"lifecycle=ICRDX")]:
            c=self.child(env={"ASP2_TEST_FAULT":fault})
            h,_=c.ack();self.assertEqual((h[1],h[3]),(2,524))
            if want:self.lifecycle(c,want)
            else:c.ended()
    def test_process_counts_and_each_guard_terminal(self):
        m,r=rt.input_pcm()
        for fault in ["process","partial-in","partial-out","input-before","input-after",
                      "input-mutate","output-before","output-after"]:
            c=self.child(env={"ASP2_TEST_FAULT":fault,"ASP2_MOCK_FAIL_AT":"3"})
            self.accepted(c);c.request(0,m,r)
            # Quantum 2 succeeds earlier in the same request; quantum 3 fails.
            h,_,pcm=c.request(1,m,r)
            self.assertEqual((h[1],h[3],h[6],h[7],pcm),(3,503,1,rt.NO,b""))
            self.lifecycle(c,b"lifecycle=ICRPDX")
    def test_eof_reject_destroy_and_repeated_cancellation(self):
        m,r=rt.input_pcm()
        c=self.child();self.accepted(c);c.request(0,m,r)
        self.lifecycle(c,b"lifecycle=ICRPDX")
        c=self.child();c.configure(rt.change(3,1,"<B",2))
        self.lifecycle(c,b"lifecycle=ICRDX")
        c=self.child(env={"ASP2_TEST_FAULT":"destroy"});self.accepted(c)
        self.lifecycle(c,b"lifecycle=ICRDX",2)
        for sig in [signal.SIGTERM,signal.SIGINT]:
            for _ in range(8):
                c=self.child();self.accepted(c);c.request(0,m,r)
                c.p.send_signal(sig)
                self.lifecycle(c,b"lifecycle=ICRPDX")
        # Cancellation inside asp_process hang must return to synchronous teardown.
        c=self.child(env={"ASP2_TEST_FAULT":"hang","ASP2_MOCK_FAIL_AT":"0"})
        self.accepted(c)
        c.write(rt.S.pack("<4sQII",b"INP2",0,len(m),len(r))+m+r)
        with self.assertRaises(TimeoutError):c.read(32,0.03)
        c.p.terminate();self.lifecycle(c,b"lifecycle=ICRPDX")
        c=self.child();self.accepted(c)
        c.write(rt.S.pack("<4sQII",b"INP2",0,len(m),len(r))+m[:17])
        c.p.terminate()
        self.assertEqual(c.p.wait(timeout=2),0)
        self.assertIn(b"lifecycle=ICRDX",c.p.stderr.read())
        c=self.child();c.p.stdout.close();c.write(rt.GOOD)
        self.assertEqual(c.p.wait(timeout=2),0)
        self.assertIn(b"lifecycle=ICRDX",c.p.stderr.read())
    def test_unexpected_stdout_and_no_synthetic_selector(self):
        c=self.child(env={"ASP2_MOCK_CHATTER":"1"})
        self.accepted(c)
        m,r=rt.input_pcm();c.request(0,m,r)
        self.assertEqual(c.request(1,m,r)[2],rt.oracle(m,r))
        c.p.stdin.close();c.ended()
        self.assertIn(b"Mock vendor stdout chatter",c.p.stderr.read())
        c=BaseChild(binary="test-cfg2-factory-mock",args=["--offline-synthetic-cfg2"])
        self.addCleanup(c.close)
        h,_=c.ack();self.assertEqual((h[1],h[3]),(2,524));c.ended()

if __name__=="__main__":
    unittest.main(verbosity=2)

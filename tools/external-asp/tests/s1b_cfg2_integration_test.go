// Loaded by Go -overlay into pinned S1-B; the TECHO5 checkout is read-only.
package mic

import (
	"bytes"
	"context"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"testing"
	"time"

	"github.com/HuskerMinion/techo5/echod/internal/asp"
)

func f1aCommand(t *testing.T, binary string, maps []string, fault string) *exec.Cmd {
	t.Helper()
	build := os.Getenv("ASP2_BUILD_DIR")
	if build == "" {
		t.Fatal("ASP2_BUILD_DIR required")
	}
	cmd := exec.Command(filepath.Join(build, binary), append([]string{"--offline-synthetic-cfg2"}, maps...)...)
	cmd.Env = []string{"LANG=C", "LC_ALL=C", "ASP2_TEST_FAULT=" + fault}
	return cmd
}
func f1aStart(t *testing.T, cmd *exec.Cmd, c asp.Config, session sessionCFG2) *externalASP {
	t.Helper()
	start := time.Now()
	f, err := startExternalASP(context.Background(), cmd, c, session)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { hostCFG2Reaped(t, f) })
	t.Logf("HELLO=%v budget=500ms", time.Since(start))
	return f
}
func f1aOracle(i asp.Input, micmap [4]int, refmap [2]int) []int16 {
	out := make([]int16, 320)
	for j := range out {
		hash := uint32(2166136261)
		for frame := j * 6; frame < j*6+6; frame++ {
			for _, slot := range micmap {
				v := int32(binary.LittleEndian.Uint32(i.Mic[frame*16+slot*4:]))
				if i.Config.Mic.Alignment == asp.High {
					v >>= 8
				}
				hash = (hash ^ uint32(v)) * 16777619
			}
			for _, slot := range refmap {
				v := int32(int16(binary.LittleEndian.Uint16(i.Ref[frame*4+slot*2:]))) * 65536
				hash = (hash ^ uint32(v)) * 16777619
			}
		}
		out[j] = int16(uint16(hash ^ (hash >> 16)))
	}
	return out
}
func TestF1ACFG2RealCHost(t *testing.T) {
	for _, bits := range []uint32{23, 31} {
		for _, binary := range []string{"test-cfg2-synthetic", "test-cfg2-synthetic-fragmented"} {
			for _, mapped := range []bool{false, true} {
				t.Run(fmt.Sprint(bits, "/", binary, "/", mapped), func(t *testing.T) {
					c := nativePattern(bits, 0).input().Config
					g := cfg2Gain(4, 15, asp.FactoryGainComplete)
					session := hostCFG2Session(t, c, confirmedFactoryAthena(), g)
					snapshot := session.Bytes()
					micmap, refmap := [4]int{0, 1, 2, 3}, [2]int{0, 1}
					var maps []string
					if mapped {
						maps = []string{"2,0,3,1", "1,0"}
						micmap = [4]int{2, 0, 3, 1}
						refmap = [2]int{1, 0}
					}
					f := f1aStart(t, f1aCommand(t, binary, maps, ""), c, session)
					g.Coefficients[0] = 1 // host and C both own their session snapshot
					var previous []int16
					max := time.Duration(0)
					for seq := uint64(0); seq < 32; seq++ {
						i := nativePattern(bits, int(seq)).input()
						m, r := bytes.Clone(i.Mic), bytes.Clone(i.Ref)
						start := time.Now()
						got, err := f.exchange(i)
						elapsed := time.Since(start)
						if elapsed > max {
							max = elapsed
						}
						if err != nil {
							t.Fatalf("seq=%d: %v", seq, err)
						}
						if got.Sequence != seq {
							t.Fatal("sequence", got.Sequence)
						}
						if seq == 0 {
							if got.Type != asp.NotReady || got.Start != asp.NoSample || len(got.PCM) != 0 ||
								got.ConfigStatus.Code != 299 || got.ConfigStatus.Message != "Synthetic only; factory qualification unavailable" {
								t.Fatal("initial metadata", got)
							}
						} else if got.Type != asp.Data || got.Start != (seq-1)*320 || !slices.Equal(got.PCM, previous) || got.ConfigStatus.Present() {
							t.Fatalf("seq=%d PCM/origin/status mismatch", seq)
						}
						previous = f1aOracle(i, micmap, refmap)
						if !bytes.Equal(m, i.Mic) || !bytes.Equal(r, i.Ref) || !bytes.Equal(snapshot, session.Bytes()) {
							t.Fatal("raw PCM or metadata mutated")
						}
					}
					t.Logf("32 exchanges; max=%v; production host budget=25ms; exact oracle PASS", max)
				})
			}
		}
	}
}
func TestF1ACFG2RealCRejectionAndFaults(t *testing.T) {
	c := nativePattern(23, 0).input().Config
	for _, avail := range []asp.FactoryGainAvailability{asp.FactoryGainNone, asp.FactoryGainPartial} {
		t.Run(fmt.Sprint("reject/", avail), func(t *testing.T) {
			mask := uint32(0)
			if avail == asp.FactoryGainPartial {
				mask = 5
			}
			session := hostCFG2Session(t, c, confirmedFactoryAthena(), cfg2Gain(4, mask, avail))
			f := f1aStart(t, f1aCommand(t, "test-cfg2-synthetic", nil, ""), c, session)
			got, err := f.exchange(nativePattern(23, 0).input())
			var term *asp.Terminal
			if !errors.As(err, &term) || term.Status.Code != 522 || !term.Configuration || len(got.PCM) != 0 {
				t.Fatal("configuration terminal", err)
			}
		})
	}
	for _, fault := range []string{"fatal", "crash", "hang"} {
		t.Run(fault, func(t *testing.T) {
			session := hostCFG2Session(t, c, confirmedFactoryAthena(), cfg2Gain(4, 15, asp.FactoryGainComplete))
			f := f1aStart(t, f1aCommand(t, "test-cfg2-synthetic", nil, fault), c, session)
			for seq := 0; seq < 8; seq++ {
				if _, err := f.exchange(nativePattern(23, seq).input()); err != nil {
					t.Fatal(seq, err)
				}
			}
			start := time.Now()
			got, err := f.exchange(nativePattern(23, 8).input())
			elapsed := time.Since(start)
			if err == nil || len(got.PCM) != 0 {
				t.Fatal("fault accepted")
			}
			if fault == "fatal" {
				var term *asp.Terminal
				if !errors.As(err, &term) || term.Status.Code != 503 || term.Configuration {
					t.Fatal("terminal metadata", err)
				}
			}
			if fault == "hang" && (!errors.Is(err, errASPTimeout) || elapsed < 20*time.Millisecond || elapsed > 250*time.Millisecond) {
				t.Fatal("deadline", elapsed, err)
			}
			hostCFG2Reaped(t, f)
			t.Logf("%s elapsed=%v; no PCM; direct child reaped", fault, elapsed)
		})
	}
	// Both mismatched formats fail; HELLO never negotiates or retries.
	t.Run("fixed-packet-rejected", func(t *testing.T) {
		cmd := f1aCommand(t, "test-cfg2-synthetic", nil, "")
		in, err := cmd.StdinPipe()
		if err != nil {
			t.Fatal(err)
		}
		out, err := cmd.StdoutPipe()
		if err != nil {
			t.Fatal(err)
		}
		if err = cmd.Start(); err != nil {
			t.Fatal(err)
		}
		defer func() {
			in.Close()
			out.Close()
			if cmd.Process != nil {
				cmd.Process.Kill()
			}
			cmd.Wait()
		}()
		var hello [4]byte
		if _, err = io.ReadFull(out, hello[:]); err != nil || string(hello[:]) != "ASP2" {
			t.Fatal(err)
		}
		if err = asp.WriteAll(in, rejectedCFG2(t)); err != nil {
			t.Fatal(err)
		}
		_, err = asp.ReadResult(out)
		var term *asp.Terminal
		if !errors.As(err, &term) || term.Status.Code != 522 {
			t.Fatal("fixed packet accepted", err)
		}
	})
}

// Actual FrankenASP ELF under the same FD-pinned supervised launch as production.
// The selector enables an explicit offline backend, never a wire version.
func TestF1ACFG2PinnedCChildren(t *testing.T) {
	for _, tc := range []struct{ binary, selector string }{
		{"test-cfg2-synthetic", "--offline-synthetic-cfg2"},
	} {
		t.Run(tc.binary, func(t *testing.T) {
			fixture := newASPProbeFixture(t, aspProbe{path: filepath.Join(os.Getenv("ASP2_BUILD_DIR"), tc.binary)}, "unused synthetic assets")
			candidate := discoverASPCandidate(fixture.open, true)
			pin, err := fixture.open()
			if err != nil {
				t.Fatal(err)
			}
			c := nativeASPConfig(31)
			session := hostCFG2Session(t, c, confirmedFactoryAthena(), cfg2Gain(4, 15, asp.FactoryGainComplete))
			f, err := startASPCandidate(context.Background(), candidate, &externalASP{config: c, session: session}, func() (*secureASPPinned, error) { return pin, nil })
			// Production uses no arguments; these fixture-only children require a
			// backend selector, so the no-argument launch must reject admission.
			if err != nil {
				t.Fatal(err)
			}
			_, err = f.exchange(nativePattern(31, 0).input())
			var terminal *asp.Terminal
			if !((errors.As(err, &terminal) && terminal.Status.Code == 524) || errors.Is(err, errASPExited)) {
				t.Fatal("implicit test backend admission", err)
			}
			hostCFG2Reaped(t, f)
			assertASPConsumed(t, pin)
			pin, err = fixture.open()
			if err != nil {
				t.Fatal(err)
			}
			f, err = startExternalASPPinnedAtProcFD(context.Background(), pin, &externalASP{config: c, session: session}, "/proc/self/fd/3", []string{tc.selector})
			if err != nil {
				t.Fatal(err)
			}
			defer hostCFG2Reaped(t, f)
			assertASPConsumed(t, pin)
			if f.cmd.Path != "/proc/self/fd/3" || len(f.cmd.ExtraFiles) != 0 {
				t.Fatal("lost FD-pinned launch")
			}
			var previous []int16
			for seq := uint64(0); seq < 8; seq++ {
				input := nativePattern(31, int(seq)).input()
				beforeMic, beforeRef := bytes.Clone(input.Mic), bytes.Clone(input.Ref)
				got, err := f.exchange(input)
				if err != nil {
					t.Fatal(seq, err)
				}
				if seq == 0 {
					if got.Type != asp.NotReady {
						t.Fatal("initial FIFO origin")
					}
				} else if got.Start != (seq-1)*320 || !slices.Equal(got.PCM, previous) {
					t.Fatal("pinned C PCM/origin mismatch")
				}
				previous = f1aOracle(input, [4]int{0, 1, 2, 3}, [2]int{0, 1})
				if !bytes.Equal(beforeMic, input.Mic) || !bytes.Equal(beforeRef, input.Ref) {
					t.Fatal("raw MIC/REF mutated")
				}
			}
		})
	}
}

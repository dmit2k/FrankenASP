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
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/HuskerMinion/techo5/echod/internal/asp"
	"github.com/HuskerMinion/techo5/echod/internal/config"
)

func f1bCommand(t *testing.T, binary string, maps []string, fault string) *exec.Cmd {
	t.Helper()
	build := os.Getenv("ASP2_BUILD_DIR")
	if build == "" {
		t.Fatal("ASP2_BUILD_DIR required")
	}
	cmd := exec.Command(filepath.Join(build, binary), append([]string{"--offline-factory-mock-cfg2"}, maps...)...)
	cmd.Env = []string{"LANG=C", "LC_ALL=C", "ASP2_TEST_FAULT=" + fault}
	return cmd
}
func f1bStart(t *testing.T, cmd *exec.Cmd, c asp.Config, session sessionCFG2) *externalASP {
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
func f1bOracle(i asp.Input, micmap [4]int, refmap [2]int) []int16 {
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
func TestF1BCFG2RealCHost(t *testing.T) {
	for _, bits := range []uint32{23, 31} {
		for _, binary := range []string{"test-cfg2-factory-mock", "test-cfg2-factory-mock-fragmented"} {
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
					f := f1bStart(t, f1bCommand(t, binary, maps, ""), c, session)
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
								got.ConfigStatus.Code != 299 || got.ConfigStatus.Message != "Experimental factory mock; unqualified" {
								t.Fatal("initial metadata", got)
							}
						} else if got.Type != asp.Data || got.Start != (seq-1)*320 || !slices.Equal(got.PCM, previous) || got.ConfigStatus.Present() {
							t.Fatalf("seq=%d PCM/origin/status mismatch", seq)
						}
						previous = f1bOracle(i, micmap, refmap)
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
func TestF1BCFG2RealCRejectionAndFaults(t *testing.T) {
	c := nativePattern(23, 0).input().Config
	for _, avail := range []asp.FactoryGainAvailability{asp.FactoryGainNone, asp.FactoryGainPartial} {
		t.Run(fmt.Sprint("reject/", avail), func(t *testing.T) {
			mask := uint32(0)
			if avail == asp.FactoryGainPartial {
				mask = 5
			}
			session := hostCFG2Session(t, c, confirmedFactoryAthena(), cfg2Gain(4, mask, avail))
			f := f1bStart(t, f1bCommand(t, "test-cfg2-factory-mock", nil, ""), c, session)
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
			f := f1bStart(t, f1bCommand(t, "test-cfg2-factory-mock", nil, fault), c, session)
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
		cmd := f1bCommand(t, "test-cfg2-factory-mock", nil, "")
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

// Real Source orchestration must return current stock on the first failed tick.
func TestF1BFactoryStockFallback(t *testing.T) {
	for _, fault := range []string{"fatal", "crash", "hang", "partial-in", "output-after"} {
		t.Run(fault, func(t *testing.T) {
			s := controlSource(t, "normal", config.ASPExternal)
			c := nativePattern(31, 0).input().Config
			session := hostCFG2Session(t, c, confirmedFactoryAthena(), cfg2Gain(4, 15, asp.FactoryGainComplete))
			var starts atomic.Int32
			s.aspStart = func(ctx context.Context) (*externalASP, error) {
				starts.Add(1)
				return startExternalASP(ctx, f1bCommand(t, "test-cfg2-factory-mock", nil, fault), c, session)
			}
			s.SetASP(config.ASPExternal)
			waitASPChild(t, s)
			f := s.asp
			t.Cleanup(func() { s.SetASP(config.ASPBuiltin); hostCFG2Reaped(t, f) })
			ch, stop := s.Listen("F1-B factory fallback")
			defer stop()
			stock := testSource()
			for tick := 0; tick < 12; tick++ {
				raw := rawFrame(tick, false)
				stock.broadcast(bytes.Clone(raw))
				s.broadcastNative(bytes.Clone(raw), nativePattern(31, tick))
				got := <-ch
				if tick < 4 || tick >= 8 {
					if !slices.Equal(got, stock.Recent(20*time.Millisecond)) {
						t.Fatal("not current stock", tick)
					}
				}
				if (s.ASPStatus().Active == config.ASPExternal) != (tick >= 4 && tick < 8) {
					t.Fatal("activation/fallback tick", tick, s.ASPStatus())
				}
			}
			st := s.ASPStatus()
			if s.asp != nil || !f.broken.Load() || !st.Confirmed || starts.Load() != 1 {
				t.Fatal("supervision", st, starts.Load())
			}
			if !strings.Contains(st.Debug, "Fallback:") && !strings.Contains(st.Debug, "503:") {
				t.Fatal("failure lost", st)
			}
			hostCFG2Reaped(t, f)
			s.SetASP(config.ASPExternal)
			if starts.Load() != 1 || s.ASPStatus() != st {
				t.Fatal("implicit restart")
			}
		})
	}
}

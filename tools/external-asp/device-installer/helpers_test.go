package main

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"golang.org/x/sys/unix"
)

func fakeProcess(t *testing.T, proc string, pid, parent int, exe, root, namespace string) string {
	t.Helper()
	p := fmt.Sprintf("%s/%d", proc, pid)
	for _, d := range []string{p + "/fd", p + "/ns"} {
		if e := os.MkdirAll(d, 0700); e != nil {
			t.Fatal(e)
		}
	}
	for n, target := range map[string]string{"exe": exe, "cwd": "/", "root": root} {
		if e := os.Symlink(target, p+"/"+n); e != nil {
			t.Fatal(e)
		}
	}
	if namespace == "" {
		namespace = proc + "/self/ns/mnt"
	}
	if e := os.Link(namespace, p+"/ns/mnt"); e != nil {
		t.Fatal(e)
	}
	setStat(t, p, parent, "123", "S")
	os.WriteFile(p+"/comm", []byte("external-asp"), 0600)
	os.WriteFile(p+"/maps", nil, 0600)
	os.WriteFile(p+"/mountinfo", []byte("1 0 0:1 / / rw - ext4 root rw\n"), 0600)
	return p
}
func setStat(t *testing.T, p string, parent int, start, state string) {
	t.Helper()
	v := []string{state, fmt.Sprint(parent)}
	for j := 0; j < 17; j++ {
		v = append(v, "0")
	}
	v = append(v, start)
	if e := os.WriteFile(p+"/stat", []byte(filepath.Base(p)+" (name with spaces) "+strings.Join(v, " ")), 0600); e != nil {
		t.Fatal(e)
	}
}
func helperFixture(t *testing.T) (*installer, string) {
	i := localInstaller(t)
	installFixture(t, i)
	foreign := i.base + "/stock-techo5"
	os.WriteFile(foreign, []byte("SYNTHETIC STOCK"), 0500)
	return i, foreign
}
func TestStockAndUnrelatedNamesNeverKillAuthority(t *testing.T) {
	i, stock := helperFixture(t)
	p := fakeProcess(t, i.proc, 50, 1, stock, "/", "")
	os.WriteFile(p+"/comm", []byte("techo5"), 0600)
	p = fakeProcess(t, i.proc, 51, 1, stock, "/", "")
	os.WriteFile(p+"/comm", []byte("external-asp"), 0600)
	pl := scan([]string{i.dest}, i.proc, true, nil)
	if len(pl.Targets) != 0 || len(pl.Hosts) != 1 || len(pl.Unrelated) != 1 || len(pl.Blocked) != 0 {
		t.Fatalf("%+v", pl)
	}
	accepts(t, func() any { activeCheck([]string{i.dest}, i.proc, true); return nil })
	// All transactions must remain possible with stock present.
	first := current(i.discover(i.readRegistry()))
	second := installFixture(t, i)
	i.o.Generation = first
	accepts(t, func() any { return i.mutate(false) })
	accepts(t, func() any { return i.mutate(true) })
	i.o.Generation = second
	accepts(t, func() any { return i.mutate(true) })
	if _, e := os.Stat(fmt.Sprintf("%s/50/stat", i.proc)); e != nil {
		t.Fatal("stock modified")
	}
}
func TestOwnedHelperAndOrphanChild(t *testing.T) {
	i, _ := helperFixture(t)
	fakeProcess(t, i.proc, 100, 1, i.dest+"/bin/external-asp", "/", "")
	ns := i.base + "/private-ns"
	os.WriteFile(ns, []byte("private"), 0600)
	fakeProcess(t, i.proc, 101, 1, i.dest+"/"+rootfs+"/factory/asp2-child", i.dest+"/"+rootfs, ns)
	pl := scan([]string{i.dest}, i.proc, true, nil)
	if len(pl.Targets) != 2 {
		t.Fatal(pl)
	}
	for _, p := range pl.Targets {
		if !strings.HasPrefix(p.Role, "orphan-") {
			t.Fatal(p.Role)
		}
	}
	refuses(t, "active pinned", func() any { return i.install(fixture()) })
}
func TestPIDParentExeRootNamespaceReuse(t *testing.T) {
	for _, change := range []string{"pid", "parent", "exe", "root", "namespace"} {
		t.Run(change, func(t *testing.T) {
			i, stock := helperFixture(t)
			p := fakeProcess(t, i.proc, 100, 1, i.dest+"/bin/external-asp", "/", "")
			old := snapshot(i.proc, 100)
			switch change {
			case "pid":
				setStat(t, p, 1, "124", "S")
			case "parent":
				setStat(t, p, 55, "123", "S")
			case "exe":
				os.Remove(p + "/exe")
				os.Symlink(stock, p+"/exe")
			case "root":
				os.Remove(p + "/root")
				os.Symlink(i.dest+"/"+rootfs, p+"/root")
			case "namespace":
				os.Remove(p + "/ns/mnt")
				os.WriteFile(p+"/ns/mnt", []byte("new ns"), 0600)
			}
			refuses(t, "identity changed", func() any { return sameProcess(old, i.proc) })
		})
	}
}
func TestZombieAndDisappearedHelper(t *testing.T) {
	i, _ := helperFixture(t)
	p := fakeProcess(t, i.proc, 100, 1, i.dest+"/bin/external-asp", "/", "")
	old := snapshot(i.proc, 100)
	setStat(t, p, 1, "123", "Z")
	if sameProcess(old, i.proc) {
		t.Fatal("zombie alive")
	}
	os.RemoveAll(p)
	if sameProcess(old, i.proc) {
		t.Fatal("gone alive")
	}
}
func TestAllPinnedReferenceKindsBlock(t *testing.T) {
	for _, kind := range []string{"fd", "cwd", "root", "map", "mount"} {
		t.Run(kind, func(t *testing.T) {
			i, foreign := helperFixture(t)
			p := fakeProcess(t, i.proc, 100, 1, foreign, "/", "")
			switch kind {
			case "fd":
				os.Symlink(i.dest, p+"/fd/4")
			case "cwd":
				os.Remove(p + "/cwd")
				os.Symlink(i.dest, p+"/cwd")
			case "root":
				os.Remove(p + "/root")
				os.Symlink(i.dest+"/"+rootfs, p+"/root")
			case "map":
				os.WriteFile(p+"/maps", []byte("1-2 r-xp 0 0:1 1 "+i.dest+"/bin/external-asp\n"), 0600)
			case "mount":
				os.WriteFile(p+"/mountinfo", []byte("2 1 0:1 / "+i.dest+"/"+rootfs+"/sys ro - sysfs sysfs ro\n"), 0600)
			}
			refuses(t, "active pinned", func() any { activeCheck([]string{i.dest}, i.proc, true); return nil })
		})
	}
}
func TestR1ParentFDPipeProof(t *testing.T) {
	for _, kind := range []string{"launcher", "child", "missingpipe", "unselected"} {
		t.Run(kind, func(t *testing.T) {
			i, host := helperFixture(t)
			other := i.base + "/other"
			os.Mkdir(other, 0700)
			stageTree(other, fixture())
			hp := fakeProcess(t, i.proc, 50, 1, host, "/", "")
			exe := other + "/bin/external-asp"
			root := "/"
			ns := ""
			if kind == "child" {
				exe = other + "/" + rootfs + "/factory/asp2-child"
				root = other + "/" + rootfs
				ns = i.base + "/private-ns"
				os.WriteFile(ns, []byte("ns"), 0600)
			}
			p := fakeProcess(t, i.proc, 100, 50, exe, root, ns)
			if kind != "child" {
				os.Symlink(exe, p+"/fd/3")
				os.Symlink(other, p+"/fd/4")
			}
			for fd, target := range map[string]string{"0": "pipe:[12345]", "9": "pipe:[12346]"} {
				os.Symlink(target, p+"/fd/"+fd)
				os.Symlink(target, hp+"/fd/"+fd)
			}
			if kind == "missingpipe" {
				os.Remove(p + "/fd/9")
			}
			hosts := []string{host}
			if kind == "unselected" {
				hosts = nil
			}
			pl := scan([]string{i.dest}, i.proc, true, hosts)
			if kind == "launcher" || kind == "child" {
				if len(pl.Targets) != 1 || pl.Targets[0].Generation != other {
					t.Fatal(pl)
				}
			} else {
				if len(pl.Targets) != 0 {
					t.Fatal("unproven target")
				}
			}
		})
	}
}

type fakeHandle struct {
	live, survive bool
	signals       *[]unix.Signal
	closed        bool
}

func (h *fakeHandle) Send(s unix.Signal) bool {
	*h.signals = append(*h.signals, s)
	if !h.survive || s == unix.SIGKILL {
		h.live = false
	}
	return true
}
func (h *fakeHandle) Alive() bool { return h.live }
func (h *fakeHandle) Close()      { h.closed = true }
func stopFixture(t *testing.T) (options, []string, string, helperControl, *[]unix.Signal) {
	i, _ := helperFixture(t)
	fakeProcess(t, i.proc, 100, 1, i.dest+"/bin/external-asp", "/", "")
	pl := scan([]string{i.dest}, i.proc, true, nil)
	empty := pl
	empty.Targets = nil
	empty.Processes = map[int]*process{}
	empty.References = nil
	signals := []unix.Signal{}
	calls := 0
	c := helperControl{Scan: func() plan {
		calls++
		if calls == 1 {
			return pl
		}
		return empty
	}, Handle: func(*process) handle { return &fakeHandle{live: true, signals: &signals} }, Active: func([]string) {}, Wait: time.Millisecond, Settle: 0}
	return options{OptIn: true, Maintenance: true}, []string{i.dest}, i.proc, c, &signals
}
func TestExplicitHelperStopEscalationAndRespawn(t *testing.T) {
	for _, kind := range []string{"term", "survivor", "kill", "respawn", "blocked", "optin", "ack"} {
		t.Run(kind, func(t *testing.T) {
			o, rs, proc, c, signals := stopFixture(t)
			if kind == "survivor" || kind == "kill" {
				c.Handle = func(*process) handle { return &fakeHandle{live: true, survive: true, signals: signals} }
			}
			if kind == "kill" {
				o.ForceKill = true
			}
			if kind == "respawn" {
				old := c.Scan
				pl := old()
				c.Scan = func() plan { return pl }
			}
			if kind == "blocked" {
				old := c.Scan
				c.Scan = func() plan { p := old(); p.Blocked = []string{"ambiguous"}; return p }
			}
			if kind == "optin" {
				o.OptIn = false
			}
			if kind == "ack" {
				o.Maintenance = false
			}
			fn := func() any { return stopHelpers(o, rs, proc, c) }
			if kind == "term" || kind == "kill" {
				accepts(t, fn)
			} else {
				refuses(t, "", fn)
			}
			expected := 1
			if kind == "kill" {
				expected = 2
			}
			if kind == "blocked" || kind == "optin" || kind == "ack" {
				expected = 0
			}
			if len(*signals) != expected {
				t.Fatalf("%s signals=%v", kind, *signals)
			}
			if expected == 2 && (*signals)[1] != unix.SIGKILL {
				t.Fatal("missing kill")
			}
		})
	}
}
func mountFixture(t *testing.T) (*installer, plan, *process) {
	i, _ := helperFixture(t)
	ns := i.base + "/private-ns"
	os.WriteFile(ns, []byte("ns"), 0600)
	p := fakeProcess(t, i.proc, 100, 1, i.dest+"/bin/external-asp", "/", ns)
	root := i.dest + "/" + rootfs
	info := "1 0 0:1 / / rw - ext4 root rw\n"
	info += "2 1 0:1 " + root + " " + root + " ro - ext4 root ro\n"
	info += "3 2 0:1 " + root + "/system " + root + "/system ro - ext4 root ro\n"
	info += "4 2 0:2 / " + root + "/sys ro - sysfs sysfs ro\n"
	os.WriteFile(p+"/mountinfo", []byte(info), 0600)
	pl := scan([]string{i.dest}, i.proc, true, nil)
	return i, pl, pl.Targets[0]
}
func TestPrivateMountScopeAndOwnership(t *testing.T) {
	for _, kind := range []string{"valid", "host", "shared", "unknown", "stacked", "foreignowner", "foreignsource", "fdowner"} {
		t.Run(kind, func(t *testing.T) {
			i, pl, p := mountFixture(t)
			rs := []string{i.dest}
			switch kind {
			case "host":
				p.Private = false
			case "shared":
				p.Mounts[1].Propagation = []string{"shared:10"}
			case "unknown":
				p.Mounts = append(p.Mounts, mount{Target: p.Generation + "/" + rootfs + "/system/foreign"})
			case "stacked":
				p.Mounts = append(p.Mounts, p.Mounts[1])
			case "foreignowner":
				q := *p
				q.PID = 200
				pl.Processes[200] = &q
			case "foreignsource":
				os.Remove(fmt.Sprintf("%s/100/root", i.proc))
				os.Symlink(i.base, fmt.Sprintf("%s/100/root", i.proc))
			case "fdowner":
				q := *p
				q.PID = 200
				q.Namespace = inode{1, 2}
				q.FDs = map[string]string{"4": i.dest}
				pl.Processes[200] = &q
			}
			fn := func() any { return cleanupPlan(p, pl, rs, i.proc) }
			if kind == "valid" {
				ms := accepts(t, fn).([]mount)
				if len(ms) != 3 || ms[2].Target != i.dest+"/"+rootfs {
					t.Fatal(ms)
				}
			} else {
				refuses(t, "", fn)
			}
		})
	}
}
func TestNamespaceAnchorPinnedWithoutSetns(t *testing.T) {
	i, _, p := mountFixture(t)
	n := pinNamespace(p, p.Mounts, i.proc)
	if ino(fmt.Sprintf("/proc/self/fd/%d", n.Anchor.Fd())) != ino("/") {
		t.Fatal("wrong root anchor")
	}
	n.Close()
}
func TestCleanupAdapterExactTargetsDetachAndErrors(t *testing.T) {
	for _, kind := range []string{"normal", "detach", "denied", "newmount", "changed", "setns"} {
		t.Run(kind, func(t *testing.T) {
			root := "/tmp/test/external-asp/" + rootfs
			ms := []mount{{ID: 2, Target: root + "/sys", Root: "/", Options: []string{"ro"}, Propagation: []string{}, FSType: "sysfs", Source: "sysfs"}, {ID: 1, Target: root, Root: root, Options: []string{"ro"}, Propagation: []string{}, FSType: "ext4", Source: "root"}}
			req := cleanupRequest{Namespace: inode{1, 2}, Root: root, Expected: ms}
			done := 0
			calls := []string{}
			ops := cleanupOps{
				Enter: func(int) {
					if kind == "setns" {
						need(false, "setns unsupported")
					}
				}, Anchor: func(int) {},
				Mounts: func() []mount {
					if kind == "newmount" {
						return []mount{{Target: root + "/foreign"}}
					}
					if kind == "changed" && len(calls) > 0 {
						return []mount{{Target: root + "/foreign"}}
					}
					return ms[done:]
				},
				Unmount: func(p string, flags int) error {
					calls = append(calls, fmt.Sprintf("%s:%d", p, flags))
					if kind == "denied" || kind == "detach" && flags == 0 {
						return unix.EPERM
					}
					done++
					return nil
				},
			}
			fn := func() any { return cleanupWith(req, ops) }
			if kind == "normal" || kind == "detach" {
				accepts(t, fn)
				if done != 2 {
					t.Fatal(done)
				}
			} else {
				refuses(t, "", fn)
			}
			for _, call := range calls {
				if !strings.HasPrefix(call, root) {
					t.Fatal("unmounted outside owned tree")
				}
			}
			if (kind == "newmount" || kind == "setns") && len(calls) > 0 {
				t.Fatal("unmount after failed verification")
			}
		})
	}
}
func TestForceFlagsRequireHelpersStop(t *testing.T) {
	refuses(t, "helpers stop", func() any { return run([]string{"install", "--force-kill"}) })
	refuses(t, "helpers stop", func() any { return run([]string{"status", "--force-unmount"}) })
}
func TestFullStopWithPinnedNamespaceMockCleanup(t *testing.T) {
	i, pl, p := mountFixture(t)
	expected := cleanupPlan(p, pl, []string{i.dest}, i.proc)
	empty := pl
	empty.Targets = nil
	empty.Processes = map[int]*process{}
	empty.References = nil
	scans, cleanups := 0, 0
	signals := []unix.Signal{}
	c := helperControl{Scan: func() plan {
		scans++
		if scans == 1 {
			return pl
		}
		return empty
	},
		Handle: func(*process) handle { return &fakeHandle{live: true, signals: &signals} },
		Pin:    func(p *process, m []mount) *pinnedNamespace { return pinNamespace(p, m, i.proc) },
		Cleanup: func(n *pinnedNamespace) any {
			cleanups++
			if len(n.Expected) != len(expected) || n.Identity != p.Namespace {
				t.Fatal("pin changed")
			}
			return "MOCK_CLEANUP"
		},
		Active: func([]string) {}, Wait: time.Millisecond,
	}
	accepts(t, func() any {
		return stopHelpers(options{OptIn: true, Maintenance: true, ForceUnmount: true}, []string{i.dest}, i.proc, c)
	})
	if cleanups != 1 {
		t.Fatal(cleanups)
	}
}

func TestOrphanNamespaceFDIsKeptAndBlocks(t *testing.T) {
	i, foreign := helperFixture(t)
	p := fakeProcess(t, i.proc, 100, 1, foreign, "/", "")
	os.Symlink("mnt:[999999]", p+"/fd/8")
	pl := scan([]string{i.dest}, i.proc, true, nil)
	if len(pl.Blocked) != 1 || !strings.Contains(pl.Blocked[0], "orphan mount namespace") {
		t.Fatal(pl.Blocked)
	}
	refuses(t, "orphan mount namespace", func() any { activeCheck([]string{i.dest}, i.proc, true); return nil })
	if _, e := os.Lstat(p + "/fd/8"); e != nil {
		t.Fatal("namespace FD removed")
	}
}
func TestR1ParentReusePreventsSignal(t *testing.T) {
	i, host := helperFixture(t)
	hp := fakeProcess(t, i.proc, 50, 1, host, "/", "")
	p := fakeProcess(t, i.proc, 100, 50, i.dest+"/bin/external-asp", "/", "")
	before := snapshot(i.proc, 100)
	before.ParentProof = snapshot(i.proc, 50)
	setStat(t, hp, 1, "124", "S")
	refuses(t, "identity changed", func() any { return sameProcess(before, i.proc) })
	_ = p
}

func TestOnlyOwnVerifiedNamespacePinsExemptOrphanBlock(t *testing.T) {
	id := inode{1, 123}
	p := &process{PID: os.Getpid(), FDs: map[string]string{"8": "mnt:[123]"}, FDIDs: map[string]inode{"8": id}}
	if !orphanNamespaceFD(p, "8", nil, nil) {
		t.Fatal("unknown self pin exempt")
	}
	if orphanNamespaceFD(p, "8", nil, map[inode]bool{id: true}) {
		t.Fatal("own verified cleanup pin blocked")
	}
	p.PID++
	if !orphanNamespaceFD(p, "8", nil, map[inode]bool{id: true}) {
		t.Fatal("foreign pin exempt")
	}
}
func TestForeignNamespaceFDKeeperBlocksCleanup(t *testing.T) {
	i, pl, p := mountFixture(t)
	empty := pl
	empty.Targets = nil
	keeper := &process{PID: 9999999, Namespace: inode{7, 8}, FDIDs: map[string]inode{"9": p.Namespace}}
	empty.Processes = map[int]*process{keeper.PID: keeper}
	calls := 0
	signals := []unix.Signal{}
	cleanupCalls := 0
	c := helperControl{Scan: func() plan {
		calls++
		if calls == 1 {
			return pl
		}
		return empty
	},
		Handle:  func(*process) handle { return &fakeHandle{live: true, signals: &signals} },
		Pin:     func(p *process, m []mount) *pinnedNamespace { return pinNamespace(p, m, i.proc) },
		Cleanup: func(*pinnedNamespace) any { cleanupCalls++; return nil }, Active: func([]string) {}, Wait: time.Millisecond}
	refuses(t, "another FD owner", func() any {
		return stopHelpers(options{OptIn: true, Maintenance: true, ForceUnmount: true}, []string{i.dest}, i.proc, c)
	})
	if cleanupCalls != 0 {
		t.Fatal("cleanup disrupted foreign keeper")
	}
}

func TestStoppedUnregisteredR1RootAlsoRecheckedForPins(t *testing.T) {
	o, rs, proc, c, _ := stopFixture(t)
	old := c.Scan
	first := old()
	first.Targets[0].Generation = "/tmp/another-owned-r1-root"
	empty := first
	empty.Targets = nil
	empty.Processes = map[int]*process{}
	count := 0
	c.Scan = func() plan {
		count++
		if count == 1 {
			return first
		}
		return empty
	}
	checked := false
	c.Active = func(roots []string) { checked = contains(roots, "/tmp/another-owned-r1-root") }
	accepts(t, func() any { return stopHelpers(o, rs, proc, c) })
	if !checked {
		t.Fatal("unregistered helper root omitted from final pin check")
	}
}

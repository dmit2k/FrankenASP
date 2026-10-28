package main

import (
	"archive/tar"
	"bytes"
	"compress/gzip"
	"encoding/binary"
	"os"
	"path"
	"path/filepath"
	"strings"
	"testing"

	"golang.org/x/sys/unix"
)

func elfFixture(interp string, shared bool) []byte {
	b := make([]byte, 1024)
	copy(b, []byte{127, 'E', 'L', 'F', 1, 1, 1})
	u16 := func(off int, v uint16) { binary.LittleEndian.PutUint16(b[off:], v) }
	u32 := func(off int, v uint32) { binary.LittleEndian.PutUint32(b[off:], v) }
	kind := uint16(2)
	if shared || interp != "" {
		kind = 3
	}
	u16(16, kind)
	u16(18, 40)
	u32(20, 1)
	u32(28, 52)
	u32(36, 0x05000000)
	u16(40, 52)
	u16(42, 32)
	u16(44, 1)
	u32(52, 1)
	u32(68, 1024)
	u32(72, 1024)
	if interp != "" {
		u16(44, 2)
		u32(84, 3)
		u32(88, 512)
		u32(100, uint32(len(interp)+1))
		copy(b[512:], interp)
	}
	return b
}
func fixture() tree {
	t := tree{}
	put := func(n string, b []byte, mode int64) {
		for p := path.Dir(n); p != "."; p = path.Dir(p) {
			t[p] = node{Kind: tar.TypeDir, Mode: 0700}
		}
		t[n] = node{Kind: tar.TypeReg, Mode: mode, Data: b}
	}
	put("bin/external-asp", elfFixture("", false), 0500)
	put(rootfs+"/factory/asp2-child", elfFixture("/system/bin/linker", false), 0500)
	put(rootfs+"/factory/channel-map", []byte("ASP2-CHANNEL-MAP-V1\nmic=0,1,2,3\nref=0,1\n"), 0400)
	put(rootfs+"/system/bin/linker", elfFixture("", false), 0500)
	put(rootfs+"/vendor/lib/libasp.so", elfFixture("", true), 0400)
	put(rootfs+"/vendor/etc/audio-algorithms/asp.cfg", []byte("ASP"), 0400)
	put(rootfs+"/vendor/etc/audio-algorithms/AFE.cfg", []byte("AFE"), 0400)
	for _, d := range []string{"proc", "proc/idme", "sys", ".realproc", "dev", "data"} {
		t[rootfs+"/"+d] = node{Kind: tar.TypeDir, Mode: 0700}
	}
	for n, v := range aliases {
		t[n] = node{Kind: tar.TypeSymlink, Mode: 0777, Link: v}
	}
	put("etc/launcher.profile", profile(bundled), 0400)
	r := map[string]any{"schema": "ASP2-INSTALLER-V1", "scope": "SYNTHETIC_FIXTURE", "mode": bundled, "installable": true, "dependencies": []any{}}
	for n, k := range map[string]string{"bin/external-asp": "launcher_sha256", rootfs + "/factory/asp2-child": "child_sha256", rootfs + "/factory/channel-map": "channel_map_sha256"} {
		r[k] = hash(t[n].Data)
	}
	put(receiptPath, jsonBytes(r), 0600)
	return t
}
func archive(t *testing.T, tr tree, change func(*tar.Writer)) string {
	t.Helper()
	p := filepath.Join(t.TempDir(), "test.tar.gz")
	f, e := os.Create(p)
	if e != nil {
		t.Fatal(e)
	}
	gz := gzip.NewWriter(f)
	tw := tar.NewWriter(gz)
	for _, n := range names(tr) {
		v := tr[n]
		h := &tar.Header{Name: n, Typeflag: v.Kind, Mode: v.Mode, Linkname: v.Link}
		if v.Kind == tar.TypeReg {
			h.Size = int64(len(v.Data))
		}
		if e = tw.WriteHeader(h); e != nil {
			t.Fatal(e)
		}
		if len(v.Data) > 0 {
			if _, e = tw.Write(v.Data); e != nil {
				t.Fatal(e)
			}
		}
	}
	if change != nil {
		change(tw)
	}
	if e = tw.Close(); e != nil {
		t.Fatal(e)
	}
	gz.Close()
	f.Close()
	return p
}
func accepts(t *testing.T, fn func() any) any {
	t.Helper()
	v, e := guarded(fn)
	if e != nil {
		t.Fatal(e)
	}
	return v
}
func refuses(t *testing.T, want string, fn func() any) {
	t.Helper()
	_, e := guarded(fn)
	if e == nil || !strings.Contains(e.Error(), want) {
		t.Fatalf("wanted refusal %q, got %v", want, e)
	}
}
func fakeProc(t *testing.T) string {
	t.Helper()
	p := t.TempDir()
	for _, d := range []string{"self/ns"} {
		if e := os.MkdirAll(p+"/"+d, 0700); e != nil {
			t.Fatal(e)
		}
	}
	os.WriteFile(p+"/self/ns/mnt", []byte("host namespace"), 0600)
	os.WriteFile(p+"/self/mountinfo", []byte("1 0 0:1 / / rw - ext4 root rw\n"), 0600)
	return p
}
func localInstaller(t *testing.T) *installer {
	b := t.TempDir()
	os.Chmod(b, 0700)
	o := options{LocalRoot: b, Destination: b + "/external-asp", OptIn: true, Confirm: true}
	var i *installer
	accepts(t, func() any { i = newInstaller(o, true); return nil })
	i.proc = fakeProc(t)
	return i
}
func TestBundleRoundTrip(t *testing.T) {
	tr := fixture()
	v := tr[rootfs+"/proc"]
	v.Mode = 0755
	tr[rootfs+"/proc"] = v
	p := archive(t, tr, nil)
	got := accepts(t, func() any { return loadBundle(p) }).(tree)
	if got.footprint() != tr.footprint() {
		t.Fatal("footprint changed")
	}
	for n, v := range tr {
		q := got[n]
		if q.Mode != v.Mode || q.Kind != v.Kind || q.Link != v.Link || !bytes.Equal(q.Data, v.Data) {
			t.Fatal(n)
		}
	}
}
func TestUnsafeArchives(t *testing.T) {
	cases := []struct {
		name string
		h    tar.Header
	}{
		{"absolute", tar.Header{Name: "/tmp/escape", Mode: 0400, Typeflag: tar.TypeReg, Size: 1}},
		{"dotdot", tar.Header{Name: "lib/../escape", Mode: 0400, Typeflag: tar.TypeReg, Size: 1}},
		{"duplicate", tar.Header{Name: "bin/external-asp", Mode: 0400, Typeflag: tar.TypeReg, Size: 1}},
		{"hardlink", tar.Header{Name: "lib/hard", Mode: 0400, Typeflag: tar.TypeLink, Linkname: "bin/external-asp"}},
		{"device", tar.Header{Name: "lib/dev", Mode: 0600, Typeflag: tar.TypeChar}},
		{"fifo", tar.Header{Name: "lib/fifo", Mode: 0600, Typeflag: tar.TypeFifo}},
		{"foreignlink", tar.Header{Name: "lib/link", Mode: 0777, Typeflag: tar.TypeSymlink, Linkname: "/etc/passwd"}},
		{"overwrite", tar.Header{Name: rootfs + "/proc/self/escape", Mode: 0400, Typeflag: tar.TypeReg, Size: 1}},
		{"worldwrite", tar.Header{Name: "lib/unsafe", Mode: 0666, Typeflag: tar.TypeReg, Size: 1}},
		{"oversized", tar.Header{Name: "lib/huge", Mode: 0400, Typeflag: tar.TypeReg, Size: maxFile + 1}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			p := archive(t, fixture(), func(w *tar.Writer) {
				h := tc.h
				must(w.WriteHeader(&h))
				if h.Size > 0 {
					_, _ = w.Write(make([]byte, h.Size))
				}
			})
			refuses(t, "", func() any { return loadBundle(p) })
		})
	}
}
func TestCorruptAndTruncatedGzip(t *testing.T) {
	for _, kind := range []string{"crc", "truncated", "trailing"} {
		t.Run(kind, func(t *testing.T) {
			p := archive(t, fixture(), nil)
			b, _ := os.ReadFile(p)
			switch kind {
			case "crc":
				b[len(b)-8] ^= 1
			case "truncated":
				b = b[:len(b)-7]
			case "trailing":
				var extra bytes.Buffer
				g := gzip.NewWriter(&extra)
				g.Write([]byte("foreign data"))
				g.Close()
				b = append(b, extra.Bytes()...)
			}
			os.WriteFile(p, b, 0600)
			refuses(t, "", func() any { return loadBundle(p) })
		})
	}
}
func TestPayloadValidation(t *testing.T) {
	changes := map[string]func(tree){
		"wrong ELF": func(tr tree) { v := tr["bin/external-asp"]; v.Data = []byte("NOT ELF"); tr["bin/external-asp"] = v },
		"wrong child": func(tr tree) {
			v := tr[rootfs+"/factory/asp2-child"]
			v.Data = elfFixture("/lib/ld-linux-armhf.so.3", false)
			tr[rootfs+"/factory/asp2-child"] = v
		},
		"wrong map": func(tr tree) {
			v := tr[rootfs+"/factory/channel-map"]
			v.Data = []byte("ASP2-CHANNEL-MAP-V1\nmic=0,0,2,3\nref=0,1\n")
			tr[rootfs+"/factory/channel-map"] = v
		},
		"wrong profile":  func(tr tree) { v := tr["etc/launcher.profile"]; v.Data = profile(live); tr["etc/launcher.profile"] = v },
		"missing child":  func(tr tree) { delete(tr, rootfs+"/factory/asp2-child") },
		"missing libasp": func(tr tree) { delete(tr, rootfs+"/vendor/lib/libasp.so") },
		"wrong alias":    func(tr tree) { v := tr[rootfs+"/proc/self"]; v.Link = "/etc"; tr[rootfs+"/proc/self"] = v },
		"private bin":    func(tr tree) { v := tr["bin"]; v.Mode = 0755; tr["bin"] = v },
		"missing exec": func(tr tree) {
			v := tr[rootfs+"/system/bin/linker"]
			v.Mode = 0400
			tr[rootfs+"/system/bin/linker"] = v
		},
	}
	for name, change := range changes {
		t.Run(name, func(t *testing.T) { tr := fixture(); change(tr); refuses(t, "", func() any { return validate(tr) }) })
	}
}
func installFixture(t *testing.T, i *installer) string {
	t.Helper()
	v := accepts(t, func() any { return i.install(fixture()) }).(map[string]any)
	return v["installed"].(string)
}
func TestTransactionsAndExactRollback(t *testing.T) {
	i := localInstaller(t)
	mode, _ := os.Stat(i.base)
	first := installFixture(t, i)
	firstInode := ino(i.dest)
	second := installFixture(t, i)
	found := accepts(t, func() any { return i.discover(i.readRegistry()) }).(map[string]generation)
	if len(found) != 2 || !found[second].Current || found[first].Current {
		t.Fatal(found)
	}
	i.o.Generation = first
	accepts(t, func() any { return i.mutate(false) })
	if ino(i.dest) != firstInode {
		t.Fatal("rollback did not exchange exact inode")
	}
	accepts(t, func() any { return i.mutate(true) })
	i.o.Generation = second
	accepts(t, func() any { return i.mutate(true) })
	if len(i.readRegistry().Generations) != 0 {
		t.Fatal("registry not empty")
	}
	after, _ := os.Stat(i.base)
	if after.Mode() != mode.Mode() {
		t.Fatal("parent mode changed")
	}
}
func TestInterruptedTransactions(t *testing.T) {
	for _, point := range []string{"registered-stage", "staged-files", "registered-complete", "before-publish", "after-publish"} {
		t.Run(point, func(t *testing.T) {
			i := localInstaller(t)
			first := installFixture(t, i)
			i.point = func(p string) {
				if p == point {
					need(false, "injected interruption")
				}
			}
			refuses(t, "injected", func() any { return i.install(fixture()) })
			i.point = func(string) {}
			found := i.discover(i.readRegistry())
			if len(found) != 2 {
				t.Fatal(found)
			}
			for k, g := range found {
				if k != first {
					i.o.Generation = k
					if g.Preparation {
						refuses(t, "incomplete", func() any { return i.mutate(false) })
					}
					accepts(t, func() any { return i.mutate(true) })
				}
			}
			i.o.Generation = first
			accepts(t, func() any { return i.mutate(true) })
		})
	}
}
func TestPartialRemovalAndStaleRecord(t *testing.T) {
	i := localInstaller(t)
	key := installFixture(t, i)
	i.o.Generation = key
	i.point = func(p string) {
		if p == "before-removal" {
			for _, g := range i.discover(i.readRegistry()) {
				os.Remove(g.Path + "/bin/external-asp")
			}
			need(false, "power loss")
		}
	}
	refuses(t, "power loss", func() any { return i.mutate(true) })
	i.point = func(string) {}
	s := i.status().(map[string]any)
	if !s["generations"].(map[string]generation)[key].Removal {
		t.Fatal(s)
	}
	accepts(t, func() any { return i.mutate(true) })
	key = installFixture(t, i)
	i.o.Generation = key
	i.point = func(p string) {
		if p == "after-removal" {
			need(false, "power loss")
		}
	}
	refuses(t, "power loss", func() any { return i.mutate(true) })
	i.point = func(string) {}
	s = i.status().(map[string]any)
	if len(s["missing_registry_generations"].([]string)) != 1 {
		t.Fatal(s)
	}
}
func TestRegistryReplaceFailureKeepsUnknownAndKnown(t *testing.T) {
	i := localInstaller(t)
	first := installFixture(t, i)
	i.point = func(p string) {
		if p == "registry-before-replace" {
			need(false, "registry interruption")
		}
	}
	refuses(t, "registry interruption", func() any { return i.install(fixture()) })
	i.point = func(string) {}
	need(i.readRegistry().Generations[first] != nil, "original lost")
	refuses(t, "not recognized", func() any { return i.status() })
	matches, _ := filepath.Glob(i.base + "/" + generationPrefix + "*")
	if len(matches) != 1 {
		t.Fatal(matches)
	}
	if _, e := os.Stat(matches[0]); e != nil {
		t.Fatal("unknown directory deleted")
	}
}
func TestUnknownContentAndIdentityPreserved(t *testing.T) {
	for _, kind := range []string{"extra", "symlink", "hardlink", "mode", "registry"} {
		t.Run(kind, func(t *testing.T) {
			i := localInstaller(t)
			key := installFixture(t, i)
			i.o.Generation = key
			switch kind {
			case "extra":
				os.WriteFile(i.dest+"/"+rootfs+"/system/owner-data", []byte("KEEP"), 0400)
			case "symlink":
				os.Symlink("/etc/passwd", i.dest+"/etc/owner-data")
			case "hardlink":
				os.Link(i.dest+"/bin/external-asp", i.dest+"/"+rootfs+"/system/owner-data")
			case "mode":
				os.Chmod(i.dest+"/lib", 0777)
			case "registry":
				r := i.readRegistry()
				r.Generations[key].Identity.Ino++
				i.save(r)
			}
			refuses(t, "", func() any { return i.mutate(true) })
			if _, e := os.Stat(i.dest); e != nil {
				t.Fatal("unknown tree removed")
			}
		})
	}
}
func TestLockOptInAndProtectedPaths(t *testing.T) {
	i := localInstaller(t)
	unlock := i.lock()
	refuses(t, "another installer", func() any { return i.install(fixture()) })
	unlock()
	i.o.OptIn = false
	refuses(t, "opt-in", func() any { return i.install(fixture()) })
	refuses(t, "fixed", func() any { return newInstaller(options{Destination: "/tmp/external-asp"}, true) })
	refuses(t, "exact private", func() any { return newInstaller(options{Destination: i.dest, LocalRoot: "/var/tmp/asp"}, true) })
	os.Chmod(i.base, 0777)
	refuses(t, "0700", func() any { return newInstaller(i.o, true) })
}
func TestParentStock0777Preserved(t *testing.T) {
	i := localInstaller(t)
	os.Chmod(i.base, 0777)
	// A controlled local transaction models the stock parent's exact permission.
	key := installFixture(t, i)
	i.o.Generation = key
	accepts(t, func() any { return i.mutate(true) })
	st, _ := os.Stat(i.base)
	if st.Mode().Perm() != 0777 {
		t.Fatal("stock parent chmod")
	}
}
func TestRenameUnsupportedNoFallback(t *testing.T) {
	i := localInstaller(t)
	old := renameAtomic
	defer func() { renameAtomic = old }()
	renameAtomic = func(string, string, uint) { need(false, "renameat2 unsupported") }
	refuses(t, "unsupported", func() any { return i.install(fixture()) })
	if _, e := os.Stat(i.dest); !os.IsNotExist(e) {
		t.Fatal("published despite unsupported atomic rename")
	}
	if len(i.discover(i.readRegistry())) != 1 {
		t.Fatal("recoverable candidate lost")
	}
}
func TestReadOnlyInspectPlanStatus(t *testing.T) {
	i := localInstaller(t)
	before, _ := os.ReadDir(i.base)
	accepts(t, func() any { return i.plan(fixture()) })
	accepts(t, func() any { return i.status() })
	after, _ := os.ReadDir(i.base)
	if len(before) != len(after) {
		t.Fatal("read-only command wrote files")
	}
}
func TestELFHeaderAndStaticChecks(t *testing.T) {
	raw := elfFixture("", false)
	raw[18] = 183
	refuses(t, "architecture", func() any { elfCheck(raw, "", true, false); return nil })
	raw = elfFixture("", false)
	binary.LittleEndian.PutUint32(raw[68:], 2000)
	refuses(t, "bounds", func() any { elfCheck(raw, "", true, false); return nil })
}
func TestNonRootProductionWrite(t *testing.T) {
	if os.Geteuid() == 0 {
		t.Skip("requires unprivileged test host")
	}
	refuses(t, "UID 0", func() any { return newInstaller(options{Destination: destination}, true) })
}
func TestKernelRenameat2(t *testing.T) {
	b := t.TempDir()
	os.Mkdir(b+"/a", 0700)
	os.Mkdir(b+"/b", 0700)
	a := ino(b + "/a")
	bb := ino(b + "/b")
	accepts(t, func() any { renameAtomic(b+"/a", b+"/b", unix.RENAME_EXCHANGE); return nil })
	if ino(b+"/a") != bb || ino(b+"/b") != a {
		t.Fatal("not exchange")
	}
	refuses(t, "", func() any { renameAtomic(b+"/a", b+"/b", unix.RENAME_NOREPLACE); return nil })
}

func TestVendorModesAndMissingLiveRuntime(t *testing.T) {
	i := localInstaller(t)
	tr := fixture()
	r := parseObject(fileData(tr, receiptPath))
	r["mode"] = live
	v := tr[receiptPath]
	v.Data = jsonBytes(r)
	tr[receiptPath] = v
	v = tr["etc/launcher.profile"]
	v.Data = profile(live)
	tr["etc/launcher.profile"] = v
	for n := range tr {
		if strings.HasPrefix(n, rootfs+"/vendor/") {
			delete(tr, n)
		}
	}
	refuses(t, "live-vendor", func() any { return i.plan(tr) })
	vendor := t.TempDir()
	os.MkdirAll(vendor+"/lib", 0700)
	os.MkdirAll(vendor+"/etc/audio-algorithms", 0700)
	os.WriteFile(vendor+"/lib/libasp.so", elfFixture("", true), 0400)
	os.WriteFile(vendor+"/etc/audio-algorithms/asp.cfg", []byte("ASP"), 0400)
	os.WriteFile(vendor+"/etc/audio-algorithms/AFE.cfg", []byte("AFE"), 0400)
	i.o.LiveVendor = vendor
	accepts(t, func() any { return i.plan(tr) })
	v = tr[rootfs+"/vendor"]
	tr[rootfs+"/vendor/forbidden"] = node{Kind: tar.TypeReg, Mode: 0400, Data: []byte("NO")}
	refuses(t, "control content", func() any { return validate(tr) })
	delete(tr, rootfs+"/vendor/forbidden")
	os.Chmod(vendor+"/lib/libasp.so", 0600)
	must(os.WriteFile(vendor+"/lib/libasp.so", []byte("wrong"), 0400))
	refuses(t, "ELF32", func() any { return i.plan(tr) })
}

func TestInsufficientCapacityHasNoStageWrites(t *testing.T) {
	i := localInstaller(t)
	i.available = func() uint64 { return 0 }
	refuses(t, "insufficient storage", func() any { return i.install(fixture()) })
	stages, _ := filepath.Glob(i.base + "/" + generationPrefix + "*")
	if len(stages) > 0 {
		t.Fatal("stage created on low space")
	}
}

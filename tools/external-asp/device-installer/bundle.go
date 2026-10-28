package main

import (
	"archive/tar"
	"bytes"
	"compress/gzip"
	"crypto/sha256"
	"debug/elf"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path"
	"path/filepath"
	"regexp"
	"sort"
	"strings"

	"golang.org/x/sys/unix"
)

const live = "LIVE_VENDOR_MATCHED"
const bundled = "OTA_VENDOR_BUNDLED_MATCHED"
const receiptPath = "etc/installer-receipt.json"
const rootfs = "lib/rootfs"
const maxBytes int64 = 48 << 20
const maxFile int64 = 16 << 20
const maxNodes = 2048

// Refusals cross the CLI boundary as finite errors; unexpected panics are not hidden.
type refusal struct{ error }

func need(ok bool, message string) {
	if !ok {
		panic(refusal{fmt.Errorf("%s", message)})
	}
}
func must(err error) {
	if err != nil {
		panic(refusal{err})
	}
}
func guarded(fn func() any) (out any, err error) {
	defer func() {
		if p := recover(); p != nil {
			if r, ok := p.(refusal); ok {
				err = r.error
			} else {
				panic(p)
			}
		}
	}()
	return fn(), nil
}
func hash(b []byte) string { h := sha256.Sum256(b); return hex.EncodeToString(h[:]) }

var aliases = func() map[string]string {
	m := map[string]string{"self": "/.realproc/self", "sys": "/.realproc/sys", "cpuinfo": "/.realproc/cpuinfo", "device-tree": "/sys/firmware/devicetree/base"}
	for i := 0; i < 4; i++ {
		m[fmt.Sprintf("idme/miccal.%d", i)] = fmt.Sprintf("/proc/device-tree/idme/miccal.%d/value", i)
	}
	n := map[string]string{}
	for k, v := range m {
		n[rootfs+"/proc/"+k] = v
	}
	return n
}()
var safeName = regexp.MustCompile("^[A-Za-z0-9_.@+/-]+$")

func relative(n string) bool {
	if !safeName.MatchString(n) || len(n) > 240 || path.IsAbs(n) || path.Clean(n) != n {
		return false
	}
	for _, p := range strings.Split(n, "/") {
		if p == "" || p == "." || p == ".." {
			return false
		}
	}
	return true
}

type node struct {
	Kind byte
	Mode int64
	Data []byte
	Link string
}
type tree map[string]node

func names(t tree) []string {
	n := make([]string, 0, len(t))
	for k := range t {
		n = append(n, k)
	}
	sort.Strings(n)
	return n
}
func loadBundle(file string) tree {
	f, e := os.Open(file)
	must(e)
	defer f.Close()
	st, e := f.Stat()
	must(e)
	need(st.Mode().IsRegular() && st.Size() <= maxBytes, "bundle is not a bounded regular archive")
	g, e := gzip.NewReader(f)
	must(e)
	defer g.Close()
	// Bound headers, padding and decompressed bytes as well as logical payload.
	lr := &io.LimitedReader{R: g, N: maxBytes + (4 << 20) + 1}
	tr := tar.NewReader(lr)
	t := tree{}
	var total int64
	for {
		h, e := tr.Next()
		if e == io.EOF {
			break
		}
		must(e)
		n := strings.TrimSuffix(h.Name, "/")
		need(relative(n) && strings.Contains(n, "/") || n == "bin" || n == "etc" || n == "lib", "unsafe archive path")
		need(strings.Split(n, "/")[0] == "bin" || strings.Split(n, "/")[0] == "etc" || strings.Split(n, "/")[0] == "lib", "unexpected top-level path")
		_, duplicate := t[n]
		need(!duplicate && len(t) < maxNodes, "duplicate/too many archive entries")
		need(len(h.PAXRecords) == 0 && len(h.Xattrs) == 0, "extended archive metadata unsupported")
		need((h.Typeflag == tar.TypeSymlink || h.Mode&07022 == 0) && h.Mode&^07777 == 0, "unsafe archive mode")
		v := node{Kind: h.Typeflag, Mode: h.Mode, Link: h.Linkname}
		switch h.Typeflag {
		case tar.TypeDir:
			need(h.Size == 0 && h.Linkname == "", "invalid directory entry")
		case tar.TypeSymlink:
			need(aliases[n] != "" && aliases[n] == h.Linkname && h.Size == 0, "unknown archive symlink")
			v.Mode = 0777
		case tar.TypeReg, tar.TypeRegA:
			need(h.Linkname == "" && h.Size > 0 && h.Size <= maxFile, "empty/oversized file")
			total += h.Size
			need(total <= maxBytes, "payload exceeds 48MiB")
			v.Kind = tar.TypeReg
			v.Data = make([]byte, int(h.Size))
			_, e = io.ReadFull(tr, v.Data)
			must(e)
		default:
			need(false, "hardlink/device/fifo/unknown archive inode")
		}
		t[n] = v
	}
	// Force gzip CRC/truncation validation; only zero tar padding may follow.
	tail, e := io.ReadAll(lr)
	must(e)
	need(lr.N > 0, "decompression bound exceeded")
	need(len(bytes.Trim(tail, "\x00")) == 0, "trailing archive content")
	for n := range t {
		if p := path.Dir(n); p != "." {
			need(t[p].Kind == tar.TypeDir, "missing/non-directory archive ancestor")
		}
	}
	validate(t)
	return t
}
func profile(mode string) []byte {
	return []byte("F2B_LAUNCHER_V1\nplatform=athena\nvendor_mode=" + mode + "\nsource_pair=INSTALLER_VERIFIED\n")
}
func exactChildren(t tree, dir string, expected ...string) {
	var actual []string
	for n := range t {
		if path.Dir(n) == dir {
			actual = append(actual, path.Base(n))
		}
	}
	sort.Strings(actual)
	sort.Strings(expected)
	need(strings.Join(actual, "\x00") == strings.Join(expected, "\x00"), "unexpected/missing control content: "+dir)
}
func fileData(t tree, n string) []byte {
	v, ok := t[n]
	need(ok && v.Kind == tar.TypeReg, "missing regular file: "+n)
	return v.Data
}
func parseObject(b []byte) map[string]any {
	need(len(b) < 1<<20, "oversized JSON receipt")
	var r map[string]any
	must(json.Unmarshal(b, &r))
	need(r != nil, "JSON receipt must be object")
	return r
}
func str(r map[string]any, k string) string            { v, _ := r[k].(string); return v }
func object(r map[string]any, k string) map[string]any { v, _ := r[k].(map[string]any); return v }
func elfCheck(raw []byte, interp string, static, shared bool) {
	need(len(raw) >= 52 && bytes.Equal(raw[:7], []byte{127, 'E', 'L', 'F', 1, 1, 1}), "expected ELF32 little-endian")
	need(binary.LittleEndian.Uint32(raw[36:40])&0xff000000 == 0x05000000, "expected ARM EABI5")
	f, e := elf.NewFile(bytes.NewReader(raw))
	must(e)
	defer f.Close()
	need(f.Machine == elf.EM_ARM && f.Version == elf.EV_CURRENT && (f.Type == elf.ET_EXEC || f.Type == elf.ET_DYN) && (!shared || f.Type == elf.ET_DYN), "wrong ELF architecture/type")
	need(binary.LittleEndian.Uint16(raw[40:42]) == 52 && binary.LittleEndian.Uint16(raw[42:44]) == 32 && len(f.Progs) > 0 && len(f.Progs) <= 128, "invalid ELF program header")
	loads, interps := 0, 0
	for _, p := range f.Progs {
		need(p.Off <= uint64(len(raw)) && p.Filesz <= uint64(len(raw))-p.Off, "ELF segment bounds")
		if p.Type == elf.PT_LOAD {
			loads++
		}
		if p.Type == elf.PT_DYNAMIC {
			need(!static, "launcher must be static")
		}
		if p.Type == elf.PT_INTERP {
			interps++
			b := raw[p.Off : p.Off+p.Filesz]
			need(interp != "" && bytes.Equal(b, append([]byte(interp), 0)) || shared && bytes.Equal(b, []byte("/system/bin/linker\x00")), "wrong ELF interpreter")
		}
	}
	expected := 0
	if interp != "" {
		expected = 1
	}
	need(loads > 0 && (interps == expected || shared && interps == 1), "ELF load/interpreter policy")
}
func channelMap(b []byte) {
	need(len(b) <= 128, "oversized channel map")
	ls := strings.Split(string(b), "\n")
	need(len(ls) == 4 && ls[0] == "ASP2-CHANNEL-MAP-V1" && ls[3] == "", "invalid channel-map header")
	for i, prefix := range []string{"mic=", "ref="} {
		need(strings.HasPrefix(ls[i+1], prefix), "invalid channel-map prefix")
		s := strings.Split(strings.TrimPrefix(ls[i+1], prefix), ",")
		count := 4
		if i == 1 {
			count = 2
		}
		need(len(s) == count, "invalid channel-map count")
		sort.Strings(s)
		for j, v := range s {
			need(v == fmt.Sprint(j), "channel-map must be exact permutation")
		}
	}
}
func validate(t tree) map[string]any {
	r := parseObject(fileData(t, receiptPath))
	mode := str(r, "mode")
	need(str(r, "schema") == "ASP2-INSTALLER-V1" && (mode == live || mode == bundled), "unrecognized payload receipt")
	need(str(r, "scope") == "OWNER_CONFIRMED" || str(r, "scope") == "SYNTHETIC_FIXTURE", "unknown receipt scope")
	need(r["installable"] == true, "NONINSTALLABLE preview")
	exactChildren(t, ".", "bin", "etc", "lib")
	exactChildren(t, "bin", "external-asp")
	exactChildren(t, "etc", "installer-receipt.json", "launcher.profile")
	exactChildren(t, "lib", "rootfs")
	exactChildren(t, rootfs, "factory", "system", "vendor", "proc", "sys", ".realproc", "dev", "data")
	exactChildren(t, rootfs+"/factory", "asp2-child", "channel-map")
	for _, n := range []string{"bin", "etc", "lib", rootfs} {
		need(t[n].Kind == tar.TypeDir && t[n].Mode == 0700, "private directory must be 0700: "+n)
	}
	for n, v := range t {
		need(relative(n), "unsafe tree path")
		if p := path.Dir(n); p != "." {
			need(t[p].Kind == tar.TypeDir, "unsafe tree ancestor")
		}
		if v.Kind == tar.TypeSymlink {
			need(aliases[n] != "" && aliases[n] == v.Link, "unexpected symlink")
		} else {
			need((v.Kind == tar.TypeDir || v.Kind == tar.TypeReg) && v.Mode&07022 == 0, "unsafe payload inode/mode")
			if v.Kind == tar.TypeDir {
				need(v.Mode&0700 == 0700, "directory must be owner-accessible")
			}
		}
	}
	for n, target := range aliases {
		need(t[n].Kind == tar.TypeSymlink && t[n].Link == target, "missing proc/IDME alias")
	}
	for _, d := range []string{"sys", ".realproc", "dev", "data"} {
		exactChildren(t, rootfs+"/"+d)
	}
	for _, n := range []string{"bin/external-asp", rootfs + "/factory/asp2-child", rootfs + "/system/bin/linker"} {
		need(t[n].Mode&0500 == 0500, "missing executable mode: "+n)
	}
	rawMap := fileData(t, rootfs+"/factory/channel-map")
	channelMap(rawMap)
	for n, k := range map[string]string{"bin/external-asp": "launcher_sha256", rootfs + "/factory/asp2-child": "child_sha256", rootfs + "/factory/channel-map": "channel_map_sha256"} {
		if _, present := r[k]; present {
			want := str(r, k)
			need(len(want) == 64 && hash(fileData(t, n)) == want, "small artifact/map hash changed: "+n)
		}
	}
	elfCheck(fileData(t, "bin/external-asp"), "", true, false)
	elfCheck(fileData(t, rootfs+"/factory/asp2-child"), "/system/bin/linker", false, false)
	elfCheck(fileData(t, rootfs+"/system/bin/linker"), "", false, false)
	need(bytes.Equal(fileData(t, "etc/launcher.profile"), profile(mode)), "launcher.profile mismatch")
	if mode == live {
		exactChildren(t, rootfs+"/vendor")
	} else {
		vendorSanity(t)
	}
	// Verify prepared closure paths still exist; resolution remains host Python's job.
	edges, ok := r["dependencies"].([]any)
	need(ok && len(edges) <= 2048, "missing/oversized prepared dependency edges")
	for _, v := range edges {
		edge, ok := v.(map[string]any)
		need(ok, "invalid dependency edge")
		n := str(edge, "selected")
		need(relative(n) && (strings.HasPrefix(n, "system/") || strings.HasPrefix(n, "vendor/")), "invalid prepared dependency path")
		if mode == live && strings.HasPrefix(n, "vendor/") {
			continue
		}
		fileData(t, rootfs+"/"+n)
	}
	return r
}
func vendorSanity(t tree) {
	elfCheck(fileData(t, rootfs+"/vendor/lib/libasp.so"), "", false, true)
	need(len(fileData(t, rootfs+"/vendor/etc/audio-algorithms/asp.cfg")) > 0 && len(fileData(t, rootfs+"/vendor/etc/audio-algorithms/AFE.cfg")) > 0, "missing factory configs")
}

type footprint struct {
	Files       int   `json:"files"`
	Directories int   `json:"directories"`
	Symlinks    int   `json:"symlinks"`
	Bytes       int64 `json:"bytes"`
}

func (t tree) footprint() footprint {
	f := footprint{Directories: 1}
	for _, v := range t {
		switch v.Kind {
		case tar.TypeDir:
			f.Directories++
		case tar.TypeSymlink:
			f.Symlinks++
		case tar.TypeReg:
			f.Files++
			f.Bytes += int64(len(v.Data))
		}
	}
	return f
}
func readTree(dir string, partial bool) tree {
	t := tree{}
	var total int64
	var base unix.Stat_t
	must(unix.Lstat(dir, &base))
	need(base.Uid == uint32(os.Geteuid()) && base.Mode&unix.S_IFMT == unix.S_IFDIR && base.Mode&07777 == 0700, "untrusted deployment directory")
	// OpenRoot keeps all reads beneath this pinned tree even if a pathname changes.
	rd, e := os.OpenRoot(dir)
	must(e)
	defer rd.Close()
	must(filepath.WalkDir(dir, func(p string, d fs.DirEntry, err error) error {
		must(err)
		if p == dir {
			return nil
		}
		n, e := filepath.Rel(dir, p)
		must(e)
		need(relative(n) && len(t) < maxNodes, "unsafe/oversized disk tree")
		st, e := rd.Lstat(n)
		must(e)
		var ust unix.Stat_t
		must(unix.Lstat(p, &ust))
		need(ust.Dev == base.Dev && ust.Uid == uint32(os.Geteuid()) && ust.Gid == uint32(os.Geteuid()), "payload ownership/mount mismatch")
		v := node{Mode: int64(ust.Mode & 07777)}
		switch {
		case st.Mode()&os.ModeSymlink != 0:
			v.Kind = tar.TypeSymlink
			v.Link, e = rd.Readlink(n)
			must(e)
			need(aliases[n] != "" && aliases[n] == v.Link, "unknown disk symlink")
		case st.IsDir():
			v.Kind = tar.TypeDir
		case st.Mode().IsRegular():
			need(ust.Nlink == 1 && st.Size() <= maxFile, "hardlink/oversized disk file")
			total += st.Size()
			need(total <= maxBytes, "disk payload bound")
			v.Kind = tar.TypeReg
			v.Data, e = rd.ReadFile(n)
			must(e)
		default:
			need(false, "special disk inode")
		}
		if v.Kind != tar.TypeSymlink {
			need(v.Mode&07022 == 0, "unsafe disk permissions")
		}
		t[n] = v
		return nil
	}))
	if !partial {
		validate(t)
	}
	return t
}
func stageTree(dir string, t tree) {
	rd, e := os.OpenRoot(dir)
	must(e)
	defer rd.Close()
	if os.Geteuid() == 0 {
		must(rd.Chown(".", 0, 0))
	}
	for _, n := range names(t) {
		v := t[n]
		switch v.Kind {
		case tar.TypeDir:
			must(rd.Mkdir(n, os.FileMode(v.Mode)))
			if os.Geteuid() == 0 {
				must(rd.Chown(n, 0, 0))
			}
			must(rd.Chmod(n, os.FileMode(v.Mode)))
		case tar.TypeSymlink:
			must(rd.Symlink(v.Link, n))
			if os.Geteuid() == 0 {
				must(rd.Lchown(n, 0, 0))
			}
		case tar.TypeReg:
			f, e := rd.OpenFile(n, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
			must(e)
			_, e = f.Write(v.Data)
			if e == nil && os.Geteuid() == 0 {
				e = f.Chown(0, 0)
			}
			if e == nil {
				e = f.Chmod(os.FileMode(v.Mode))
			}
			if e == nil {
				e = f.Sync()
			}
			ce := f.Close()
			must(e)
			must(ce)
		}
	}
	// Reverse order ensures each containing directory is durable.
	ns := names(t)
	sort.Sort(sort.Reverse(sort.StringSlice(ns)))
	for _, n := range ns {
		if t[n].Kind == tar.TypeDir {
			f, e := rd.Open(n)
			must(e)
			e = f.Sync()
			f.Close()
			must(e)
		}
	}
	syncDir(dir)
}

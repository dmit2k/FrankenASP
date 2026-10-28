package main

import (
	"crypto/rand"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"

	"golang.org/x/sys/unix"
)

const destination = "/data/techo5-linux/external-asp"
const registryName = ".external-asp-owner.json"
const generationPrefix = ".external-asp-generation-"
const lockName = ".external-asp-installer.lock"
const reserve = 16 << 20

type identity struct {
	Dev uint64 `json:"dev"`
	Ino uint64 `json:"ino"`
	UID uint32 `json:"uid"`
}

func identify(p string) identity {
	var s unix.Stat_t
	must(unix.Stat(p, &s))
	return identity{uint64(s.Dev), s.Ino, s.Uid}
}

type record struct {
	Identity    identity   `json:"identity"`
	Footprint   *footprint `json:"footprint,omitempty"`
	Preparation bool       `json:"preparation_incomplete,omitempty"`
	Removal     bool       `json:"removal_authorized,omitempty"`
	Mode        string     `json:"mode,omitempty"`
}
type registry struct {
	Schema      string             `json:"schema"`
	Generations map[string]*record `json:"generations"`
}
type generation struct {
	Path        string `json:"path"`
	Current     bool   `json:"current"`
	Mode        string `json:"mode"`
	Preparation bool   `json:"preparation_pending"`
	Removal     bool   `json:"removal_pending"`
}
type options struct {
	Command, Helper, Bundle, Destination, LocalRoot, Generation, LiveVendor string
	R1Hosts                                                                 []string
	OptIn, Confirm, Maintenance, ForceKill, ForceUnmount                    bool
}
type installer struct {
	available  func() uint64
	o          options
	base, dest string
	parent     identity
	proc       string
	point      func(string)
}

func newInstaller(o options, write bool) *installer {
	d := o.Destination
	if d == "" {
		d = destination
	}
	need(filepath.IsAbs(d) && filepath.Clean(d) == d, "destination must be exact absolute path")
	if o.LocalRoot != "" {
		b := o.LocalRoot
		need(filepath.IsAbs(b) && filepath.Clean(b) == b && strings.HasPrefix(b, "/tmp/") && d == b+"/external-asp", "local mode requires exact private /tmp child")
		var st unix.Stat_t
		must(unix.Lstat(b, &st))
		need(st.Mode&unix.S_IFMT == unix.S_IFDIR && st.Mode&07777 == 0700 && st.Uid == uint32(os.Geteuid()), "local root must be owned 0700 directory")
	} else {
		need(d == destination, "production destination is fixed")
		if write {
			need(os.Geteuid() == 0, "production writes require UID 0")
		}
	}
	for p := filepath.Dir(d); ; p = filepath.Dir(p) {
		st, e := os.Lstat(p)
		must(e)
		need(st.IsDir() && st.Mode()&os.ModeSymlink == 0, "deployment ancestor symlink/type")
		if o.LocalRoot == "" {
			var s unix.Stat_t
			must(unix.Lstat(p, &s))
			need(s.Uid == 0 && s.Mode&07000 == 0, "untrusted production ancestor")
			need(s.Mode&0022 == 0 || ((p == "/data" || p == "/data/techo5-linux") && s.Mode&07777 == 0777), "unsafe production ancestor permissions")
		}
		if p == "/" {
			break
		}
	}
	if st, e := os.Lstat(d); e == nil {
		need(st.IsDir() && st.Mode()&os.ModeSymlink == 0, "deployment symlink/type")
	} else {
		need(os.IsNotExist(e), e.Error())
	}
	b := filepath.Dir(d)
	return &installer{o: o, base: b, dest: d, parent: identify(b), proc: "/proc", point: func(string) {}}
}
func (i *installer) unchanged() {
	need(identify(i.base) == i.parent, "deployment parent identity changed")
}
func uuid() string {
	b := make([]byte, 16)
	_, e := rand.Read(b)
	must(e)
	b[6] = (b[6] & 15) | 64
	b[8] = (b[8] & 63) | 128
	return fmt.Sprintf("%x-%x-%x-%x-%x", b[:4], b[4:6], b[6:8], b[8:10], b[10:])
}

var uuidRE = regexp.MustCompile("^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

func syncDir(p string) { f, e := os.Open(p); must(e); e = f.Sync(); f.Close(); must(e) }
func secureRegular(p string, mode uint32) {
	var s unix.Stat_t
	must(unix.Lstat(p, &s))
	need(s.Mode&unix.S_IFMT == unix.S_IFREG && s.Mode&07777 == mode && s.Uid == uint32(os.Geteuid()) && s.Nlink == 1, "unrecognized registry/lock: "+p)
}
func (i *installer) readRegistry() registry {
	p := i.base + "/" + registryName
	if _, e := os.Lstat(p); os.IsNotExist(e) {
		return registry{"ASP2-OWNERSHIP-V1", map[string]*record{}}
	}
	secureRegular(p, 0600)
	b := boundedRead(p, 1<<20)
	var r registry
	must(json.Unmarshal(b, &r))
	need(r.Schema == "ASP2-OWNERSHIP-V1" && r.Generations != nil, "unrecognized registry schema")
	for k, v := range r.Generations {
		need(uuidRE.MatchString(k) && v != nil, "invalid generation UUID/record")
	}
	return r
}
func jsonBytes(v any) []byte {
	b, e := json.MarshalIndent(v, "", "  ")
	must(e)
	return append(b, '\n')
}
func (i *installer) save(r registry) {
	i.unchanged()
	f, e := os.CreateTemp(i.base, ".external-asp-receipt-")
	must(e)
	p := f.Name()
	defer os.Remove(p)
	must(f.Chmod(0600))
	_, e = f.Write(jsonBytes(r))
	if e == nil {
		e = f.Sync()
	}
	ce := f.Close()
	must(e)
	must(ce)
	i.point("registry-before-replace")
	must(os.Rename(p, i.base+"/"+registryName))
	syncDir(i.base)
}
func (i *installer) lock() func() {
	i.unchanged()
	p := i.base + "/" + lockName
	fd, e := unix.Open(p, unix.O_CREAT|unix.O_RDWR|unix.O_NOFOLLOW|unix.O_CLOEXEC, 0600)
	must(e)
	f := os.NewFile(uintptr(fd), p)
	var st unix.Stat_t
	e = unix.Fstat(fd, &st)
	if e != nil || st.Mode&unix.S_IFMT != unix.S_IFREG || st.Mode&07777 != 0600 || st.Uid != uint32(os.Geteuid()) || st.Nlink != 1 {
		f.Close()
		need(false, "unrecognized installer lock")
	}
	if e = unix.Flock(fd, unix.LOCK_EX|unix.LOCK_NB); e != nil {
		f.Close()
		need(false, "another installer owns lock")
	}
	return func() { f.Close() }
}
func (i *installer) discover(r registry) map[string]generation {
	paths, e := filepath.Glob(i.base + "/" + generationPrefix + "*")
	must(e)
	if _, e := os.Lstat(i.dest); e == nil {
		paths = append(paths, i.dest)
	} else {
		need(os.IsNotExist(e), e.Error())
	}
	found := map[string]generation{}
	for _, p := range paths {
		st, e := os.Lstat(p)
		must(e)
		need(st.IsDir() && st.Mode()&os.ModeSymlink == 0, "unrecognized/partial deployment")
		id := identify(p)
		key := ""
		var rec *record
		for k, v := range r.Generations {
			if v.Identity == id {
				need(key == "", "duplicate registry identity")
				key = k
				rec = v
			}
		}
		need(key != "", "original generation ownership/inode identity not recognized")
		_, duplicate := found[key]
		need(!duplicate, "duplicate generation")
		t := readTree(p, rec.Preparation || rec.Removal)
		mode := rec.Mode
		if !rec.Preparation && !rec.Removal {
			receipt := validate(t)
			mode = str(receipt, "mode")
			need(str(receipt, "installation_id") == key, "generation receipt identity mismatch")
			f := t.footprint()
			need(rec.Footprint != nil && *rec.Footprint == f, "unrecognized generation content/size changed")
		}
		found[key] = generation{p, p == i.dest, mode, rec.Preparation, rec.Removal}
	}
	return found
}
func roots(found map[string]generation, dest string) []string {
	out := []string{dest}
	for _, g := range found {
		if g.Path != dest {
			out = append(out, g.Path)
		}
	}
	return out
}
func current(found map[string]generation) string {
	for k, g := range found {
		if g.Current {
			return k
		}
	}
	return ""
}
func (i *installer) preflight(t tree) map[string]any {
	r := validate(t)
	if i.o.LocalRoot == "" {
		need(str(r, "scope") == "OWNER_CONFIRMED", "synthetic fixture cannot enter production")
	}
	if str(r, "mode") == live {
		vendor := "/vendor"
		if i.o.LocalRoot != "" {
			vendor = i.o.LiveVendor
			need(filepath.IsAbs(vendor), "local A requires --live-vendor")
		}
		var st unix.Statfs_t
		must(unix.Statfs(vendor, &st))
		if i.o.LocalRoot == "" {
			need(st.Flags&unix.ST_RDONLY != 0, "original /vendor must already be RO")
		}
		rd, e := os.OpenRoot(vendor)
		must(e)
		defer rd.Close()
		read := func(n string) []byte {
			s, e := rd.Lstat(n)
			must(e)
			need(s.Mode().IsRegular() && s.Size() > 0 && s.Size() <= maxFile, "missing/invalid live vendor file")
			b, e := rd.ReadFile(n)
			must(e)
			return b
		}
		elfCheck(read("lib/libasp.so"), "", false, true)
		read("etc/audio-algorithms/asp.cfg")
		read("etc/audio-algorithms/AFE.cfg")
		// Host has resolved closure. Check its chosen vendor paths without resolving it again.
		for _, v := range r["dependencies"].([]any) {
			n := str(v.(map[string]any), "selected")
			if strings.HasPrefix(n, "vendor/") {
				elfCheck(read(strings.TrimPrefix(n, "vendor/")), "", false, true)
			}
		}
	}
	return r
}
func (i *installer) plan(t tree) map[string]any {
	r := i.readRegistry()
	found := i.discover(r)
	for _, g := range found {
		need(!g.Preparation && !g.Removal, "finish interrupted generation preparation/removal first")
	}
	receipt := i.preflight(t)
	activeCheck(roots(found, i.dest), i.proc, i.o.LocalRoot != "")
	var st unix.Statfs_t
	must(unix.Statfs(i.base, &st))
	free := uint64(st.Bavail) * uint64(st.Bsize)
	if i.available != nil {
		free = i.available()
	}
	size := t.footprint().Bytes
	need(free >= uint64(size+reserve), "insufficient storage for staged generation +16MiB reserve")
	op := "ATOMIC_RENAME_NOREPLACE"
	if current(found) != "" {
		op = "ATOMIC_EXCHANGE"
	}
	return map[string]any{"destination": i.dest, "bytes": size, "free_bytes": free, "required_free_bytes": size + reserve, "current": current(found), "operation": op, "mode": receipt["mode"], "activation": false, "parent_permissions_modified": false, "store_used": false}
}

var renameAtomic = func(source, dest string, flags uint) {
	e := unix.Renameat2(unix.AT_FDCWD, source, unix.AT_FDCWD, dest, flags)
	if e == unix.ENOSYS || e == unix.EINVAL || e == unix.EOPNOTSUPP {
		need(false, "renameat2 unsupported; no non-atomic fallback")
	}
	must(e)
}

func (i *installer) install(t tree) any {
	need(i.o.OptIn && i.o.Confirm, "install requires --opt-in --confirm-inactive")
	unlock := i.lock()
	defer unlock()
	plan := i.plan(t)
	r := i.readRegistry()
	key := uuid()
	stage := i.base + "/" + generationPrefix + key
	must(os.Mkdir(stage, 0700))
	id := identify(stage)
	r.Generations[key] = &record{Identity: id, Preparation: true, Mode: plan["mode"].(string)}
	// Never delete uncertain content on error. Pending records authorize explicit recovery.
	i.save(r)
	i.point("registered-stage")
	staged := tree{}
	for n, v := range t {
		staged[n] = v
	}
	receipt := parseObject(fileData(t, receiptPath))
	receipt["installation_id"] = key
	v := staged[receiptPath]
	v.Data = jsonBytes(receipt)
	staged[receiptPath] = v
	stageTree(stage, staged)
	i.point("staged-files")
	checked := readTree(stage, false)
	f := checked.footprint()
	r.Generations[key] = &record{Identity: id, Footprint: &f}
	i.save(r)
	i.point("registered-complete")
	found := i.discover(r)
	activeCheck(roots(found, i.dest), i.proc, i.o.LocalRoot != "")
	need(current(found) == plan["current"], "current generation changed")
	i.unchanged()
	need(identify(stage) == id, "stage identity changed")
	i.point("before-publish")
	if old := current(found); old != "" {
		need(identify(i.dest) == r.Generations[old].Identity, "current generation identity changed before publish")
	}
	flags := uint(unix.RENAME_NOREPLACE)
	if plan["current"] != "" {
		flags = unix.RENAME_EXCHANGE
	}
	renameAtomic(stage, i.dest, flags)
	i.point("after-publish")
	syncDir(i.base)
	return map[string]any{"installed": key, "previous": plan["current"], "destination": i.dest, "activation": false}
}
func (i *installer) status() any {
	r := i.readRegistry()
	found := i.discover(r)
	_, e := guarded(func() any { activeCheck(roots(found, i.dest), i.proc, i.o.LocalRoot != ""); return nil })
	reason := ""
	if e != nil {
		reason = e.Error()
	}
	stale := []string{}
	for k := range r.Generations {
		if _, ok := found[k]; !ok {
			stale = append(stale, k)
		}
	}
	return map[string]any{"installed": current(found) != "", "generations": found, "inactive": e == nil, "activity_or_blocker": reason, "missing_registry_generations": stale, "activation_managed": false}
}
func (i *installer) mutate(remove bool) any {
	need(i.o.OptIn && i.o.Confirm && uuidRE.MatchString(i.o.Generation), "operation requires exact --generation UUID --opt-in --confirm-inactive")
	unlock := i.lock()
	defer unlock()
	r := i.readRegistry()
	found := i.discover(r)
	g, ok := found[i.o.Generation]
	need(ok, "unrecognized generation; nothing changed")
	activeCheck(roots(found, i.dest), i.proc, i.o.LocalRoot != "")
	i.unchanged()
	need(identify(g.Path) == r.Generations[i.o.Generation].Identity, "generation inode changed")
	if !remove {
		need(!g.Current && !g.Preparation && !g.Removal, "rollback generation current/incomplete/removal pending")
		i.preflight(readTree(g.Path, false))
		flags := uint(unix.RENAME_NOREPLACE)
		if current(found) != "" {
			flags = unix.RENAME_EXCHANGE
		}
		i.point("before-rollback")
		need(identify(g.Path) == r.Generations[i.o.Generation].Identity, "rollback source identity changed")
		if old := current(found); old != "" {
			need(identify(i.dest) == r.Generations[old].Identity, "current generation identity changed before rollback")
		}
		renameAtomic(g.Path, i.dest, flags)
		i.point("after-rollback")
		syncDir(i.base)
		return map[string]any{"rolled_back_to": i.o.Generation, "activation": false}
	}
	rec := r.Generations[i.o.Generation]
	rec.Removal = true
	rec.Mode = g.Mode
	i.save(r)
	need(identify(g.Path) == rec.Identity, "generation identity changed before removal")
	if g.Current {
		trash := i.base + "/" + generationPrefix + uuid()
		renameAtomic(g.Path, trash, unix.RENAME_NOREPLACE)
		g.Path = trash
		syncDir(i.base)
	}
	i.point("before-removal")
	// Root.RemoveAll is confined and never follows payload symlinks. All inodes
	// were checked, including mounts and process references, before authorization.
	rd, e := os.OpenRoot(i.base)
	must(e)
	defer rd.Close()
	must(rd.RemoveAll(filepath.Base(g.Path)))
	i.point("after-removal")
	delete(r.Generations, i.o.Generation)
	i.save(r)
	return map[string]any{"removed": i.o.Generation, "activation": false}
}
func boundedRead(p string, limit int64) []byte {
	f, e := os.Open(p)
	must(e)
	defer f.Close()
	b, e := ioReadBounded(f, limit)
	must(e)
	return b
}

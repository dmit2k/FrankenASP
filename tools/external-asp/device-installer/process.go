package main

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"golang.org/x/sys/unix"
)

type inode struct {
	Dev uint64 `json:"dev"`
	Ino uint64 `json:"ino"`
}

func ino(p string) inode { v := identify(p); return inode{v.Dev, v.Ino} }
func link(p string) string {
	v, e := os.Readlink(p)
	must(e)
	return strings.TrimSuffix(v, " (deleted)")
}
func under(v, root string) bool {
	v = strings.TrimSuffix(v, " (deleted)")
	return v == root || strings.HasPrefix(v, root+"/")
}
func ioReadBounded(r io.Reader, limit int64) ([]byte, error) {
	b, e := io.ReadAll(io.LimitReader(r, limit+1))
	if int64(len(b)) > limit {
		return nil, fmt.Errorf("metadata bound exceeded")
	}
	return b, e
}
func text(p string, limit int64) string { return string(boundedRead(p, limit)) }

type process struct {
	ParentProof          *process `json:"-"`
	PID                  int      `json:"pid"`
	PPID                 int      `json:"ppid"`
	Start                string   `json:"start"`
	Exe, Root, Namespace inode
	ExePath              string            `json:"exe_path"`
	RootPath             string            `json:"root_path"`
	CWD                  string            `json:"cwd"`
	Comm                 string            `json:"comm"`
	FDs                  map[string]string `json:"-"`
	FDIDs                map[string]inode  `json:"-"`
	Maps, MountInfo      string            `json:"-"`
	Generation           string            `json:"root_generation,omitempty"`
	Role                 string            `json:"role,omitempty"`
	Provenance           string            `json:"provenance,omitempty"`
	Private              bool              `json:"private_namespace"`
	Mounts               []mount           `json:"mounts,omitempty"`
}

func statFields(p string) (state string, parent int, start string) {
	s := text(p+"/stat", 8192)
	at := strings.LastIndex(s, ")")
	need(at >= 0, "malformed process stat")
	f := strings.Fields(s[at+1:])
	need(len(f) >= 20, "short process stat")
	parent, e := strconv.Atoi(f[1])
	must(e)
	return f[0], parent, f[19]
}
func snapshot(proc string, pid int) *process {
	p := fmt.Sprintf("%s/%d", proc, pid)
	state, parent, start := statFields(p)
	if state == "Z" {
		return nil
	}
	q := &process{PID: pid, PPID: parent, Start: start, Exe: ino(p + "/exe"), Root: ino(p + "/root"), Namespace: ino(p + "/ns/mnt"), ExePath: link(p + "/exe"), RootPath: link(p + "/root"), CWD: link(p + "/cwd"), Comm: strings.TrimSpace(text(p+"/comm", 256)), FDs: map[string]string{}, FDIDs: map[string]inode{}}
	fds, e := os.ReadDir(p + "/fd")
	must(e)
	need(len(fds) <= 8192, "process FD count bound")
	for _, fd := range fds {
		_, e := guarded(func() any {
			n := fd.Name()
			q.FDs[n] = link(p + "/fd/" + n)
			q.FDIDs[n] = ino(p + "/fd/" + n)
			return nil
		})
		if e != nil && !os.IsNotExist(e) {
			must(e)
		}
	}
	q.Maps = text(p+"/maps", 8<<20)
	q.MountInfo = text(p+"/mountinfo", 8<<20)
	state, parent, start = statFields(p)
	need(state != "Z" && parent == q.PPID && start == q.Start && ino(p+"/exe") == q.Exe && ino(p+"/root") == q.Root && ino(p+"/ns/mnt") == q.Namespace, "process changed during inspection")
	return q
}
func pins(p *process, root string) []string {
	var reasons []string
	for k, v := range map[string]string{"executable": p.ExePath, "cwd": p.CWD, "process rootfs": p.RootPath} {
		if under(v, root) {
			reasons = append(reasons, k)
		}
	}
	for fd, v := range p.FDs {
		if under(v, root) {
			reasons = append(reasons, "pinned FD "+fd)
		}
	}
	for _, line := range strings.Split(p.Maps, "\n") {
		f := strings.Fields(line)
		if len(f) >= 6 && under(strings.Join(f[5:], " "), root) {
			reasons = append(reasons, "mapped runtime file")
		}
	}
	return reasons
}

type mount struct {
	ID          int      `json:"id"`
	Target      string   `json:"target"`
	Root        string   `json:"root"`
	Options     []string `json:"options"`
	Propagation []string `json:"propagation"`
	FSType      string   `json:"fstype"`
	Source      string   `json:"source"`
}

func unescape(s string) string {
	for _, v := range []struct{ a, b string }{{"\\040", " "}, {"\\011", "\t"}, {"\\012", "\n"}, {"\\134", "\\"}} {
		s = strings.ReplaceAll(s, v.a, v.b)
	}
	return s
}
func parseMounts(s, root string) []mount {
	out := []mount{}
	for _, line := range strings.Split(strings.TrimSpace(s), "\n") {
		if line == "" {
			continue
		}
		f := strings.Fields(line)
		sep := -1
		for j, v := range f {
			if v == "-" {
				sep = j
				break
			}
		}
		need(len(f) >= 10 && sep >= 6 && sep+3 < len(f), "cannot parse mountinfo")
		id, e := strconv.Atoi(f[0])
		must(e)
		target := unescape(f[4])
		if root != "/" {
			target = filepath.Join(root, strings.TrimPrefix(target, "/"))
		}
		out = append(out, mount{id, target, unescape(f[3]), strings.Split(f[5], ","), append([]string{}, f[6:sep]...), f[sep+1], unescape(f[sep+2])})
	}
	return out
}

type plan struct {
	Targets    []*process       `json:"targets"`
	Hosts      []map[string]any `json:"hosts"`
	Unrelated  []map[string]any `json:"unrelated"`
	Blocked    []string         `json:"blocked"`
	References []map[string]any `json:"references"`
	Processes  map[int]*process `json:"-"`
	SelfNS     inode            `json:"-"`
}

func secure(p string, directory bool) inode {
	var s unix.Stat_t
	must(unix.Lstat(p, &s))
	kind := uint32(unix.S_IFREG)
	if directory {
		kind = unix.S_IFDIR
	}
	need(s.Mode&unix.S_IFMT == kind && s.Mode&07022 == 0 && s.Uid == uint32(os.Geteuid()), "untrusted helper ownership/type/mode")
	return ino(p)
}
func scan(roots []string, proc string, local bool, hosts []string) plan {
	return scanWithPins(roots, proc, local, hosts, nil)
}

func scanWithPins(roots []string, proc string, local bool, hosts []string, pinned map[inode]bool) plan {
	out := plan{Targets: []*process{}, Hosts: []map[string]any{}, Unrelated: []map[string]any{}, Blocked: []string{}, References: []map[string]any{}, Processes: map[int]*process{}, SelfNS: ino(proc + "/self/ns/mnt")}
	trusted := map[inode][2]string{}
	for _, root := range roots {
		if _, e := os.Lstat(root); os.IsNotExist(e) {
			continue
		}
		secure(root, true)
		for sub, role := range map[string]string{"bin/external-asp": "linux-launcher", rootfs + "/factory/asp2-child": "bionic-child"} {
			p := root + "/" + sub
			if _, e := os.Lstat(p); os.IsNotExist(e) {
				continue
			}
			trusted[secure(p, false)] = [2]string{root, role}
		}
	}
	hostIDs := map[inode]bool{}
	for _, p := range hosts {
		hostIDs[secure(p, false)] = true
	}
	entries, e := os.ReadDir(proc)
	must(e)
	deadline := time.Now().Add(15 * time.Second)
	count, total := 0, 0
	for _, entry := range entries {
		pid, e := strconv.Atoi(entry.Name())
		if e != nil {
			continue
		}
		count++
		need(count <= 32768 && time.Now().Before(deadline), "process scan time/count bound")
		path := proc + "/" + entry.Name()
		if local {
			var s unix.Stat_t
			if unix.Stat(path, &s) != nil || s.Uid != uint32(os.Geteuid()) {
				continue
			}
		}
		v, e := guarded(func() any { return snapshot(proc, pid) })
		if e != nil {
			if os.IsNotExist(e) || e == unix.ESRCH {
				continue
			}
			if local && os.IsPermission(e) {
				continue
			}
			out.Blocked = append(out.Blocked, fmt.Sprintf("PID %d unreadable/unstable state: %s", pid, e))
			continue
		}
		p, _ := v.(*process)
		if p == nil {
			continue
		}
		total += len(p.Maps) + len(p.MountInfo)
		for _, s := range p.FDs {
			total += len(s)
		}
		need(total <= 128<<20, "aggregate process metadata exceeds 128MiB")
		out.Processes[pid] = p
	}
	visible := map[inode]bool{out.SelfNS: true}
	for _, p := range out.Processes {
		visible[p.Namespace] = true
	}
	for _, p := range out.Processes {
		if len(roots) > 0 || len(hosts) > 0 {
			for fd := range p.FDs {
				if orphanNamespaceFD(p, fd, visible, pinned) {
					out.Blocked = append(out.Blocked, fmt.Sprintf("PID %d orphan mount namespace FD %s has unverifiable root; kept", p.PID, fd))
				}
			}
		}
		p.Mounts = parseMounts(p.MountInfo, p.RootPath)
		p.Private = p.Namespace != out.SelfNS
		if match, ok := trusted[p.Exe]; ok {
			p.Generation = match[0]
			p.Role = match[1]
			p.Provenance = "installer-owned executable inode"
			if p.PPID == 1 || out.Processes[p.PPID] == nil {
				p.Role = "orphan-" + p.Role
			}
		} else if parent := out.Processes[p.PPID]; parent != nil && hostIDs[parent.Exe] {
			fdLaunch := p.FDIDs["3"] == p.Exe && p.FDs["4"] != ""
			child := strings.HasSuffix(p.ExePath, "/"+rootfs+"/factory/asp2-child")
			if fdLaunch || child {
				_, e := guarded(func() any {
					root := p.FDs["4"]
					role := "r1-external-helper"
					if fdLaunch {
						need(secure(root, true) == p.FDIDs["4"] && secure(root+"/bin/external-asp", false) == p.Exe, "R1 pinned root/executable mismatch")
					} else {
						root = strings.TrimSuffix(p.ExePath, "/"+rootfs+"/factory/asp2-child")
						role = "r1-bionic-child"
						for _, sub := range []string{"", "lib", rootfs, rootfs + "/factory", "etc"} {
							secure(filepath.Join(root, sub), true)
						}
						need(secure(p.ExePath, false) == p.Exe && ino(root+"/"+rootfs) == p.Root && p.Private, "R1 child root/namespace mismatch")
						elfCheck(boundedRead(p.ExePath, 1<<20), "/system/bin/linker", false, false)
						cfg := text(root+"/etc/launcher.profile", 1024)
						secure(root+"/etc/launcher.profile", false)
						need(cfg == string(profile(live)) || cfg == string(profile(bundled)), "R1 profile missing")
					}
					input := p.FDs["0"]
					inputOK, outputOK := false, false
					for _, v := range parent.FDs {
						if v == input && strings.HasPrefix(v, "pipe:[") {
							inputOK = true
						}
					}
					for n, v := range p.FDs {
						if n != "0" && n != "2" && v != input && strings.HasPrefix(v, "pipe:[") {
							for _, pv := range parent.FDs {
								if pv == v {
									outputOK = true
								}
							}
						}
					}
					need(inputOK && outputOK, "R1 IPC pipe proof missing")
					p.Generation = root
					p.Role = role
					p.Provenance = "selected R1 parent inode + pinned helper/root + distinct IPC pipes"
					p.ParentProof = parent
					return nil
				})
				if e != nil {
					out.Blocked = append(out.Blocked, fmt.Sprintf("PID %d ambiguous R1 provenance: %s", p.PID, e))
				}
			}
		}
		if p.Role != "" {
			out.Targets = append(out.Targets, p)
		} else if strings.HasPrefix(p.Comm, "techo5") || hostIDs[p.Exe] {
			out.Hosts = append(out.Hosts, map[string]any{"pid": p.PID, "exe": p.ExePath, "role": "stock-or-host; preserved"})
		} else if strings.Contains(p.Comm, "external-asp") {
			out.Unrelated = append(out.Unrelated, map[string]any{"pid": p.PID, "reason": "name is not kill authority"})
		}
		for _, root := range roots {
			why := pins(p, root)
			for _, m := range p.Mounts {
				if under(m.Target, root) || under(m.Root, root) {
					why = append(why, "runtime mount namespace")
				}
			}
			if len(why) > 0 {
				out.References = append(out.References, map[string]any{"pid": p.PID, "generation_path": root, "reasons": why})
			}
		}
	}
	for _, m := range parseMounts(text(proc+"/self/mountinfo", 8<<20), "/") {
		for _, root := range roots {
			if under(m.Target, root) || under(m.Root, root) {
				out.Blocked = append(out.Blocked, "active runtime mount: "+m.Target)
			}
		}
	}
	return out
}
func activeCheck(roots []string, proc string, local bool) {
	p := scan(roots, proc, local, nil)
	need(len(p.Blocked) == 0, "cannot establish inactive state: "+strings.Join(p.Blocked, "; "))
	if len(p.References) > 0 {
		need(false, fmt.Sprintf("active pinned deployment reference: %v", p.References))
	}
}
func sameProcess(p *process, proc string) bool {
	v, e := guarded(func() any { return snapshot(proc, p.PID) })
	if e != nil {
		if os.IsNotExist(e) || e == unix.ESRCH {
			return false
		}
		must(e)
	}
	q, _ := v.(*process)
	if q == nil {
		return false
	}
	need(q.Start == p.Start && q.PPID == p.PPID && q.Exe == p.Exe && q.Root == p.Root && q.Namespace == p.Namespace, "PID/executable/parent/root/namespace identity changed; no signal")
	if p.ParentProof != nil {
		need(sameProcess(p.ParentProof, proc), "R1 parent disappeared; no signal")
	}
	return true
}

// Only the current installer's explicitly verified cleanup pins are exempt.
func orphanNamespaceFD(p *process, fd string, visible, pinned map[inode]bool) bool {
	return strings.HasPrefix(p.FDs[fd], "mnt:[") && !visible[p.FDIDs[fd]] && !(p.PID == os.Getpid() && pinned[p.FDIDs[fd]])
}

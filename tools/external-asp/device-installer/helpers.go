package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"runtime"
	"sort"
	"strings"
	"time"

	"golang.org/x/sys/unix"
)

type handle interface {
	Send(unix.Signal) bool
	Alive() bool
	Close()
}
type processHandle struct {
	p    *process
	proc string
	fd   int
}

func openHandle(p *process, proc string) handle {
	h := &processHandle{p, proc, -1}
	if !sameProcess(p, proc) {
		return h
	}
	if proc == "/proc" {
		fd, e := unix.PidfdOpen(p.PID, 0)
		if e == nil {
			h.fd = fd
		} else if e != unix.ENOSYS && e != unix.EINVAL && e != unix.EOPNOTSUPP && e != unix.ESRCH {
			must(e)
		}
	}
	_, e := guarded(func() any { sameProcess(p, proc); return nil })
	if e != nil {
		h.Close()
		must(e)
	}
	return h
}
func (h *processHandle) Send(sig unix.Signal) bool {
	if !sameProcess(h.p, h.proc) {
		return false
	}
	var e error
	if h.fd >= 0 {
		e = unix.PidfdSendSignal(h.fd, sig, nil, 0)
	} else {
		e = unix.Kill(h.p.PID, sig)
	}
	if e == unix.ESRCH {
		return false
	}
	must(e)
	return true
}
func (h *processHandle) Alive() bool {
	if h.fd >= 0 {
		fds := []unix.PollFd{{Fd: int32(h.fd), Events: unix.POLLIN}}
		_, e := unix.Poll(fds, 0)
		must(e)
		if fds[0].Revents != 0 {
			return false
		}
	}
	return sameProcess(h.p, h.proc)
}
func (h *processHandle) Close() {
	if h.fd >= 0 {
		unix.Close(h.fd)
		h.fd = -1
	}
}
func selectedMounts(ms []mount, root string) []mount {
	out := []mount{}
	for _, m := range ms {
		if under(m.Target, root) {
			out = append(out, m)
		}
	}
	sort.Slice(out, func(a, b int) bool {
		da, db := strings.Count(out[a].Target, "/"), strings.Count(out[b].Target, "/")
		if da == db {
			return out[a].Target > out[b].Target
		}
		return da > db
	})
	return out
}
func contains(s []string, v string) bool {
	for _, x := range s {
		if x == v {
			return true
		}
	}
	return false
}
func cleanupPlan(p *process, pl plan, roots []string, proc string) []mount {
	need(p.Private, "host namespace is never a cleanup target")
	need(contains(roots, p.Generation), "cleanup requires installer-owned rootfs")
	root := p.Generation + "/" + rootfs
	secure(root, true)
	need(p.RootPath == "/" || p.RootPath == root, "unknown helper chroot")
	expected := selectedMounts(p.Mounts, root)
	need(len(expected) > 0, "no verified owned private mounts")
	allowed := map[string]string{root: "", root + "/system": "", root + "/vendor": "", root + "/sys": "sysfs", root + "/.realproc": "proc", root + "/proc": "proc", root + "/dev": "tmpfs", root + "/data": "tmpfs"}
	seen := map[string]bool{}
	for _, m := range expected {
		kind, ok := allowed[m.Target]
		need(ok && !seen[m.Target] && len(m.Propagation) == 0 && (kind == "" || kind == m.FSType), "unknown/protected/shared/stacked private mount")
		seen[m.Target] = true
		need(m.Target == root+"/dev" || m.Target == root+"/data" || contains(m.Options, "ro"), "expected RO private mount")
		suffix := strings.TrimPrefix(m.Target, root)
		if suffix == "" || suffix == "/system" || suffix == "/vendor" {
			source := m.Target
			if suffix == "/vendor" {
				cfg := text(p.Generation+"/etc/launcher.profile", 1024)
				need(cfg == string(profile(live)) || cfg == string(profile(bundled)), "unknown vendor profile")
				if cfg == string(profile(live)) {
					source = "/vendor"
				}
			}
			viewed := strings.TrimPrefix(m.Target, p.RootPath)
			if p.RootPath == "/" {
				viewed = strings.TrimPrefix(m.Target, "/")
			}
			observed := fmt.Sprintf("%s/%d/root/%s", proc, p.PID, strings.TrimPrefix(viewed, "/"))
			need(ino(observed) == ino(source), "foreign rootfs/system/vendor bind source")
		} else {
			need(m.Root == "/" && m.Source == m.FSType, "unknown pseudo-filesystem origin")
		}
	}
	targets := map[int]bool{}
	for _, q := range pl.Targets {
		targets[q.PID] = true
	}
	for _, q := range pl.Processes {
		need(targets[q.PID] || q.Namespace != p.Namespace && len(pins(q, p.Generation)) == 0, "private namespace/rootfs has another owner")
	}
	return expected
}

type pinnedNamespace struct {
	NS       *os.File
	Anchor   *os.File
	Identity inode
	Root     string
	Expected []mount
}

func (n *pinnedNamespace) Close() { n.NS.Close(); n.Anchor.Close() }
func pinNamespace(p *process, expected []mount, proc string) *pinnedNamespace {
	ns, e := os.Open(fmt.Sprintf("%s/%d/ns/mnt", proc, p.PID))
	must(e)
	var anchor *os.File
	_, err := guarded(func() any {
		fd, e := unix.Open(fmt.Sprintf("%s/%d/root", proc, p.PID), unix.O_RDONLY|unix.O_DIRECTORY|unix.O_CLOEXEC, 0)
		must(e)
		depth := strings.Count(strings.Trim(p.RootPath, "/"), "/") + 1
		if p.RootPath == "/" {
			depth = 0
		}
		need(depth <= 128, "namespace root depth bound")
		for j := 0; j < depth; j++ {
			parent, e := unix.Openat(fd, "..", unix.O_RDONLY|unix.O_DIRECTORY|unix.O_CLOEXEC, 0)
			unix.Close(fd)
			must(e)
			fd = parent
		}
		anchor = os.NewFile(uintptr(fd), "namespace-root")
		need(ino(fmt.Sprintf("/proc/self/fd/%d", anchor.Fd())) == ino("/") && ino(fmt.Sprintf("/proc/self/fd/%d", ns.Fd())) == p.Namespace && sameProcess(p, proc), "cannot verify pinned private namespace/root")
		return nil
	})
	if err != nil {
		ns.Close()
		if anchor != nil {
			anchor.Close()
		}
		must(err)
	}
	return &pinnedNamespace{ns, anchor, p.Namespace, p.Generation + "/" + rootfs, expected}
}

type cleanupRequest struct {
	Namespace inode
	Root      string
	Expected  []mount
}

func runCleanup(n *pinnedNamespace) any {
	exe, e := os.Executable()
	must(e)
	ctx, cancel := context.WithTimeout(context.Background(), 8*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, exe, "_cleanup")
	cmd.ExtraFiles = []*os.File{n.NS, n.Anchor}
	cmd.Stdin = bytes.NewReader(jsonBytes(cleanupRequest{n.Identity, n.Root, n.Expected}))
	var out, err bytes.Buffer
	cmd.Stdout = &out
	cmd.Stderr = &err
	e = cmd.Run()
	need(e == nil, "private cleanup unsupported/failed: "+err.String())
	var result any
	must(json.Unmarshal(out.Bytes(), &result))
	return result
}

type cleanupOps struct {
	Enter   func(int)
	Anchor  func(int)
	Mounts  func() []mount
	Unmount func(string, int) error
}

func cleanupWith(req cleanupRequest, ops cleanupOps) any {
	need(filepath.IsAbs(req.Root) && strings.HasSuffix(req.Root, "/"+rootfs) && len(req.Expected) > 0, "invalid private cleanup scope")
	ops.Enter(3)
	ops.Anchor(4)
	owned := func() []mount { return selectedMounts(ops.Mounts(), req.Root) }
	need(reflect.DeepEqual(owned(), req.Expected), "private mounts changed before cleanup")
	done := []map[string]any{}
	for j, m := range req.Expected {
		need(under(m.Target, req.Root) && reflect.DeepEqual(owned(), req.Expected[j:]), "private mount changed during cleanup")
		detached := false
		if e := ops.Unmount(m.Target, 0); e != nil {
			must(ops.Unmount(m.Target, unix.MNT_DETACH))
			detached = true
		}
		done = append(done, map[string]any{"target": m.Target, "detached": detached})
	}
	need(len(owned()) == 0, "private mount leak after cleanup")
	return done
}
func cleanupChild() any {
	runtime.LockOSThread()
	b, e := ioReadBounded(os.Stdin, 1<<20)
	must(e)
	var req cleanupRequest
	must(json.Unmarshal(b, &req))
	need(ino("/proc/self/ns/mnt") != req.Namespace && ino("/proc/self/fd/3") == req.Namespace, "cleanup refuses host/changed namespace")
	return cleanupWith(req, cleanupOps{
		Enter:   func(fd int) { must(unix.Unshare(unix.CLONE_FS)); must(unix.Setns(fd, unix.CLONE_NEWNS)) },
		Anchor:  func(fd int) { must(unix.Fchdir(fd)); must(unix.Chroot(".")); must(unix.Chdir("/")) },
		Mounts:  func() []mount { return parseMounts(text("/proc/self/mountinfo", 8<<20), "/") },
		Unmount: unix.Unmount,
	})
}

type helperControl struct {
	Scan    func() plan
	Handle  func(*process) handle
	Pin     func(*process, []mount) *pinnedNamespace
	Cleanup func(*pinnedNamespace) any
	Active  func([]string)
	Wait    time.Duration
	Settle  time.Duration
}

func (i *installer) helperControl(rs []string) helperControl {
	pinned := map[inode]bool{}
	return helperControl{
		Scan:   func() plan { return scanWithPins(rs, i.proc, i.o.LocalRoot != "", i.o.R1Hosts, pinned) },
		Handle: func(p *process) handle { return openHandle(p, i.proc) },
		Pin: func(p *process, m []mount) *pinnedNamespace {
			n := pinNamespace(p, m, i.proc)
			pinned[n.Identity] = true
			return n
		},
		Cleanup: runCleanup,
		Active:  func(checked []string) { activeCheck(checked, i.proc, i.o.LocalRoot != "") },
		Wait:    2 * time.Second, Settle: 500 * time.Millisecond,
	}
}
func stopHelpers(o options, rs []string, proc string, c helperControl) any {
	need(o.OptIn && o.Maintenance, "helpers stop requires --opt-in --maintenance-ack (Built-in selected, new helper requests prevented)")
	pl := c.Scan()
	need(len(pl.Blocked) == 0, "unreadable/ambiguous process state; inspect helpers status")
	need(len(pl.Targets) <= 256, "helper target count bound")
	fmt.Fprintln(os.Stderr, string(jsonBytes(pl)))
	type targetHandle struct {
		p *process
		h handle
	}
	hs := []targetHandle{}
	ns := map[inode]*pinnedNamespace{}
	defer func() {
		for _, h := range hs {
			h.h.Close()
		}
		for _, n := range ns {
			n.Close()
		}
	}()
	if o.ForceUnmount {
		for _, p := range pl.Targets {
			if !p.Private || len(selectedMounts(p.Mounts, p.Generation+"/"+rootfs)) == 0 {
				continue
			}
			if ns[p.Namespace] != nil {
				continue
			}
			expected := cleanupPlan(p, pl, rs, proc)
			ns[p.Namespace] = c.Pin(p, expected)
		}
	}
	depth := func(p *process) int {
		seen := map[int]bool{}
		for p != nil && !seen[p.PID] {
			seen[p.PID] = true
			p = pl.Processes[p.PPID]
		}
		return len(seen)
	}
	sort.Slice(pl.Targets, func(a, b int) bool { return depth(pl.Targets[a]) > depth(pl.Targets[b]) })
	for _, p := range pl.Targets {
		hs = append(hs, targetHandle{p, c.Handle(p)})
	}
	signals := []map[string]any{}
	send := func(h targetHandle, sig unix.Signal) {
		if h.h.Send(sig) {
			signals = append(signals, map[string]any{"pid": h.p.PID, "signal": sig.String()})
		}
	}
	for _, h := range hs {
		send(h, unix.SIGTERM)
	}
	wait := func() []targetHandle {
		end := time.Now().Add(c.Wait)
		for {
			alive := []targetHandle{}
			for _, h := range hs {
				if h.h.Alive() {
					alive = append(alive, h)
				}
			}
			if len(alive) == 0 || time.Now().After(end) {
				return alive
			}
			time.Sleep(20 * time.Millisecond)
		}
	}
	alive := wait()
	if len(alive) > 0 && o.ForceKill {
		for _, h := range alive {
			send(h, unix.SIGKILL)
		}
		alive = wait()
	}
	need(len(alive) == 0, "helpers still alive; optional --force-kill required; no mutation/cleanup")
	latest := c.Scan()
	need(len(latest.Blocked) == 0 && len(latest.Targets) == 0, "helper restarted or state became ambiguous; no kill loop")
	cleanups := []any{}
	for id, n := range ns {
		for _, p := range latest.Processes {
			if p.PID == os.Getpid() {
				continue
			}
			need(p.Namespace != id, "namespace has another owner")
			for _, v := range p.FDIDs {
				need(v != id, "namespace pinned by another FD owner")
			}
		}
		cleanups = append(cleanups, c.Cleanup(n))
	}
	for id, n := range ns {
		n.Close()
		delete(ns, id)
	}
	time.Sleep(c.Settle)
	latest = c.Scan()
	need(len(latest.Blocked) == 0 && len(latest.Targets) == 0, "helper respawned after stop")
	checked := append([]string{}, rs...)
	for _, p := range pl.Targets {
		if !contains(checked, p.Generation) {
			checked = append(checked, p.Generation)
		}
	}
	c.Active(checked)
	return map[string]any{"stopped": true, "signals": signals, "private_cleanup": cleanups, "host_processes_preserved": true, "activation": false}
}
func (i *installer) helpers() any {
	r := i.readRegistry()
	found := i.discover(r)
	rs := roots(found, i.dest)
	if i.o.Helper == "status" {
		return scan(rs, i.proc, i.o.LocalRoot != "", i.o.R1Hosts)
	}
	unlock := i.lock()
	defer unlock()
	return stopHelpers(i.o, rs, i.proc, i.helperControl(rs))
}

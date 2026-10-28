// asp2-install is an offline Linux maintenance tool. It never launches the payload.
package main

import (
	"flag"
	"fmt"
	"os"
)

type stringsFlag []string

func (s *stringsFlag) String() string     { return fmt.Sprint([]string(*s)) }
func (s *stringsFlag) Set(v string) error { *s = append(*s, v); return nil }
func run(args []string) any {
	if len(args) == 1 && args[0] == "--version" {
		return map[string]any{"source_revision": sourceRevision, "network": false, "activation": false}
	}
	need(len(args) > 0, "usage: asp2-install inspect|dry-run|install|status|rollback|uninstall|helpers status|stop")
	if args[0] == "_cleanup" {
		need(len(args) == 1, "invalid internal cleanup invocation")
		return cleanupChild()
	}
	o := options{Command: args[0]}
	args = args[1:]
	if o.Command == "helpers" {
		need(len(args) > 0 && (args[0] == "status" || args[0] == "stop"), "helpers requires status|stop")
		o.Helper = args[0]
		args = args[1:]
	}
	need(contains([]string{"inspect", "dry-run", "install", "status", "rollback", "uninstall", "helpers"}, o.Command), "unknown command")
	f := flag.NewFlagSet(o.Command, flag.ContinueOnError)
	f.StringVar(&o.Bundle, "bundle", "", "prepared .tar.gz (no URLs)")
	f.StringVar(&o.Destination, "destination", destination, "fixed production destination; override only with private --local-root")
	f.StringVar(&o.LocalRoot, "local-root", "", "offline private /tmp sandbox only")
	f.StringVar(&o.Generation, "generation", "", "exact UUID from status")
	f.StringVar(&o.LiveVendor, "live-vendor", "", "local A fixture vendor; production always /vendor")
	f.BoolVar(&o.OptIn, "opt-in", false, "authorize maintenance writes")
	f.BoolVar(&o.Confirm, "confirm-inactive", false, "acknowledge inactive install/update/removal")
	f.BoolVar(&o.Maintenance, "maintenance-ack", false, "Built-in selected and new helper requests prevented")
	f.BoolVar(&o.ForceKill, "force-kill", false, "SIGKILL only confirmed survivors after SIGTERM")
	f.BoolVar(&o.ForceUnmount, "force-unmount", false, "detach only confirmed private owned namespace mounts")
	var hosts stringsFlag
	f.Var(&hosts, "r1-host", "explicit trusted R1 executable for parent/FD/IPC proof (repeatable)")
	must(f.Parse(args))
	need(f.NArg() == 0, "unexpected positional arguments")
	o.R1Hosts = []string(hosts)
	need((!o.ForceKill && !o.ForceUnmount) || (o.Command == "helpers" && o.Helper == "stop"), "force flags require explicit helpers stop")
	if o.Command == "inspect" {
		need(o.Bundle != "", "inspect requires --bundle")
		t := loadBundle(o.Bundle)
		r := validate(t)
		return map[string]any{"mode": r["mode"], "scope": r["scope"], "footprint": t.footprint(), "activation": false}
	}
	write := o.Command == "install" || o.Command == "rollback" || o.Command == "uninstall" || o.Command == "helpers" && o.Helper == "stop"
	i := newInstaller(o, write)
	switch o.Command {
	case "dry-run", "install":
		need(o.Bundle != "", "command requires --bundle")
		t := loadBundle(o.Bundle)
		if o.Command == "dry-run" {
			return i.plan(t)
		}
		return i.install(t)
	case "status":
		return i.status()
	case "rollback":
		return i.mutate(false)
	case "uninstall":
		return i.mutate(true)
	case "helpers":
		return i.helpers()
	}
	panic("unreachable")
}

var sourceRevision = "development"

func main() {
	out, err := guarded(func() any { return run(os.Args[1:]) })
	if err != nil {
		fmt.Fprintln(os.Stderr, "ASP2 installer REFUSED:", err)
		os.Exit(2)
	}
	fmt.Println(string(jsonBytes(out)))
}

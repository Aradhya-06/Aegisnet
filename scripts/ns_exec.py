#!/usr/bin/env python3
"""Restricted command runner for AegisNet  (the ONLY privileged entry point).

Django runs as a normal user. Everything that needs root (executing inside a
lab network namespace, packet capture, route changes) goes through this script,
which is the single thing you allow in sudoers (see scripts/print_sudoers.sh).

It never uses a shell and only runs commands from a small allow-list with
validated arguments:

  * the target namespace must be one of aegis_{a,r1,r2,r3,b,c}  (or --host)
  * IP arguments must be inside the lab ranges 10.10.0.0/16 or 127.0.0.0/8
  * `ip` is read-only except `ip route add|replace|del <lab-subnet> via <lab-ip>`
  * tcpdump may only write under <project>/data/pcaps and never use -z
  * python is limited to the project's own communication modules, and any file
    path argument must live under <project>/data

Usage:  ns_exec.py (--node aegis_x | --host) -- <command> [args...]
        ns_exec.py --check

Standard library only, so it can run with `python3 -I`.
IMPORTANT: if you allow this in sudoers it is effectively root for anyone who
can edit the project files. Use it on your own lab machine or VM only.
"""
import ipaddress
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
PCAP_DIR = os.path.join(DATA_DIR, "pcaps")
LAB_NETS = [ipaddress.ip_network("10.10.0.0/16"), ipaddress.ip_network("127.0.0.0/8")]
NODES = {"aegis_" + n for n in ("a", "r1", "r2", "r3", "b", "c")}
PY_MODULES = {
    "communication.tcp_server", "communication.udp_server", "communication.client",
    "communication.test_services", "communication.traffic", "communication.probe", "communication.loadgen",
}
PATH_FLAGS = {"--file", "--save-dir", "--out", "--cert", "--key"}
SAFE_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"


class Refused(Exception):
    pass


def lab_ip(value):
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        raise Refused("not an IP address: %r" % value)
    if not any(ip in net for net in LAB_NETS):
        raise Refused("address outside the lab ranges: %s" % value)
    return value


def lab_prefix(value):
    try:
        net = ipaddress.ip_network(value, strict=False)
    except ValueError:
        raise Refused("not a network: %r" % value)
    if not any(net.subnet_of(n) for n in LAB_NETS if n.version == net.version):
        raise Refused("network outside the lab ranges: %s" % value)
    return value


def number(value, lo, hi, what="value"):
    if not re.fullmatch(r"\d+", value or ""):
        raise Refused("%s must be an integer" % what)
    n = int(value)
    if not lo <= n <= hi:
        raise Refused("%s must be between %d and %d" % (what, lo, hi))
    return str(n)


def fnumber(value, lo, hi, what="value"):
    if not re.fullmatch(r"\d+(\.\d+)?", value or ""):
        raise Refused("%s must be a number" % what)
    n = float(value)
    if not lo <= n <= hi:
        raise Refused("%s must be between %s and %s" % (what, lo, hi))
    return value


def ifname(value):
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,15}", value or ""):
        raise Refused("bad interface name: %r" % value)
    return value


def need(argv, i, what):
    if i >= len(argv):
        raise Refused("missing value for %s" % what)
    return argv[i]


# --------------------------------------------------------------------------- validators
def v_ping(a):
    out, i, dest = ["ping"], 1, None
    while i < len(a):
        t = a[i]
        if t in ("-q", "-n"):
            out.append(t)
        elif t in ("-c", "-W", "-w", "-s"):
            i += 1
            hi = {"-c": 100, "-W": 10, "-w": 120, "-s": 1400}[t]
            out += [t, number(need(a, i, t), 1, hi, t)]
        elif t == "-i":
            i += 1
            out += [t, fnumber(need(a, i, t), 0.2, 10, t)]
        elif t.startswith("-"):
            raise Refused("ping option not allowed: " + t)
        else:
            if dest is not None:
                raise Refused("only one ping destination allowed")
            dest = lab_ip(t)
        i += 1
    if dest is None:
        raise Refused("ping needs a destination")
    return out + [dest]


def v_traceroute(a):
    out, i, dest = ["traceroute"], 1, None
    while i < len(a):
        t = a[i]
        if t in ("-n", "-I"):
            out.append(t)
        elif t in ("-m", "-w", "-q"):
            i += 1
            hi = {"-m": 30, "-w": 5, "-q": 3}[t]
            out += [t, number(need(a, i, t), 1, hi, t)]
        elif t.startswith("-"):
            raise Refused("traceroute option not allowed: " + t)
        else:
            if dest is not None:
                raise Refused("only one destination allowed")
            dest = lab_ip(t)
        i += 1
    if dest is None:
        raise Refused("traceroute needs a destination")
    return out + [dest]


def v_ss(a):
    out, i = ["ss"], 1
    while i < len(a):
        t = a[i]
        if re.fullmatch(r"-[tuanlpHs46eio]+", t):
            out.append(t)
        elif t == "state":
            i += 1
            st = need(a, i, "state")
            if st not in ("established", "listening", "connected", "all", "syn-sent", "time-wait"):
                raise Refused("ss state not allowed")
            out += ["state", st]
        else:
            raise Refused("ss argument not allowed: " + t)
        i += 1
    return out


def v_netstat(a):
    out = ["netstat"]
    for t in a[1:]:
        if re.fullmatch(r"-[tuanlpr]+", t):
            out.append(t)
        else:
            raise Refused("netstat argument not allowed: " + t)
    return out


def v_ifconfig(a):
    out = ["ifconfig"]
    for t in a[1:]:
        if t == "-a" or re.fullmatch(r"[A-Za-z0-9_.-]{1,15}", t):
            out.append(t)
        else:
            raise Refused("ifconfig argument not allowed: " + t)
    return out


def v_nslookup(a):
    out = ["nslookup"]
    positional = 0
    for t in a[1:]:
        if re.fullmatch(r"-port=\d{1,5}", t):
            out.append(t)
        elif t.startswith("-"):
            raise Refused("nslookup option not allowed: " + t)
        else:
            positional += 1
            if positional == 1:
                if not re.fullmatch(r"[A-Za-z0-9._-]{1,253}", t):
                    raise Refused("bad host name")
                out.append(t)
            elif positional == 2:
                out.append(lab_ip(t))
            else:
                raise Refused("too many arguments")
    if positional == 0:
        raise Refused("nslookup needs a name")
    return out


def v_ip(a):
    i, out = 1, ["ip"]
    while i < len(a) and a[i] in ("-j", "-s", "-d", "-brief", "-4", "-o", "-json", "-stats"):
        out.append(a[i])
        i += 1
    rest = a[i:]
    if not rest:
        raise Refused("ip needs an object")
    obj = rest[0]
    if obj in ("addr", "address", "link", "neigh", "neighbor"):
        if len(rest) == 1:
            return out + rest
        if rest[1] not in ("show", "list", "ls"):
            raise Refused("ip %s %s is not allowed (read-only)" % (obj, rest[1]))
        tail = rest[2:]
        if tail and not (len(tail) == 2 and tail[0] == "dev" and ifname(tail[1])):
            raise Refused("unsupported ip show arguments")
        return out + rest
    if obj == "route":
        if len(rest) == 1 or rest[1] in ("show", "list", "ls"):
            tail = rest[2:]
            if tail and not (len(tail) == 2 and tail[0] == "dev" and ifname(tail[1])):
                raise Refused("unsupported ip route show arguments")
            return out + rest
        if rest[1] == "get":
            if len(rest) != 3:
                raise Refused("ip route get needs one address")
            return out + ["route", "get", lab_ip(rest[2])]
        if rest[1] in ("replace", "add", "del", "delete"):
            if len(rest) < 3:
                raise Refused("route needs a destination")
            cmd = ["route", rest[1], lab_prefix(rest[2])]
            j = 3
            while j < len(rest):
                k = rest[j]
                if k == "via":
                    j += 1
                    cmd += ["via", lab_ip(need(rest, j, "via"))]
                elif k == "dev":
                    j += 1
                    cmd += ["dev", ifname(need(rest, j, "dev"))]
                elif k == "metric":
                    j += 1
                    cmd += ["metric", number(need(rest, j, "metric"), 0, 10000, "metric")]
                else:
                    raise Refused("route option not allowed: " + k)
                j += 1
            return out + cmd
        raise Refused("ip route %s not allowed" % rest[1])
    raise Refused("ip object not allowed: " + obj)


def v_tcpdump(a):
    out, i = ["tcpdump", "-Z", "root"], 1
    have_iface = False
    while i < len(a):
        t = a[i]
        if t in ("-n", "-nn", "-U", "-p", "-q", "--immediate-mode"):
            out.append(t)
        elif t == "-i":
            i += 1
            out += [t, ifname(need(a, i, t))]
            have_iface = True
        elif t == "-c":
            i += 1
            out += [t, number(need(a, i, t), 1, 20000, "-c")]
        elif t == "-s":
            i += 1
            out += [t, number(need(a, i, t), 64, 4096, "-s")]
        elif t == "-w":
            i += 1
            path = os.path.realpath(need(a, i, t))
            if not path.startswith(PCAP_DIR + os.sep) or not path.endswith(".pcap"):
                raise Refused("tcpdump -w must be a .pcap file under " + PCAP_DIR)
            out += [t, path]
        elif t.startswith("-"):
            raise Refused("tcpdump option not allowed: " + t)
        else:
            break
        i += 1
    if not have_iface:
        raise Refused("tcpdump needs -i <interface>")
    for tok in a[i:]:
        if tok.startswith("-") or not re.fullmatch(r"[A-Za-z0-9.:/()!&|<>=_-]+", tok):
            raise Refused("bad capture filter token: %r" % tok)
        out.append(tok)
    return out


def v_python(a):
    if len(a) < 3 or a[1] != "-m" or a[2] not in PY_MODULES:
        raise Refused("python is limited to: " + ", ".join(sorted(PY_MODULES)))
    args = a[3:]
    for idx, tok in enumerate(args):
        if idx > 0 and args[idx - 1] in PATH_FLAGS:
            real = os.path.realpath(tok)
            if not (real == DATA_DIR or real.startswith(DATA_DIR + os.sep)):
                raise Refused("path outside the project data directory: " + tok)
    return [sys.executable, "-u", "-m", a[2]] + args


VALIDATORS = {
    "ping": v_ping, "traceroute": v_traceroute, "ss": v_ss, "ip": v_ip,
    "tcpdump": v_tcpdump, "nslookup": v_nslookup, "netstat": v_netstat,
    "ifconfig": v_ifconfig, "python3": v_python, "python": v_python,
}


def validate(argv):
    """Return the vetted argv or raise Refused. Pure function, used by tests."""
    if not argv:
        raise Refused("no command given")
    fn = VALIDATORS.get(argv[0])
    if fn is None:
        raise Refused("command not allowed: %s" % argv[0])
    return fn(argv)


def validate_node(node):
    if node not in NODES:
        raise Refused("not a lab namespace: %r" % node)
    return node


def main(argv):
    if argv == ["--check"]:
        print("ns_exec ok")
        return 0
    try:
        if "--" not in argv:
            raise Refused("usage: ns_exec.py (--node aegis_x | --host) -- command ...")
        sep = argv.index("--")
        head, cmd = argv[:sep], argv[sep + 1:]
        node = None
        if head == ["--host"]:
            node = None
        elif len(head) == 2 and head[0] == "--node":
            node = validate_node(head[1])
        else:
            raise Refused("need exactly --host or --node <aegis_x>")
        final = validate(cmd)
    except Refused as exc:
        sys.stderr.write("ns_exec: refused: %s\n" % exc)
        return 126

    env = {"PATH": SAFE_PATH, "LANG": "C", "LC_ALL": "C", "PYTHONPATH": ROOT,
           "PYTHONUNBUFFERED": "1", "HOME": os.environ.get("HOME", "/tmp")}
    os.umask(0o022)
    os.chdir(ROOT)
    if node:
        final = ["ip", "netns", "exec", node] + final
    exe = shutil.which(final[0], path=SAFE_PATH) or final[0]
    try:
        os.execve(exe, final, env)
    except OSError as exc:
        sys.stderr.write("ns_exec: cannot run %s: %s\n" % (final[0], exc))
        return 127


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

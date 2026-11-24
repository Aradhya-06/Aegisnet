"""AegisNet unit tests. Run:  python manage.py test tests
Every fixture here is a test input, clearly labelled; none is shown in the application."""
import os, re, shlex, socket, subprocess, sys, tempfile, threading
from pathlib import Path

os.environ.setdefault("AEGISNET_FORCE_SIM", "1")
from django.test import SimpleTestCase, TestCase, Client
from django.contrib.auth import get_user_model

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


# ------------------------------------------------------------------ privileged helper
class NsExecValidator(SimpleTestCase):
    def setUp(self):
        import ns_exec
        self.v, self.R = ns_exec.validate, ns_exec.Refused

    def test_allowed(self):
        self.v(["ping", "-c", "2", "10.10.2.2"])
        self.v(["ip", "-j", "addr"])
        self.v(["ip", "route", "replace", "10.10.5.0/30", "via", "10.10.3.2"])

    def test_refused(self):
        bad = [["ping", "-c", "2", "8.8.8.8"], ["rm", "-rf", "/"], ["bash", "-c", "id"], ["sh"],
               ["ip", "route", "add", "default", "via", "10.10.1.2"],
               ["ip", "route", "del", "0.0.0.0/0"], ["ip", "link", "delete", "eth0"],
               ["ip", "route", "replace", "10.10.5.0/30", "via", "192.168.1.1"],
               ["ping", "-c", "2", "10.10.2.2; id"], ["python", "-c", "print(1)"], [],
               ["tcpdump", "-i", "eth0", "-w", "/etc/passwd"], ["tcpdump", "-z", "sh", "-w", "x.pcap"]]
        for argv in bad:
            with self.assertRaises(self.R, msg=str(argv)):
                self.v(argv)

    def test_node_names(self):
        import ns_exec
        ns_exec.validate_node("aegis_r1")
        for n in ("r1", "host", "../etc", "r1;id", ""):
            with self.assertRaises(self.R):
                ns_exec.validate_node(n)


# ------------------------------------------------------------------ routing
def lab_graph():
    from routing.topology import Graph
    g = Graph()
    for n in "a r1 r2 r3 b c".split():
        g.add_node(n)
    for x, y in [("a", "r1"), ("r1", "r2"), ("r1", "r3"), ("r3", "r2"), ("r2", "b"), ("r3", "c")]:
        g.add_link(x, y, 1)
    return g


class Routing(SimpleTestCase):
    def test_dijkstra_primary_then_backup(self):
        from routing.link_state import shortest_path
        g = lab_graph()
        r = shortest_path(g, "a", "b")
        self.assertEqual(r["path"], ["a", "r1", "r2", "b"]); self.assertEqual(r["cost"], 3)
        g.links[frozenset(("r1", "r2"))]["enabled"] = False
        r = shortest_path(g, "a", "b")
        self.assertEqual(r["path"], ["a", "r1", "r3", "r2", "b"]); self.assertEqual(r["cost"], 4)

    def test_unreachable(self):
        from routing.link_state import shortest_path
        g = lab_graph()
        g.links[frozenset(("r2", "b"))]["enabled"] = False
        r = shortest_path(g, "a", "b")
        self.assertFalse(r["path"]); self.assertIsNone(r["cost"])

    def test_weighted(self):
        from routing.link_state import shortest_path
        from routing.topology import Graph
        g = Graph()
        for n in "sabt": g.add_node(n)
        g.add_link("s", "a", 1); g.add_link("a", "t", 10); g.add_link("s", "b", 3); g.add_link("b", "t", 3)
        self.assertEqual(shortest_path(g, "s", "t")["path"], ["s", "b", "t"])

    def test_dv_matches_dijkstra(self):
        from routing.link_state import shortest_path
        from routing.distance_vector import run_distance_vector
        g = lab_graph()
        for src, dst in [("a", "b"), ("a", "c"), ("b", "c")]:
            dv, ls = run_distance_vector(g, src, dst), shortest_path(g, src, dst)
            self.assertEqual(dv["cost"], ls["cost"], (src, dst))
            self.assertEqual(dv["path"], ls["path"], (src, dst))

    def test_dv_after_failure(self):
        from routing.distance_vector import run_distance_vector
        g = lab_graph(); g.links[frozenset(("r1", "r2"))]["enabled"] = False
        self.assertEqual(run_distance_vector(g, "a", "b")["cost"], 4)

    def test_validation(self):
        from routing.topology import TopologyError
        g = lab_graph()
        for args in [("a", "a", 1), ("a", "zz", 1), ("a", "b", 0), ("a", "b", "x"), ("a", "b", 5000)]:
            with self.assertRaises(TopologyError):
                g.add_link(*args)


# ------------------------------------------------------------------ protocol & sockets
class Protocol(SimpleTestCase):
    def test_frame_roundtrip(self):
        from communication.protocol import send_frame, recv_frame
        a, b = socket.socketpair()
        send_frame(a, {"type": "x", "n": 1}, b"\x00body\xff"); h, body = recv_frame(b)
        self.assertEqual(h["n"], 1); self.assertEqual(body, b"\x00body\xff")

    def test_address_and_filename_rules(self):
        from communication.protocol import ensure_lab_address, safe_filename, ProtocolError
        ensure_lab_address("10.10.2.2"); ensure_lab_address("127.0.0.1")
        for bad in ("8.8.8.8", "example.com", "192.168.0.1", "10.11.0.1"):
            with self.assertRaises(ProtocolError):
                ensure_lab_address(bad)
        self.assertEqual(safe_filename("../../etc/passwd"), "passwd")
        self.assertNotIn("/", safe_filename("a/b\\c d.txt"))


class TcpUdpLoopback(SimpleTestCase):
    """Real servers (subprocesses) and the real client, over 127.0.0.1."""
    def _serve(self, module, port, *extra):
        d = tempfile.mkdtemp()
        p = subprocess.Popen([sys.executable, "-m", module, "--host", "127.0.0.1", "--port", str(port), *extra],
                             cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        import time; time.sleep(1.0)
        self.addCleanup(lambda: (p.terminate(), p.wait(timeout=5)))
        return d

    def _client(self, *args):
        r = subprocess.run([sys.executable, "-m", "communication.client", *args], cwd=ROOT, capture_output=True, text=True, timeout=30)
        return __import__("json").loads(r.stdout.strip().splitlines()[-1])

    def test_tcp_message_echo_and_checksum(self):
        import hashlib
        d = self._serve("communication.tcp_server", 19001, "--save-dir", tempfile.mkdtemp())
        out = self._client("--proto", "tcp", "--host", "127.0.0.1", "--port", "19001", "--message", "hello")
        self.assertTrue(out["ok"], out); self.assertEqual(out["response"]["echo"], "hello")
        self.assertEqual(out["sha256_sent"], hashlib.sha256(b"hello").hexdigest())

    def test_udp_replies(self):
        self._serve("communication.udp_server", 19002)
        out = self._client("--proto", "udp", "--host", "127.0.0.1", "--port", "19002", "--message", "ping", "--count", "2")
        self.assertTrue(out["ok"], out); self.assertTrue(all(d["answered"] for d in out["datagrams"]))

    def test_external_destination_refused(self):
        r = subprocess.run([sys.executable, "-m", "communication.client", "--proto", "tcp", "--host", "8.8.8.8", "--port", "53", "--message", "x"],
                           cwd=ROOT, capture_output=True, text=True, timeout=20)
        out = __import__("json").loads(r.stdout.strip().splitlines()[-1])
        self.assertFalse(out["ok"])


# ------------------------------------------------------------------ NS2 trace parser
TRACE_FIXTURE = """\
+ 1.0 0 1 tcp 1000 ------- 1 0.0 4.0 0 1
- 1.0 0 1 tcp 1000 ------- 1 0.0 4.0 0 1
r 1.1 0 1 tcp 1000 ------- 1 0.0 4.0 0 1
+ 1.1 1 4 tcp 1000 ------- 1 0.0 4.0 0 1
r 1.2 1 4 tcp 1000 ------- 1 0.0 4.0 0 1
+ 2.0 0 1 tcp 1000 ------- 1 0.0 4.0 1 2
d 2.05 0 1 tcp 1000 ------- 1 0.0 4.0 1 2
"""


class TraceParser(SimpleTestCase):
    """FIXTURE = hand-written 2-packet trace used only to test arithmetic."""
    def test_counts(self):
        from simulation.trace_parser import parse_trace
        res = parse_trace(TRACE_FIXTURE.splitlines())
        fl = res["flows"][0] if isinstance(res["flows"], list) else list(res["flows"].values())[0]
        self.assertEqual(fl["sent"], 2); self.assertEqual(fl["delivered"], 1); self.assertEqual(fl["dropped"], 1)
        self.assertAlmostEqual(fl["pdr"], 0.5); self.assertAlmostEqual(fl["loss_ratio"], 0.5)
        self.assertAlmostEqual(fl["avg_delay_ms"], 200.0, places=3)

    def test_empty(self):
        from simulation.trace_parser import parse_trace
        self.assertFalse(parse_trace([])["flows"])


# ------------------------------------------------------------------ packet parser
class PacketParser(SimpleTestCase):
    def test_dns_tcp_syn_arp_tls(self):
        from scapy.all import Ether, IP, UDP, TCP, DNS, DNSQR, ARP, Raw
        from packet_analyzer.parser import parse_packet
        r = parse_packet(1, Ether()/IP(src="10.10.1.1", dst="10.10.5.2")/UDP(sport=40000, dport=5353)/DNS(rd=1, qd=DNSQR(qname="lab.test")))
        self.assertEqual(r["proto"], "UDP"); self.assertIn("lab.test", r["info"])
        r = parse_packet(2, Ether()/IP(src="10.10.1.1", dst="10.10.5.2")/TCP(sport=40000, dport=9001, flags="S"))
        self.assertEqual(r["proto"], "TCP"); self.assertIn("S", r["tcp_flags"])
        r = parse_packet(3, Ether()/ARP(op=1, psrc="10.10.1.1", pdst="10.10.1.2"))
        self.assertEqual(r["proto"], "ARP")
        hello = bytes.fromhex("160301002e01000028030300") + b"\x00" * 32 + b"\x00\x00\x00"   # truncated test ClientHello
        parse_packet(4, Ether()/IP()/TCP(dport=443)/Raw(hello))        # must not raise on malformed TLS

    def test_parse_tls_garbage(self):
        from packet_analyzer.parser import parse_tls
        for blob in (b"", b"\x16", b"\x16\x03\x01\xff\xff", b"GET / HTTP/1.1\r\n"):
            parse_tls(blob)                                              # never raises


# ------------------------------------------------------------------ topology consistency
class TopologyConsistency(SimpleTestCase):
    def test_python_matches_shell(self):
        from core.topology_def import LINKS, NODES
        text = (ROOT / "scripts/lab_common.sh").read_text()
        block = re.search(r"^LINKS=\((.*?)^\)", text, re.S | re.M).group(1)
        shell = [tuple(l.strip().strip('"').split()) for l in block.strip().splitlines()]
        py = [(l[0], l[1], l[2], l[3], l[4], l[5], l[6]) for l in LINKS]
        self.assertEqual(shell, py)
        self.assertEqual(sorted(n[0] for n in NODES), sorted(re.search(r"^NODES=\((.*?)\)", text, re.M).group(1).split()))

    def test_scripts_syntax(self):
        for s in ROOT.glob("scripts/*.sh"):
            self.assertEqual(subprocess.run(["bash", "-n", str(s)]).returncode, 0, s.name)


# ------------------------------------------------------------------ Django-backed
class RecoveryPlan(TestCase):
    def setUp(self):
        from django.core.management import call_command
        call_command("setup_aegisnet")

    def test_backup_path_plan(self):
        from recovery.recovery_engine import plan_route_changes
        plan = plan_route_changes(["a", "r1", "r3", "r2", "b"])
        got = {(p["node"], p["dest"], p["via"]) for p in plan}
        self.assertIn(("r1", "10.10.5.0/30", "10.10.3.2"), got)          # r1 -> r3 towards B
        self.assertIn(("r3", "10.10.5.0/30", "10.10.4.2"), got)          # r3 -> r2
        self.assertIn(("r2", "10.10.1.0/30", "10.10.4.1"), got)          # reverse: r2 -> r3 towards A
        for p in plan:
            self.assertEqual(p["argv"][:3], ["ip", "route", "replace"])
            self.assertNotEqual(p["dest"], "default")

    def test_plan_commands_pass_the_helper(self):
        from recovery.recovery_engine import plan_route_changes
        import ns_exec
        for p in plan_route_changes(["a", "r1", "r3", "r2", "b"]):
            ns_exec.validate(p["argv"])

    def test_simulated_recovery_end_to_end(self):
        from core.models import Link
        from recovery.models import MonitoredFlow
        from recovery import recovery_engine as eng
        eng.inject_link_failure("r1-r2", confirm=True)
        self.assertTrue(Link.objects.get(name="r1-r2").admin_down)
        flow = MonitoredFlow.objects.get(name="A to B")
        ev = eng.recover_flow(flow, confirm=True, trigger="manual")
        self.assertEqual(ev.mode, "simulated")
        self.assertEqual(list(ev.new_path), ["a", "r1", "r3", "r2", "b"])
        self.assertEqual(ev.result, "success")
        eng.restore_all()
        self.assertFalse(Link.objects.get(name="r1-r2").admin_down)

    def test_injection_needs_confirmation(self):
        from recovery import recovery_engine as eng
        from core.models import Link
        with self.assertRaises(Exception):
            eng.inject_link_failure("r1-r2", confirm=False)
        self.assertFalse(Link.objects.get(name="r1-r2").admin_down)
        with self.assertRaises(Exception):
            eng.inject_link_failure("eth0", confirm=True)               # not a lab link


class Views(TestCase):
    PAGES = ["/", "/about/", "/monitoring/", "/communication/", "/packets/", "/routing/",
             "/simulation/", "/recovery/", "/ml/"]

    def setUp(self):
        from django.core.management import call_command
        call_command("setup_aegisnet")
        get_user_model().objects.create_user("t", password="t-pass-123")
        self.c = Client()

    def test_login_required(self):
        for p in self.PAGES:
            self.assertEqual(self.c.get(p).status_code, 302, p)

    def test_pages_render(self):
        self.c.login(username="t", password="t-pass-123")
        for p in self.PAGES:
            self.assertEqual(self.c.get(p).status_code, 200, p)

    def test_mutating_endpoints_reject_get_and_unauthenticated(self):
        r = self.c.post("/recovery/api/inject/", {"link": "r1-r2", "confirm": "1"})
        self.assertEqual(r.status_code, 302)

    def test_simulated_state_is_labelled_and_has_no_invented_numbers(self):
        self.c.login(username="t", password="t-pass-123")
        d = self.c.get("/recovery/api/state/").json()
        self.assertFalse(d["lab"]["live"])
        for l in d["links"]:
            self.assertIsNone(l["latency"], "latency must be null when nothing was measured")


# ------------------------------------------------------------------ regressions found in the live lab
class Regressions(TestCase):
    def setUp(self):
        from django.core.management import call_command
        call_command("setup_aegisnet")

    def _fake(self, rc, stdout="", stderr="", error=""):
        from types import SimpleNamespace
        return SimpleNamespace(returncode=rc, stdout=stdout, stderr=stderr, error=error, ok=rc == 0,
                               text=stdout + stderr)

    def test_unreachable_ping_is_a_measured_failure_not_unknown(self):
        """Interface down => `ping: connect: Network is unreachable` (rc 2, no statistics)."""
        from unittest import mock
        from monitoring import services as mon
        with mock.patch.object(mon.netenv, "run_in_node", return_value=self._fake(2, stderr="ping: connect: Network is unreachable\n")):
            p = mon.ping("r1", "10.10.2.2", count=2)
        self.assertTrue(p["unreachable"]); self.assertFalse(p["reachable"])

    def test_helper_failure_is_not_reported_as_unreachable(self):
        from unittest import mock
        from monitoring import services as mon
        with mock.patch.object(mon.netenv, "run_in_node", return_value=self._fake(126, error="privilege helper not available")):
            p = mon.ping("r1", "10.10.2.2", count=2)
        self.assertFalse(p["unreachable"])                     # could not measure -> stays 'unknown'

    def test_http_client_ignores_proxy_environment(self):
        """urllib would send lab traffic to $HTTP_PROXY; the lab client must connect directly."""
        import http.server, threading
        from communication.traffic import http_get

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200); self.end_headers(); self.wfile.write(b"direct")
            def log_message(self, *a): pass
        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        old = {k: os.environ.get(k) for k in ("http_proxy", "HTTP_PROXY", "no_proxy", "NO_PROXY")}
        os.environ.update(http_proxy="http://127.0.0.1:9", HTTP_PROXY="http://127.0.0.1:9")
        os.environ.pop("no_proxy", None); os.environ.pop("NO_PROXY", None)
        try:
            r = http_get("127.0.0.1", srv.server_address[1], timeout=3)
        finally:
            srv.shutdown()
            for k, v in old.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self.assertTrue(r["ok"], r); self.assertEqual(r["body"], "direct")


# ------------------------------------------------------------------ ML pipeline (code path only)
class MLPipeline(SimpleTestCase):
    """SYNTHETIC FIXTURE generated by a seeded RNG. It exercises the code only; the metrics it
    produces say nothing about real networks and must never be quoted as results."""

    def _fixture(self, per_class=40):
        import csv, random
        from ml_extension.features import FEATURES
        rnd = random.Random(1)
        path = Path(tempfile.mkdtemp()) / "fixture.csv"
        centres = {"normal": 5, "moderate": 55, "high": 95}
        with open(path, "w", newline="") as f:
            w = csv.writer(f); w.writerow(FEATURES + ["label"])
            for lab, u in centres.items():
                for _ in range(per_class):
                    w.writerow([u + rnd.uniform(-4, 4), u / 10, 1 + u / 20, u / 30, 2, 100 + u] + [lab])
        return path

    def test_train_structure_and_predict(self):
        from ml_extension import train as T, predict as P
        path = self._fixture()
        res = T.train(path, path.parent)
        self.assertEqual(res["dataset"]["train_rows"] + res["dataset"]["test_rows"], 120)
        for key in ("ml", "threshold_baseline"):
            self.assertEqual(len(res[key]["confusion_matrix"]), 3)
            self.assertEqual(sum(map(sum, res[key]["confusion_matrix"])), res["dataset"]["test_rows"])
        out = P.predict_row(path.parent, {"utilization_pct": 95, "throughput_mbps": 9, "latency_ms": 6, "loss_pct": 3,
                                          "active_connections": 2, "packets_per_sec": 200})
        self.assertIn(out["ml"], ("normal", "moderate", "high"))
        self.assertAlmostEqual(sum(out["probabilities"].values()), 1.0, places=1)

    def test_refuses_tiny_dataset(self):
        from ml_extension import train as T
        path = self._fixture(per_class=3)
        with self.assertRaises(T.MLError):
            T.train(path, path.parent)

    def test_refuses_missing_columns(self):
        from ml_extension import train as T
        bad = Path(tempfile.mkdtemp()) / "bad.csv"; bad.write_text("a,b\n1,2\n")
        with self.assertRaises(T.MLError):
            T.load_dataset(bad)

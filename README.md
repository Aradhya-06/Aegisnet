# AegisNet — Adaptive Network Monitoring, Traffic Analysis and Self-Healing System

Computer Networks lab major project (JIIT). One Django application that **measures** a small network,
**generates and captures** real traffic in it, **computes routes**, **detects faults**
and **repairs the network by itself** — all inside an isolated, throw-away test network of Linux namespaces.

Stack: Django · SQLite · Bootstrap 5 · Chart.js · AJAX polling (no React / FastAPI).
Everything the browser needs is vendored in `static/vendor/` — the UI works offline.

---------------------------------------------------------------------------------------------------

## 1. What is real and what is simulated

| Area | Real (measured/executed) | Simulated (labelled as such in the UI) |
|---|---|---|
| Monitoring | psutil counters, `ip -j`, `ping`, `ss` on the host and inside lab nodes | — |
| TCP/UDP | Python sockets running **inside** the namespaces; handshake/FIN steps timed with `perf_counter` | — |
| Packet analyzer | `tcpdump` → PCAP → Scapy decode (+ optional TShark cross-check) | — |
| Routing | Dijkstra / Distance Vector on the lab graph; the recovery engine installs the result with `ip route replace` | The *Routing Visualizer* sandbox graph (never touches the kernel) |
| Fault detection / recovery | Real ping/connect probes; real route changes; verification by a real ping | **Fallback mode** (no namespaces/root): acts on the graph model only and says so |
| NS2 | NS2 actually executes the Tcl and the trace file is parsed | Whole page is a simulation of a *simulated* network |
| ML (optional) | scikit-learn on a dataset **you** collect or upload | — |

No latency, loss, throughput or accuracy number is hard-coded. If something cannot be measured the UI shows
"—"/"unknown", not a made-up value. Every response/log carries `mode: live | simulated`.

## 2. Test network

```
              primary (cost 1)
 PC A ── R1 ──────────────────── R2 ── PC B
          \                      /
           ╰──── R3 ───────────╯      backup path
                 │
               PC C
```
Six namespaces `aegis_{a,r1,r2,r3,b,c}`, six veth links on `/30` subnets `10.10.1–6.0/30`.
Primary A→B = `A-R1-R2-B` (cost 3). If `r1-r2` fails, the recovery engine installs `A-R1-R3-R2-B` (cost 4).
Note: R3/PC C were added to your sketch so that a genuine backup path exists.

## 3. Install and run

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt            # add requirements-ml.txt for the ML page
python manage.py migrate
python manage.py setup_aegisnet --create-user admin --password 'choose-a-password'
python manage.py runserver 127.0.0.1:8000  # sign in at http://127.0.0.1:8000
```
Without further setup the site runs in **SIMULATED** mode (badge in the top bar).

### Live lab (Linux, root once)
```bash
sudo apt install iproute2 iputils-ping tcpdump traceroute tshark ns2      # tshark/ns2 optional
sudo scripts/setup_network.sh              # create the namespaces       (--dry-run to preview)
sudo scripts/verify_network.sh             # should be all PASS
sudo scripts/print_sudoers.sh              # prints a sudoers snippet; install with visudo
export AEGISNET_PRIV_PYTHON=$(command -v python3)
python manage.py runserver                 # badge now says LIVE
```
Django never runs as root. It calls **one** helper, `scripts/ns_exec.py` (via `sudo -n`), which allow-lists
commands and arguments (lab IPs only, no shell, read-only `ip` except lab-subnet routes).
> ⚠ The helper runs this project's Python modules as root. Use a VM or personal machine where you are the only user.

Switches: `AEGISNET_FORCE_SIM=1` (force simulation), `AEGISNET_DATA_DIR`, `AEGISNET_SECRET_KEY`,
`AEGISNET_ALLOWED_HOSTS`, `AEGISNET_DEBUG`, `AEGISNET_PING_TARGET`.

Cleanup: `sudo scripts/restore_network.sh all` (undo failures/route changes) · `sudo scripts/cleanup_network.sh` (delete the lab).

## 4. Pages

| Page | What it does |
|---|---|
| Dashboard | Mode, topology drawing with live link colours, probe-all, recent events |
| Monitoring | Interfaces/IPs/MACs/counters, rates, connections, ping, allow-listed Linux command runner |
| TCP / UDP | Start servers in nodes, send text/files, step-by-step handshake & FIN timeline |
| Packet Analyzer | Capture on a lab interface with generated HTTP/DNS/TLS/TCP/UDP/ICMP, filter, decode, download PCAP, TShark view |
| Routing | Build/edit a graph, Link State vs Distance Vector, step logs, count-to-infinity, load the lab topology |
| NS2 | Four scenarios (normal, congestion, failed link, lossy link), throughput/delay/PDR/loss comparison |
| Fault & Recovery | Failure injection (dry-run + confirm), detector, automatic recovery, rollback, history |
| ML (optional) | Collect/upload dataset → Random Forest → compare with threshold detector |
| Documentation | Architecture, CO mapping, demo script, safety rules |

## 5. Course-outcome mapping
Each row points to a feature that runs (the same table is on the Documentation page).

| CO | Topic | Where in AegisNet |
|---|---|---|
| CO1 | Interfaces, addressing, Linux tools, TCP/IP | Monitoring page; `scripts/setup_network.sh` lab |
| CO2 | TCP/UDP socket programming | TCP/UDP page; `communication/` |
| CO3 | Routing algorithms, NS2 evaluation | Routing page; NS2 page; recovery engine uses the same Dijkstra |
| CO4 | Packet visualisation and analysis | Packet Analyzer page |
| CO5 | Real-world application | Fault & Recovery (detect → heal → verify → rollback) |

## 6. Final demonstration (12 steps)
1. Start Django, sign in; badge says **LIVE**.  2. `sudo scripts/verify_network.sh` → all PASS; Dashboard → *Probe links*.
3. Monitoring: interfaces and addresses of PC A and R1; run `ip route` in R1.  4. TCP/UDP: start `tcp-b`/`udp-b`, send a message and a file from A to B; read the handshake/FIN timeline.
5. Packet Analyzer: capture `r1 / r1-a` with all traffic types; open the TLS handshake; download the PCAP and open it in Wireshark.
6. Routing: load lab topology, A→B with Dijkstra and DV; disable `r1-r2`, rerun → path changes.
7. Recovery page: start the background detector with *automatic recovery*.  8. Tick confirm, **inject failure on r1-r2**.
9. Detector raises *Link failure*, *Interface down*, *End-to-end path broken*; recovery installs `A-R1-R3-R2-B`.
10. Verification ping succeeds (3/3); show `traceroute` from A — it now crosses `10.10.3.2` and `10.10.4.2`.
11. Click **Rollback** → alerts resolve, path returns to `A-R1-R2-B`.  12. NS2 page: compare scenarios A and C (labelled simulated).

## 7. Tests
```bash
python manage.py test tests          # 34 tests, ~10 s, run in simulation mode
```
Covers: helper allow-list (incl. refusal cases), Dijkstra/DV agreement, framing, real
TCP/UDP over loopback, NS2 trace arithmetic (hand-written fixture), TLS/DNS/ARP parsing, topology ↔ shell-table
consistency, recovery planning (each command must pass the helper), simulated recovery, page rendering and login
protection, and regressions found in the live lab (see §9). The ML tests use a **synthetic fixture** and only prove the code runs.

## 8. Layout
```
config/  core/  monitoring/  communication/  packet_analyzer/  routing/  simulation/
recovery/  ml_extension/  templates/  static/  scripts/  tests/  docs/  data/ (runtime, git-ignore it)
```
Database tables: see `docs/ARCHITECTURE.md`.

## 9. Verified vs. not verified (read before presenting)
Verified here in a Linux sandbox with a live lab: setup/verify/cleanup scripts, real TCP/UDP,
capture of 6 traffic types, failure injection → detection → recovery → verified ping →
traceroute on the backup path → rollback, and the 39 unit tests.

Bugs this live run exposed (and fixed): a downed interface was classed *unknown* instead of *down* (so recovery
saw nothing to fix); the HTTP test client went through the sandbox's `HTTP_PROXY` instead of the lab address.

**Not verified / limitations**
* **ML collection and `scripts/impair_link.sh` were never run** — the sandbox kernel has no `sch_netem`/`sch_tbf`.
  The ML training code is tested only on a synthetic fixture, so **no accuracy figure exists; do not quote one.**
  Run the collector on your own VM and report what you measure.
* The privileged helper is effectively "run project code as root" for anyone who can edit the project files.
* Packet capture was only exercised on `r1-a`; TShark decode depends on `tshark` being installed.
* NS2 results exist only after NS2 has executed a scenario on your machine.
* Namespaces vanish on reboot — re-run `setup_network.sh`. (If `ip netns` shows *"Peer netns reference is invalid"*, run
  `cleanup_network.sh` then `setup_network.sh`.)

## 10. Troubleshooting
| Symptom | Fix |
|---|---|
| Badge says SIMULATED | not root-capable: install the sudoers snippet and `export AEGISNET_PRIV_PYTHON`; or run `setup_network.sh` first |
| `Network is unreachable` on a link | expected while a failure is injected; use Rollback |
| Capture shows 0 packets | wrong interface for that node (use the interface list); check `tcpdump` installed |
| HTTP/TLS traffic fails | start the service (TCP/UDP page) and confirm it listens in the right node |
| NS2 buttons disabled | `sudo apt install ns2` |
| ML page asks for libraries | `pip install -r requirements-ml.txt` |

## 11. Viva questions (with short answers)
* **Why namespaces and not VMs?** Each has its own interfaces/routes/ARP table at near-zero cost, so a failure is a real kernel event.
* **Dijkstra vs Distance Vector?** Global topology knowledge vs neighbour tables; DV can count to infinity without split horizon (shown on the Routing page).
* **How does recovery avoid breaking the host?** Only `ip route replace` of lab subnets inside `aegis_*` namespaces, validated by `ns_exec.py`; host default route never touched.
* **Why is a failed link `down` rather than `unknown`?** The kernel replied "unreachable" — a measured failure; "unknown" is reserved for probes that could not run.

## 12. Presentation outline (10 slides)
Problem → Architecture & test network → Monitoring → Sockets → Packet analysis → Routing & NS2 →
Fault detection → Self-healing live demo → Safety design → Results, limitations, future work.

## 13. Screenshots to capture
Dashboard (LIVE badge) · topology with a red link · TCP handshake timeline ·
packet table with TLS handshake · Wireshark with the PCAP · Routing before/after failure · NS2 comparison · Recovery page
(alerts + recovery history with the verified ping) · traceroute on the backup path.

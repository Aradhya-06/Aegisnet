"""Decode a PCAP file into packet METADATA rows (Scapy; no Django needed).

What is stored per packet: timestamp, MACs, IPs, ports, protocol, length, TCP
flags, TTL and a one-line summary. Application payloads are NOT stored. For TLS
only handshake metadata (type, version, SNI, chosen cipher) is read; the
encrypted application data is reported only as "N bytes of encrypted data".
"""
from __future__ import annotations

import logging
from collections import Counter

logging.getLogger("scapy.runtime").setLevel(logging.ERROR)

DNS_PORTS = (53, 5353)
TLS_VERSIONS = {0x0300: "SSL 3.0", 0x0301: "TLS 1.0", 0x0302: "TLS 1.1", 0x0303: "TLS 1.2", 0x0304: "TLS 1.3"}
TLS_RECORDS = {20: "ChangeCipherSpec", 21: "Alert", 22: "Handshake", 23: "ApplicationData"}
TLS_HANDSHAKES = {1: "ClientHello", 2: "ServerHello", 4: "NewSessionTicket", 8: "EncryptedExtensions",
                  11: "Certificate", 12: "ServerKeyExchange", 13: "CertificateRequest", 14: "ServerHelloDone",
                  15: "CertificateVerify", 16: "ClientKeyExchange", 20: "Finished"}
ICMP_TYPES = {0: "echo reply", 3: "destination unreachable", 8: "echo request", 11: "time exceeded"}

PROTOCOL_FILTERS = ["all", "tcp", "udp", "icmp", "dns", "http", "tls", "arp", "other"]


def parse_tls(payload: bytes):
    """Read TLS record/handshake metadata from the first bytes of a TCP payload."""
    if len(payload) < 5 or payload[0] not in TLS_RECORDS or payload[1] != 3 or payload[2] > 4:
        return None
    out = {"record": TLS_RECORDS[payload[0]], "record_version": TLS_VERSIONS.get((payload[1] << 8) | payload[2], "?")}
    if payload[0] != 22:
        out["encrypted_bytes"] = int.from_bytes(payload[3:5], "big")
        return out
    if len(payload) < 6:
        return out
    hs = payload[5]
    out["handshake"] = TLS_HANDSHAKES.get(hs, f"type {hs}")
    try:
        if hs in (1, 2):
            pos = 9                                   # skip record(5) + handshake header(4)
            out["hello_version"] = TLS_VERSIONS.get(int.from_bytes(payload[pos:pos + 2], "big"), "?")
            pos += 2 + 32                             # version + random
            sid = payload[pos]
            pos += 1 + sid
            if hs == 1:
                cs_len = int.from_bytes(payload[pos:pos + 2], "big")
                out["cipher_suites_offered"] = cs_len // 2
                pos += 2 + cs_len
                pos += 1 + payload[pos]               # compression methods
            else:
                out["cipher_suite"] = "0x%04x" % int.from_bytes(payload[pos:pos + 2], "big")
                pos += 2 + 1                          # suite + compression method
            ext_total = int.from_bytes(payload[pos:pos + 2], "big")
            pos += 2
            end = min(pos + ext_total, len(payload))
            while pos + 4 <= end:
                etype = int.from_bytes(payload[pos:pos + 2], "big")
                elen = int.from_bytes(payload[pos + 2:pos + 4], "big")
                data = payload[pos + 4:pos + 4 + elen]
                if etype == 0 and hs == 1 and len(data) >= 5:         # server_name
                    nlen = int.from_bytes(data[3:5], "big")
                    out["sni"] = data[5:5 + nlen].decode("ascii", "replace")
                elif etype == 43:                                       # supported_versions
                    if hs == 2 and len(data) >= 2:
                        out["negotiated"] = TLS_VERSIONS.get(int.from_bytes(data[:2], "big"), "?")
                    elif hs == 1 and data:
                        out["versions_offered"] = [TLS_VERSIONS.get(int.from_bytes(data[i:i + 2], "big"), "?")
                                                    for i in range(1, min(len(data), 1 + data[0]), 2)]
                pos += 4 + elen
    except (IndexError, ValueError):
        out["truncated"] = True       # snaplen cut the handshake short - metadata partial
    return out


def _tls_info(meta: dict) -> str:
    if meta.get("handshake"):
        bits = [f"TLS {meta['handshake']}"]
        if meta.get("sni"):
            bits.append(f"SNI={meta['sni']}")
        if meta.get("negotiated"):
            bits.append(f"version {meta['negotiated']}")
        elif meta.get("versions_offered"):
            bits.append("offers " + "/".join(meta["versions_offered"]))
        if meta.get("truncated"):
            bits.append("(truncated by snaplen)")
        return " ".join(bits)
    if meta["record"] == "ApplicationData":
        return f"TLS encrypted application data ({meta.get('encrypted_bytes', '?')} bytes - content not readable)"
    return f"TLS {meta['record']}"


def _dns_info(payload: bytes):
    from scapy.layers.dns import DNS
    d = DNS(payload)
    try:
        name = d.qd.qname.decode().rstrip(".") if d.qd else "?"
        qtype = {1: "A", 28: "AAAA", 5: "CNAME", 15: "MX", 2: "NS", 16: "TXT"}.get(d.qd.qtype, str(d.qd.qtype)) if d.qd else "?"
    except Exception:
        return None
    if d.qr == 0:
        return f"DNS query {qtype} {name} (id {d.id:#06x})"
    answers = []
    try:
        if d.ancount and d.an:
            answers.append(str(d.an.rdata))
    except Exception:
        pass
    return f"DNS response {qtype} {name} -> {', '.join(answers) if answers else 'no answer'} (id {d.id:#06x})"


def parse_packet(index: int, pkt, dns_ports=DNS_PORTS) -> dict:
    from scapy.layers.inet import ICMP, IP, TCP, UDP
    from scapy.layers.l2 import ARP, Ether
    row = {"index": index, "ts": float(pkt.time), "src_mac": "", "dst_mac": "", "src_ip": "", "dst_ip": "",
           "proto": "OTHER", "app": "", "sport": None, "dport": None, "length": len(pkt), "tcp_flags": "",
           "ttl": None, "info": ""}
    if Ether in pkt:
        row["src_mac"], row["dst_mac"] = pkt[Ether].src, pkt[Ether].dst
    if ARP in pkt:
        a = pkt[ARP]
        row.update(proto="ARP", src_ip=a.psrc, dst_ip=a.pdst)
        row["info"] = (f"ARP who-has {a.pdst} tell {a.psrc}" if a.op == 1 else f"ARP {a.psrc} is-at {a.hwsrc}")
        return row
    if IP not in pkt:
        row["info"] = pkt.summary()[:120]
        return row
    ip = pkt[IP]
    row.update(src_ip=ip.src, dst_ip=ip.dst, ttl=ip.ttl)
    if TCP in pkt:
        t = pkt[TCP]
        payload = bytes(t.payload)
        row.update(proto="TCP", sport=t.sport, dport=t.dport, tcp_flags=str(t.flags))
        row["info"] = f"{t.sport} -> {t.dport} [{t.flags}] seq={t.seq} ack={t.ack} len={len(payload)}"
        if payload:
            first = payload.split(b"\r\n", 1)[0][:110]
            if payload[:4] in (b"GET ", b"POST", b"HEAD", b"PUT ") or payload[:5] == b"HTTP/":
                row.update(app="http", info="HTTP " + first.decode("ascii", "replace"))
            else:
                meta = parse_tls(payload)
                if meta:
                    row.update(app="tls", info=_tls_info(meta))
    elif UDP in pkt:
        u = pkt[UDP]
        payload = bytes(u.payload)
        row.update(proto="UDP", sport=u.sport, dport=u.dport)
        row["info"] = f"{u.sport} -> {u.dport} len={len(payload)}"
        if payload and (u.sport in dns_ports or u.dport in dns_ports):
            try:
                text = _dns_info(payload)
            except Exception:
                text = None
            if text:
                row.update(app="dns", info=text)
    elif ICMP in pkt:
        ic = pkt[ICMP]
        row.update(proto="ICMP")
        row["info"] = f"ICMP {ICMP_TYPES.get(ic.type, 'type %d' % ic.type)} id={getattr(ic, 'id', '')} seq={getattr(ic, 'seq', '')}"
    else:
        row["info"] = f"IP protocol {ip.proto}"
    return row


def parse_pcap(path, limit=2000, dns_ports=DNS_PORTS) -> list[dict]:
    from scapy.utils import PcapReader
    rows = []
    with PcapReader(str(path)) as reader:
        for i, pkt in enumerate(reader, 1):
            if i > limit:
                break
            try:
                rows.append(parse_packet(i, pkt, dns_ports))
            except Exception as exc:                      # a malformed packet must not abort the capture
                rows.append({"index": i, "ts": float(pkt.time), "src_mac": "", "dst_mac": "", "src_ip": "", "dst_ip": "",
                             "proto": "OTHER", "app": "", "sport": None, "dport": None, "length": len(pkt),
                             "tcp_flags": "", "ttl": None, "info": f"undecodable packet ({exc.__class__.__name__})"})
    return rows


def matches_filter(row: dict, proto: str) -> bool:
    proto = (proto or "all").lower()
    if proto == "all":
        return True
    if proto in ("dns", "http", "tls"):
        return row["app"] == proto
    if proto in ("tcp", "udp", "icmp", "arp"):
        return row["proto"].lower() == proto
    return row["proto"] not in ("TCP", "UDP", "ICMP", "ARP")


def summarize(rows: list[dict]) -> dict:
    c = Counter()
    for r in rows:
        c[r["proto"]] += 1
        if r["app"]:
            c[r["app"].upper()] += 1
    return dict(c)

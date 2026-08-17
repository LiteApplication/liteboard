"""Minimal stdlib netlink client (links, addresses, bridge FDB) + netns entry.

Why not shell out to ``ip``/``bridge``? The daemon image is deliberately
dependency-light (``psutil`` + ``cryptography``, no iproute2 package), and these
probes have to run *inside other network namespaces* anyway — which needs a
fork+setns regardless. Speaking netlink directly keeps the image unchanged and
avoids parsing human-readable command output.

Reads are ``RTM_GET*`` dumps. Two narrowly-scoped writes exist for the repair
actions (``fdb_replace``, ``link_delete``) — nothing else here mutates state, and
callers are responsible for validating their arguments first.
"""

from __future__ import annotations

import ctypes
import json
import os
import socket
import struct

# ---- netlink constants ---------------------------------------------------- #
NETLINK_ROUTE = 0
NLM_F_REQUEST = 0x01
NLM_F_DUMP = 0x300  # ROOT | MATCH
NLMSG_ERROR = 2
NLMSG_DONE = 3

NLM_F_ACK = 0x04
NLM_F_REPLACE = 0x100
NLM_F_CREATE = 0x400

RTM_DELLINK = 17
RTM_GETLINK = 18
RTM_GETADDR = 22
RTM_NEWNEIGH = 28
RTM_GETNEIGH = 30

NUD_PERMANENT = 0x80

IFLA_IFNAME = 3
IFLA_MTU = 4
IFLA_MASTER = 10
IFLA_OPERSTATE = 16
IFLA_LINKINFO = 18
IFLA_INFO_KIND = 1
IFLA_INFO_DATA = 2
IFLA_VXLAN_ID = 1

IFA_ADDRESS = 1
IFA_LOCAL = 2

NDA_DST = 1
NDA_LLADDR = 2

AF_BRIDGE = 7
IFF_UP = 0x1
NTF_SELF = 0x02
CLONE_NEWNET = 0x40000000

# operstate values we care about (linux/if.h IF_OPER_*)
_OPERSTATE = {0: "unknown", 2: "down", 5: "dormant", 6: "up"}


def _align(n: int) -> int:
    return (n + 3) & ~3


def _parse_attrs(buf: memoryview) -> dict[int, bytes]:
    """Parse a flat rtattr stream into ``{type: payload}``."""
    attrs: dict[int, bytes] = {}
    off = 0
    while off + 4 <= len(buf):
        (rta_len, rta_type) = struct.unpack_from("=HH", buf, off)
        if rta_len < 4 or off + rta_len > len(buf):
            break
        attrs[rta_type & 0x3FFF] = bytes(buf[off + 4 : off + rta_len])
        off += _align(rta_len)
    return attrs


def _dump(msg_type: int, payload: bytes, timeout: float = 3.0) -> list[tuple[int, bytes]]:
    """Send a netlink dump request and collect ``(msg_type, body)`` replies."""
    sock = socket.socket(socket.AF_NETLINK, socket.SOCK_RAW, NETLINK_ROUTE)
    try:
        sock.settimeout(timeout)
        sock.bind((0, 0))
        header = struct.pack(
            "=IHHII", 16 + len(payload), msg_type, NLM_F_REQUEST | NLM_F_DUMP, 1, 0
        )
        sock.send(header + payload)

        out: list[tuple[int, bytes]] = []
        while True:
            data = sock.recv(65536)
            off = 0
            done = False
            while off + 16 <= len(data):
                nl_len, nl_type, _flags, _seq, _pid = struct.unpack_from("=IHHII", data, off)
                if nl_len < 16 or off + nl_len > len(data):
                    done = True
                    break
                if nl_type == NLMSG_DONE:
                    done = True
                    break
                if nl_type == NLMSG_ERROR:
                    (errno,) = struct.unpack_from("=i", data, off + 16)
                    if errno != 0:
                        raise OSError(-errno, f"netlink error {-errno}")
                    done = True
                    break
                out.append((nl_type, data[off + 16 : off + nl_len]))
                off += _align(nl_len)
            if done:
                return out
    finally:
        sock.close()


def _attr(attr_type: int, payload: bytes) -> bytes:
    """Serialise one rtattr, padded to the 4-byte alignment netlink expects."""
    header = struct.pack("=HH", 4 + len(payload), attr_type)
    blob = header + payload
    return blob + b"\x00" * (_align(len(blob)) - len(blob))


def _request_ack(msg_type: int, payload: bytes, timeout: float = 3.0) -> None:
    """Send a mutating netlink request and wait for the kernel's ACK.

    Raises ``OSError`` with the kernel's errno if the operation was rejected, so
    a failed repair surfaces as a real error instead of a silent no-op.
    """
    sock = socket.socket(socket.AF_NETLINK, socket.SOCK_RAW, NETLINK_ROUTE)
    try:
        sock.settimeout(timeout)
        sock.bind((0, 0))
        flags = NLM_F_REQUEST | NLM_F_ACK
        if msg_type == RTM_NEWNEIGH:
            flags |= NLM_F_CREATE | NLM_F_REPLACE
        sock.send(struct.pack("=IHHII", 16 + len(payload), msg_type, flags, 1, 0) + payload)

        data = sock.recv(65536)
        if len(data) < 20:
            raise OSError("short netlink ack")
        _len, nl_type, _flags, _seq, _pid = struct.unpack_from("=IHHII", data, 0)
        if nl_type != NLMSG_ERROR:
            raise OSError(f"unexpected netlink reply type {nl_type}")
        (errno,) = struct.unpack_from("=i", data, 16)
        if errno != 0:  # 0 is a plain ACK
            raise OSError(-errno, os.strerror(-errno))
    finally:
        sock.close()


# ---- typed dumps ---------------------------------------------------------- #
def list_links() -> list[dict]:
    """All links in the current netns: name, mtu, state, master, kind, vxlan id."""
    # ifinfomsg: family, pad, type, index, flags, change
    payload = struct.pack("=BBHiII", socket.AF_UNSPEC, 0, 0, 0, 0, 0)
    links = []
    for _t, body in _dump(RTM_GETLINK, payload):
        _fam, _pad, _typ, index, flags, _chg = struct.unpack_from("=BBHiII", body, 0)
        attrs = _parse_attrs(memoryview(body)[16:])

        kind = None
        vxlan_id = None
        if IFLA_LINKINFO in attrs:
            nested = _parse_attrs(memoryview(attrs[IFLA_LINKINFO]))
            if IFLA_INFO_KIND in nested:
                kind = nested[IFLA_INFO_KIND].rstrip(b"\x00").decode(errors="replace")
            if kind == "vxlan" and IFLA_INFO_DATA in nested:
                vx = _parse_attrs(memoryview(nested[IFLA_INFO_DATA]))
                if IFLA_VXLAN_ID in vx and len(vx[IFLA_VXLAN_ID]) >= 4:
                    vxlan_id = struct.unpack("=I", vx[IFLA_VXLAN_ID][:4])[0]

        oper = attrs.get(IFLA_OPERSTATE)
        links.append(
            {
                "index": index,
                "name": (attrs.get(IFLA_IFNAME, b"").rstrip(b"\x00").decode(errors="replace")),
                "mtu": struct.unpack("=I", attrs[IFLA_MTU])[0] if IFLA_MTU in attrs else None,
                "master": struct.unpack("=i", attrs[IFLA_MASTER])[0] if IFLA_MASTER in attrs else None,
                "up": bool(flags & IFF_UP),
                "operstate": _OPERSTATE.get(oper[0] if oper else 0, "unknown"),
                "kind": kind,
                "vxlan_id": vxlan_id,
            }
        )
    return links


def list_addrs() -> list[dict]:
    """IPv4 addresses in the current netns, as ``{index, addr}``."""
    # ifaddrmsg: family, prefixlen, flags, scope, index
    payload = struct.pack("=BBBBI", socket.AF_INET, 0, 0, 0, 0)
    out = []
    for _t, body in _dump(RTM_GETADDR, payload):
        _fam, _plen, _flags, _scope, index = struct.unpack_from("=BBBBI", body, 0)
        attrs = _parse_attrs(memoryview(body)[8:])
        raw = attrs.get(IFA_LOCAL) or attrs.get(IFA_ADDRESS)
        if raw and len(raw) == 4:
            out.append({"index": index, "addr": socket.inet_ntop(socket.AF_INET, raw)})
    return out


def list_fdb() -> list[dict]:
    """Bridge forwarding-database entries in the current netns.

    Each entry is ``{ifindex, mac, dst, self}``. The VXLAN driver keeps two
    entries per remote MAC: the bridge's learned one (``master br0``, no ``dst``)
    and the vxlan one (``self``) carrying the destination VTEP. A desynced
    endpoint is exactly the case where the ``self`` entry has no ``dst`` — or
    points at the wrong node.
    """
    # ndmsg: family, pad1, pad2, ifindex, state, flags, type
    payload = struct.pack("=BBHiHBB", AF_BRIDGE, 0, 0, 0, 0, 0, 0)
    out = []
    for _t, body in _dump(RTM_GETNEIGH, payload):
        _fam, _p1, _p2, ifindex, _state, flags, _typ = struct.unpack_from("=BBHiHBB", body, 0)
        attrs = _parse_attrs(memoryview(body)[12:])
        mac = attrs.get(NDA_LLADDR)
        if not mac or len(mac) != 6:
            continue
        dst = attrs.get(NDA_DST)
        out.append(
            {
                "ifindex": ifindex,
                "mac": ":".join(f"{b:02x}" for b in mac),
                "dst": socket.inet_ntop(socket.AF_INET, dst) if dst and len(dst) == 4 else None,
                "self": bool(flags & NTF_SELF),
            }
        )
    return out


# ---- writes (repair actions) ---------------------------------------------- #
def fdb_replace(ifindex: int, mac: str, dst: str) -> None:
    """Point a VXLAN FDB entry at the right destination VTEP.

    The netlink equivalent of ``bridge fdb replace <mac> dev vxlan0 dst <ip>``:
    it rewrites one forwarding entry and nothing else. No container restarts, no
    interface churn — traffic to that MAC starts flowing again immediately.
    """
    raw_mac = bytes(int(part, 16) for part in mac.split(":"))
    if len(raw_mac) != 6:
        raise ValueError(f"bad mac {mac!r}")
    payload = struct.pack(
        "=BBHiHBB", AF_BRIDGE, 0, 0, ifindex, NUD_PERMANENT, NTF_SELF, 0
    )
    payload += _attr(NDA_LLADDR, raw_mac)
    payload += _attr(NDA_DST, socket.inet_pton(socket.AF_INET, dst))
    _request_ack(RTM_NEWNEIGH, payload)


def link_delete(ifindex: int) -> None:
    """Remove an interface — the netlink form of ``ip link delete``.

    Used only to clear orphaned ``vx-*`` devices left behind by a torn-down
    sandbox, which block the node from recreating that network's interface.
    """
    _request_ack(RTM_DELLINK, struct.pack("=BBHiII", socket.AF_UNSPEC, 0, 0, ifindex, 0, 0))


# ---- namespace entry ------------------------------------------------------ #
def _setns(fd: int) -> None:
    setns = getattr(os, "setns", None)
    if setns is not None:  # Python >= 3.12
        setns(fd, CLONE_NEWNET)
        return
    libc = ctypes.CDLL("libc.so.6", use_errno=True)
    if libc.setns(fd, CLONE_NEWNET) != 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err))


def in_netns(ns_path: str, probe, timeout: int = 5) -> dict:
    """Run ``probe()`` inside the network namespace at ``ns_path``.

    Always forks: ``setns`` is per-thread and irreversible for our purposes, so
    entering a namespace in the daemon's own process would silently move the
    HTTP server off the network it is serving on. The child returns its result
    as JSON over a pipe and never touches anything else.

    Returns ``probe()``'s value, or ``{"error": ...}`` — never raises, because a
    missing namespace or a dropped capability is a normal, reportable condition.
    """
    try:
        read_fd, write_fd = os.pipe()
    except OSError as exc:
        return {"error": f"pipe: {exc}"}

    try:
        pid = os.fork()
    except OSError as exc:
        os.close(read_fd)
        os.close(write_fd)
        return {"error": f"fork: {exc}"}

    if pid == 0:  # --- child ---
        os.close(read_fd)
        code = 0
        try:
            import signal

            signal.alarm(timeout)  # hard bound: never wedge a forked prober
            fd = os.open(ns_path, os.O_RDONLY)
            try:
                _setns(fd)
            finally:
                os.close(fd)
            payload = json.dumps({"ok": probe()}).encode()
        except BaseException as exc:  # noqa: BLE001 - report to the parent
            payload = json.dumps({"error": f"{type(exc).__name__}: {exc}"}).encode()
            code = 1
        try:
            os.write(write_fd, payload)
        except OSError:
            code = 1
        os._exit(code)

    # --- parent ---
    os.close(write_fd)
    chunks = []
    try:
        while True:
            chunk = os.read(read_fd, 65536)
            if not chunk:
                break
            chunks.append(chunk)
    except OSError as exc:
        return {"error": f"read: {exc}"}
    finally:
        os.close(read_fd)
        try:
            os.waitpid(pid, 0)
        except OSError:
            pass

    if not chunks:
        return {"error": "prober produced no output"}
    try:
        result = json.loads(b"".join(chunks))
    except ValueError as exc:
        return {"error": f"malformed prober output: {exc}"}
    if "error" in result:
        return {"error": result["error"]}
    return result["ok"]

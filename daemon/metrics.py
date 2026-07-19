"""Live host metrics collection via psutil.

Rates (CPU %, disk I/O, network throughput) are computed from deltas between
successive samples. A background sampler keeps a warm previous sample so that
each request returns instantaneous rates without blocking.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field

import psutil

# When containerised, mount the host's /proc and point psutil at it so CPU,
# memory, load, network and disk counters reflect the host, not the container.
_PROCFS = os.environ.get("LITEBOARD_PROCFS")
if _PROCFS:
    psutil.PROCFS_PATH = _PROCFS


@dataclass
class _Sample:
    ts: float
    disk_read: int
    disk_write: int
    net_sent: int
    net_recv: int


@dataclass
class MetricsSnapshot:
    ts: float
    hostname: str
    uptime_s: float
    cpu_percent: float
    cpu_per_core: list[float]
    cpu_count: int
    load_avg: list[float]
    mem_total: int
    mem_used: int
    mem_percent: float
    swap_total: int
    swap_used: int
    disk_read_bps: float
    disk_write_bps: float
    net_sent_bps: float
    net_recv_bps: float
    disks: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return self.__dict__


class MetricsCollector:
    """Thread-safe collector holding the most recent I/O sample."""

    def __init__(self, sample_interval: float = 2.0) -> None:
        self._interval = sample_interval
        self._lock = threading.Lock()
        self._prev = self._raw_sample()
        # Prime psutil's per-cpu percent baseline.
        psutil.cpu_percent(percpu=True)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            sample = self._raw_sample()
            with self._lock:
                self._prev = sample

    @staticmethod
    def _raw_sample() -> _Sample:
        disk = psutil.disk_io_counters()
        net = psutil.net_io_counters()
        return _Sample(
            ts=time.time(),
            disk_read=disk.read_bytes if disk else 0,
            disk_write=disk.write_bytes if disk else 0,
            net_sent=net.bytes_sent if net else 0,
            net_recv=net.bytes_recv if net else 0,
        )

    def snapshot(self) -> MetricsSnapshot:
        now = self._raw_sample()
        with self._lock:
            prev = self._prev
        dt = max(now.ts - prev.ts, 1e-6)

        def rate(cur: int, old: int) -> float:
            return max(cur - old, 0) / dt

        vm = psutil.virtual_memory()
        sm = psutil.swap_memory()
        try:
            load = list(os.getloadavg())
        except (OSError, AttributeError):
            load = [0.0, 0.0, 0.0]

        disks = []
        for part in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(part.mountpoint)
            except (PermissionError, OSError):
                continue
            disks.append(
                {
                    "mount": part.mountpoint,
                    "total": usage.total,
                    "used": usage.used,
                    "percent": usage.percent,
                }
            )

        return MetricsSnapshot(
            ts=now.ts,
            hostname=os.environ.get("LITEBOARD_NODE_NAME", "") or _hostname(),
            uptime_s=time.time() - psutil.boot_time(),
            cpu_percent=psutil.cpu_percent(),
            cpu_per_core=psutil.cpu_percent(percpu=True),
            cpu_count=psutil.cpu_count() or 0,
            load_avg=load,
            mem_total=vm.total,
            mem_used=vm.total - vm.available,
            mem_percent=vm.percent,
            swap_total=sm.total,
            swap_used=sm.used,
            disk_read_bps=rate(now.disk_read, prev.disk_read),
            disk_write_bps=rate(now.disk_write, prev.disk_write),
            net_sent_bps=rate(now.net_sent, prev.net_sent),
            net_recv_bps=rate(now.net_recv, prev.net_recv),
            disks=disks,
        )


def _hostname() -> str:
    import socket

    return socket.gethostname()

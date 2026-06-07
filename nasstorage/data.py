import json
import re
import socket
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import psutil

WATCHED_FOLDERS_PATH = Path.home() / ".local" / "share" / "home_os" / "storage_folders.json"


@dataclass
class WatchedFolder:
    name: str
    path: str


def load_watched_folders() -> list[WatchedFolder]:
    try:
        raw = json.loads(WATCHED_FOLDERS_PATH.read_text())
        return [WatchedFolder(name=f['name'], path=f['path']) for f in raw]
    except Exception:
        return []


def save_watched_folders(folders: list[WatchedFolder]) -> None:
    WATCHED_FOLDERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    WATCHED_FOLDERS_PATH.write_text(json.dumps(
        [{'name': f.name, 'path': f.path} for f in folders],
        indent=2,
    ))


@dataclass
class MountInfo:
    name: str
    source: str
    path: str
    is_mounted: bool
    used: int      # bytes
    total: int     # bytes
    free: int      # bytes
    percent: float


@dataclass
class NetIO:
    rx_mbps: float
    tx_mbps: float


@dataclass
class NASData:
    fetched_at: str
    host: str
    host_online: bool
    mounts: list        # list[MountInfo]
    net_io: NetIO


# Tracks (bytes_recv, bytes_sent, timestamp) between refreshes
IOState = tuple[float, float, float]


def _parse_fstab_nas() -> list[tuple[str, str, str]]:
    """Returns (name, source, mountpoint) for network mounts in /etc/fstab."""
    results = []
    try:
        with open('/etc/fstab') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                parts = line.split()
                if len(parts) >= 3 and parts[2].lower() in ('cifs', 'nfs', 'nfs4', 'smbfs'):
                    mountpoint = parts[1]
                    results.append((Path(mountpoint).name, parts[0], mountpoint))
    except Exception:
        pass
    return results


def _mounted_paths() -> set[str]:
    return {p.mountpoint for p in psutil.disk_partitions(all=True)}


def _ping(host: str) -> bool:
    r = subprocess.run(
        ['ping', '-c', '1', '-W', '1', host],
        capture_output=True,
    )
    return r.returncode == 0


def _lan_interface(host: str) -> str | None:
    """Find the NIC on the same /24 subnet as the NAS host."""
    prefix = '.'.join(host.split('.')[:3])
    for nic, addrs in psutil.net_if_addrs().items():
        for addr in addrs:
            if addr.family == socket.AF_INET and addr.address.startswith(prefix + '.'):
                return nic
    return None


def fmt_size(n: int) -> str:
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def fetch(prev_io: IOState | None) -> tuple[NASData, IOState]:
    configured = _parse_fstab_nas()

    host = ''
    for _, source, _ in configured:
        m = re.match(r'//([^/]+)/', source)
        if m:
            host = m.group(1)
            break

    host_online = _ping(host) if host else False
    mounted = _mounted_paths()

    mounts: list[MountInfo] = []
    for name, source, path in configured:
        is_mounted = path in mounted
        if is_mounted:
            try:
                u = psutil.disk_usage(path)
                mounts.append(MountInfo(
                    name=name, source=source, path=path, is_mounted=True,
                    used=u.used, total=u.total, free=u.free, percent=u.percent,
                ))
            except Exception:
                mounts.append(MountInfo(name=name, source=source, path=path,
                                        is_mounted=True, used=0, total=0, free=0, percent=0))
        else:
            mounts.append(MountInfo(name=name, source=source, path=path,
                                    is_mounted=False, used=0, total=0, free=0, percent=0))

    # Network I/O delta on the LAN interface
    nic = _lan_interface(host) if host else None
    now = datetime.now().timestamp()

    if nic:
        counters = psutil.net_io_counters(pernic=True).get(nic)
    else:
        counters = psutil.net_io_counters()

    recv = counters.bytes_recv if counters else 0
    sent = counters.bytes_sent if counters else 0

    if prev_io and (now - prev_io[2]) > 0.5:
        dt = now - prev_io[2]
        rx = max(0.0, (recv - prev_io[0]) / dt / 1_048_576)
        tx = max(0.0, (sent - prev_io[1]) / dt / 1_048_576)
    else:
        rx = tx = 0.0

    return (
        NASData(
            fetched_at=datetime.now().isoformat(),
            host=host,
            host_online=host_online,
            mounts=mounts,
            net_io=NetIO(rx_mbps=rx, tx_mbps=tx),
        ),
        (recv, sent, now),
    )


def mount_all(password: str) -> tuple[bool, str]:
    r = subprocess.run(
        ['sudo', '-S', 'mount', '-a'],
        input=password + '\n',
        capture_output=True, text=True, timeout=30,
    )
    return r.returncode == 0, (r.stdout + r.stderr).strip()


def mount_one(path: str, password: str) -> tuple[bool, str]:
    r = subprocess.run(
        ['sudo', '-S', 'mount', path],
        input=password + '\n',
        capture_output=True, text=True, timeout=15,
    )
    return r.returncode == 0, (r.stdout + r.stderr).strip()

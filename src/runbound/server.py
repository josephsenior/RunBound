"""Development-server discovery and health checks."""

from __future__ import annotations

import contextlib
import re
import socket
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass

from .background import BackgroundProcess
from .deadline import SuspendAwareDeadline

_URL = re.compile(
    r"https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[::\])"
    r"(?::(\d{2,5}))?(?:/\S*)?",
    re.I,
)
_PORT_PATTERNS = (
    re.compile(
        r"(?:listening|running|started|available|server).*?"
        r"(?:port|on)\s*[:=]?\s*(\d{2,5})",
        re.I,
    ),
    re.compile(r"(?:localhost|127\.0\.0\.1|0\.0\.0\.0):\s*(\d{2,5})", re.I),
    re.compile(r"\bport\s*[:=]\s*(\d{2,5})\b", re.I),
)


@dataclass(frozen=True, slots=True)
class ServerReady:
    pid: int
    host: str
    port: int
    url: str
    protocol: str
    source: str
    startup_seconds: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class ServerStartupError(RuntimeError):
    pass


def detect_server(
    output: str, *, default_host: str = "127.0.0.1"
) -> tuple[str, int, str, str] | None:
    """Detect ``(host, port, protocol, source)`` from development-server output."""

    for line in reversed((output or "").splitlines()):
        url_match = _URL.search(line)
        if url_match:
            raw_url = url_match.group(0).rstrip(".,;)")
            protocol = raw_url.split(":", 1)[0].lower()
            port = int(url_match.group(1) or (443 if protocol == "https" else 80))
            if 0 < port < 65536:
                return default_host, port, protocol, line.strip()
        for pattern in _PORT_PATTERNS:
            match = pattern.search(line)
            if match:
                port = int(match.group(1))
                if 0 < port < 65536:
                    return default_host, port, "http", line.strip()
    return None


def _healthy(host: str, port: int, protocol: str, timeout: float) -> bool:
    if protocol == "tcp":
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            return False
    request = urllib.request.Request(
        f"{protocol}://{host}:{port}/",
        headers={"User-Agent": "RunBound-health-check"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout):
            return True
    except urllib.error.HTTPError:
        # Any HTTP response proves that the server is accepting requests.
        return True
    except (OSError, urllib.error.URLError, ValueError):
        return False


def wait_until_healthy(
    process: BackgroundProcess,
    *,
    timeout: float = 60.0,
    host: str = "127.0.0.1",
    port: int | None = None,
    protocol: str = "http",
    poll_interval: float = 0.1,
    request_timeout: float = 0.5,
) -> ServerReady:
    """Wait for a managed server to advertise and accept connections."""

    if timeout <= 0:
        raise ValueError("timeout must be greater than zero")
    if port is not None and not 0 < port < 65536:
        raise ValueError("port must be between 1 and 65535")
    started = time.monotonic()
    candidate = (host, port, protocol, "explicit port") if port is not None else None
    with SuspendAwareDeadline(timeout, poll_interval=poll_interval) as deadline:
        while not deadline.expired():
            snapshot = process.read()
            if candidate is None:
                candidate = detect_server(
                    snapshot.stdout + "\n" + snapshot.stderr,
                    default_host=host,
                )
            if candidate is not None:
                ready_host, ready_port, ready_protocol, source = candidate
                if _healthy(
                    ready_host,
                    int(ready_port),
                    ready_protocol,
                    request_timeout,
                ):
                    return ServerReady(
                        process.pid,
                        ready_host,
                        int(ready_port),
                        f"{ready_protocol}://{ready_host}:{ready_port}/",
                        ready_protocol,
                        source,
                        time.monotonic() - started,
                    )
            if not process.running:
                details = (snapshot.stderr or snapshot.stdout).strip()
                suffix = f": {details[-500:]}" if details else ""
                raise ServerStartupError(
                    f"server exited with code {process.returncode} "
                    f"before becoming healthy{suffix}"
                )
            before = time.monotonic()
            time.sleep(poll_interval)
            deadline.credit_poll_sleep(time.monotonic() - before)
    with contextlib.suppress(Exception):
        process.terminate()
    raise ServerStartupError(f"server did not become healthy within {timeout:g}s")

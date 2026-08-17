from __future__ import annotations

import socket
import sys

from runbound import detect_server, start_background, wait_until_healthy
from runbound.cli import main


def python_command(source: str) -> list[str]:
    return [sys.executable, "-u", "-c", source]


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def server_source(port: int) -> str:
    return (
        "from http.server import HTTPServer, BaseHTTPRequestHandler; "
        "H=type('H',(BaseHTTPRequestHandler,),"
        "{'do_GET':lambda s:(s.send_response(204),s.end_headers()),"
        "'log_message':lambda *a:None}); "
        f"print('Local: http://localhost:{port}', flush=True); "
        f"HTTPServer(('127.0.0.1',{port}),H).serve_forever()"
    )


def test_detect_server_understands_common_output() -> None:
    assert detect_server("VITE ready\nLocal: http://localhost:5173/") == (
        "127.0.0.1",
        5173,
        "http",
        "Local: http://localhost:5173/",
    )
    detected = detect_server("Server listening on port 8080")
    assert detected is not None
    assert detected[1] == 8080


def test_wait_until_healthy_discovers_and_checks_server() -> None:
    port = free_port()
    process = start_background(python_command(server_source(port)))
    try:
        ready = wait_until_healthy(process, timeout=10)
        assert ready.port == port
        assert ready.protocol == "http"
        assert ready.pid == process.pid
    finally:
        process.close()


def test_server_cli_can_exit_after_readiness() -> None:
    port = free_port()
    exit_code = main(
        [
            "server",
            "--wait-healthy",
            "--exit-after-ready",
            "--json",
            "--startup-timeout",
            "10s",
            "--",
            *python_command(server_source(port)),
        ]
    )
    assert exit_code == 0

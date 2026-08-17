"""Command-line interface for RunBound."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections.abc import Sequence

from .background import start_background
from .result import RunResult, TerminationReason
from .runner import DEFAULT_OUTPUT_LIMIT, run
from .server import ServerStartupError, wait_until_healthy

_DURATION = re.compile(r"^(\d+(?:\.\d+)?)(ms|s|m|h)?$", re.I)
_SIZE = re.compile(r"^(\d+(?:\.\d+)?)(b|kib|mib|gib|kb|mb|gb)?$", re.I)


def parse_duration(value: str) -> float:
    match = _DURATION.fullmatch(value.strip())
    if not match:
        raise argparse.ArgumentTypeError(f"invalid duration: {value!r}")
    number = float(match.group(1))
    factor = {None: 1.0, "ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}
    return number * factor[match.group(2).lower() if match.group(2) else None]


def parse_size(value: str) -> int:
    match = _SIZE.fullmatch(value.strip())
    if not match:
        raise argparse.ArgumentTypeError(f"invalid size: {value!r}")
    number = float(match.group(1))
    suffix = match.group(2).lower() if match.group(2) else "b"
    factor = {
        "b": 1,
        "kb": 1000,
        "mb": 1000**2,
        "gb": 1000**3,
        "kib": 1024,
        "mib": 1024**2,
        "gib": 1024**3,
    }[suffix]
    size = int(number * factor)
    if size <= 0:
        raise argparse.ArgumentTypeError("size must be greater than zero")
    return size


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="runbound",
        description="Run a command with bounded output and execution time.",
    )
    parser.add_argument("--timeout", type=parse_duration)
    parser.add_argument(
        "--output-limit",
        type=parse_size,
        default=DEFAULT_OUTPUT_LIMIT,
        help="per-stream byte limit (default: 8MiB)",
    )
    parser.add_argument("--cwd")
    parser.add_argument("--stdin", dest="stdin_data")
    parser.add_argument("--encoding", default="utf-8")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser


def build_server_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="runbound server",
        description="Run a development server and wait until it is healthy.",
    )
    parser.add_argument("--wait-healthy", action="store_true")
    parser.add_argument("--startup-timeout", type=parse_duration, default=60.0)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int)
    parser.add_argument(
        "--protocol", choices=("http", "https", "tcp"), default="http"
    )
    parser.add_argument(
        "--output-limit",
        type=parse_size,
        default=DEFAULT_OUTPUT_LIMIT,
        help="rolling per-stream byte limit (default: 8MiB)",
    )
    parser.add_argument("--cwd")
    parser.add_argument("--encoding", default="utf-8")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument(
        "--exit-after-ready",
        action="store_true",
        help="terminate the server after the readiness check (useful in CI)",
    )
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser


def _exit_code(result: RunResult) -> int:
    special = {
        TerminationReason.TIMEOUT: 124,
        TerminationReason.OUTPUT_LIMIT: 125,
        TerminationReason.SPAWN_ERROR: 126,
        TerminationReason.CANCELLED: 130,
    }
    if result.termination_reason in special:
        return special[result.termination_reason]
    return int(result.returncode or 0)


def _command(
    namespace: argparse.Namespace, parser: argparse.ArgumentParser
) -> list[str]:
    command = list(namespace.command)
    if command and command[0] == "--":
        command.pop(0)
    if not command:
        parser.error("a command is required after --")
    return command


def _server_main(argv: Sequence[str]) -> int:
    parser = build_server_parser()
    namespace = parser.parse_args(argv)
    command = _command(namespace, parser)
    process = start_background(
        command,
        cwd=namespace.cwd,
        output_limit=namespace.output_limit,
        encoding=namespace.encoding,
    )
    stdout_offset = 0
    stderr_offset = 0
    try:
        ready = wait_until_healthy(
            process,
            timeout=namespace.startup_timeout,
            host=namespace.host,
            port=namespace.port,
            protocol=namespace.protocol,
        )
        if namespace.as_json:
            print(json.dumps({"status": "healthy", **ready.to_dict()}, indent=2))
        else:
            print(f"runbound: server healthy at {ready.url}", file=sys.stderr)
        if namespace.exit_after_ready:
            return 0
        while process.running:
            snapshot = process.read(stdout_offset, stderr_offset)
            stdout_offset = snapshot.stdout_offset
            stderr_offset = snapshot.stderr_offset
            sys.stdout.write(snapshot.stdout)
            sys.stderr.write(snapshot.stderr)
            sys.stdout.flush()
            sys.stderr.flush()
            time.sleep(0.1)
        snapshot = process.read(stdout_offset, stderr_offset)
        sys.stdout.write(snapshot.stdout)
        sys.stderr.write(snapshot.stderr)
        return int(process.returncode or 0)
    except ServerStartupError as error:
        if namespace.as_json:
            print(json.dumps({"status": "failed", "error": str(error)}, indent=2))
        else:
            print(f"runbound: {error}", file=sys.stderr)
        return 124
    except KeyboardInterrupt:
        return 130
    finally:
        process.close()


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "server":
        return _server_main(arguments[1:])
    parser = build_parser()
    namespace = parser.parse_args(arguments)
    command = _command(namespace, parser)

    result = run(
        command,
        cwd=namespace.cwd,
        timeout=namespace.timeout,
        output_limit=namespace.output_limit,
        stdin=namespace.stdin_data,
        encoding=namespace.encoding,
    )
    if namespace.as_json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
        if result.error:
            print(f"runbound: {result.error}", file=sys.stderr)
    return _exit_code(result)

from __future__ import annotations

import json
import sys

from runbound.cli import main, parse_duration, parse_size


def test_parse_duration_units() -> None:
    assert parse_duration("250ms") == 0.25
    assert parse_duration("2m") == 120
    assert parse_duration("1h") == 3600


def test_parse_size_units() -> None:
    assert parse_size("8MiB") == 8 * 1024 * 1024
    assert parse_size("2MB") == 2_000_000


def test_cli_json_result(capsys) -> None:
    exit_code = main(
        [
            "--json",
            "--timeout",
            "10s",
            "--",
            sys.executable,
            "-c",
            "print('hello')",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["stdout"].strip() == "hello"
    assert payload["termination_reason"] == "completed"


def test_cli_timeout_exit_code(capsys) -> None:
    exit_code = main(
        [
            "--json",
            "--timeout",
            "100ms",
            "--",
            sys.executable,
            "-c",
            "import time; time.sleep(30)",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 124
    assert payload["termination_reason"] == "timeout"


from __future__ import annotations

import sys
import time

from runbound import RollingBuffer, start_background


def python_command(source: str) -> list[str]:
    return [sys.executable, "-u", "-c", source]


def test_rolling_buffer_retains_newest_bytes_and_reports_gap() -> None:
    buffer = RollingBuffer(5)
    buffer.append(b"abc")
    buffer.append(b"defg")
    offset, content, skipped = buffer.snapshot(0)
    assert offset == 7
    assert content == b"cdefg"
    assert skipped == 2
    assert buffer.dropped_bytes == 2


def test_background_process_supports_incremental_output_and_stdin() -> None:
    process = start_background(
        python_command(
            "import sys; print('ready', flush=True); "
            "print(sys.stdin.readline().strip().upper(), flush=True)"
        ),
        output_limit=1024,
    )
    try:
        deadline = time.monotonic() + 5
        first = process.read()
        while "ready" not in first.stdout and time.monotonic() < deadline:
            time.sleep(0.02)
            first = process.read()
        assert "ready" in first.stdout
        process.write("hello\n")
        assert process.wait(timeout=5) == 0
        second = process.read(first.stdout_offset, first.stderr_offset)
        assert "HELLO" in second.stdout
        assert not process.running
    finally:
        process.close()


def test_background_output_is_bounded() -> None:
    process = start_background(
        python_command("print('x' * 10000, flush=True)"),
        output_limit=128,
    )
    try:
        assert process.wait(timeout=5) == 0
        process.close()
        snapshot = process.read()
        assert len(snapshot.stdout.encode()) <= 128
        assert process.stdout_dropped_bytes > 0
    finally:
        process.close()

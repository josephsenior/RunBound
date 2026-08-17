from __future__ import annotations

import asyncio
import json
import os
import sys
import time

import pytest

from runbound import TerminationReason, run, run_async


def python_command(source: str) -> list[str]:
    return [sys.executable, "-c", source]


def test_run_captures_stdout_stderr_and_exit_code() -> None:
    result = run(
        python_command(
            "import sys; print('out'); print('err', file=sys.stderr); sys.exit(7)"
        ),
        timeout=10,
    )

    assert result.stdout.strip() == "out"
    assert result.stderr.strip() == "err"
    assert result.returncode == 7
    assert result.termination_reason is TerminationReason.COMPLETED
    assert not result.succeeded


def test_run_forwards_stdin() -> None:
    result = run(
        python_command("import sys; print(sys.stdin.read().upper())"),
        stdin="hello",
        timeout=10,
    )
    assert result.stdout.strip() == "HELLO"
    assert result.succeeded


def test_run_stops_at_stdout_limit() -> None:
    result = run(
        python_command(
            "import sys, time; sys.stdout.write('x' * 100000); "
            "sys.stdout.flush(); time.sleep(30)"
        ),
        timeout=10,
        output_limit=1024,
    )

    assert result.termination_reason is TerminationReason.OUTPUT_LIMIT
    assert result.stdout_truncated
    assert not result.stderr_truncated
    assert len(result.stdout.encode()) < 1300
    assert "RUNBOUND" in result.stdout


def test_run_stops_at_stderr_limit() -> None:
    result = run(
        python_command(
            "import sys, time; sys.stderr.write('e' * 100000); "
            "sys.stderr.flush(); time.sleep(30)"
        ),
        timeout=10,
        output_limit=2048,
    )

    assert result.termination_reason is TerminationReason.OUTPUT_LIMIT
    assert result.stderr_truncated


def test_run_times_out_without_waiting_for_child() -> None:
    started = time.monotonic()
    result = run(python_command("import time; time.sleep(30)"), timeout=0.2)

    assert result.termination_reason is TerminationReason.TIMEOUT
    assert result.timed_out
    assert time.monotonic() - started < 8


def test_run_returns_structured_spawn_error() -> None:
    result = run(["runbound-program-that-does-not-exist-9e63"])
    assert result.termination_reason is TerminationReason.SPAWN_ERROR
    assert result.returncode is None
    assert result.error


def test_result_json_shape() -> None:
    result = run(python_command("print('ok')"), timeout=10)
    encoded = json.dumps(result.to_dict())
    decoded = json.loads(encoded)
    assert decoded["termination_reason"] == "completed"
    assert decoded["succeeded"] is True
    assert decoded["args"][0] == sys.executable


def test_result_reports_detected_prompt_and_stall_reason() -> None:
    result = run(python_command("print('Password:', flush=True)"), timeout=10)
    assert result.prompt is not None
    assert result.prompt["type"] == "password"
    assert result.prompt["safe_to_respond"] is False
    assert result.stall_reason == "the process is waiting for credentials"


@pytest.mark.asyncio
async def test_run_async_forwards_stdin() -> None:
    result = await run_async(
        python_command("import sys; print(sys.stdin.read()[::-1])"),
        stdin="abc",
        timeout=10,
    )
    assert result.stdout.strip() == "cba"
    assert result.succeeded


@pytest.mark.asyncio
async def test_run_async_enforces_output_limit() -> None:
    result = await run_async(
        python_command(
            "import sys, time; sys.stdout.write('x' * 100000); "
            "sys.stdout.flush(); time.sleep(30)"
        ),
        timeout=10,
        output_limit=1024,
    )
    assert result.termination_reason is TerminationReason.OUTPUT_LIMIT
    assert result.stdout_truncated


@pytest.mark.asyncio
async def test_run_async_cancellation_terminates_child() -> None:
    task = asyncio.create_task(
        run_async(python_command("import time; time.sleep(30)"), timeout=60)
    )
    await asyncio.sleep(0.2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.skipif(os.name == "nt", reason="POSIX signal escalation test")
@pytest.mark.asyncio
async def test_run_async_force_kills_sigterm_ignoring_child() -> None:
    started = time.monotonic()
    result = await run_async(
        python_command(
            "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
            "time.sleep(30)"
        ),
        timeout=0.2,
    )
    assert result.termination_reason is TerminationReason.TIMEOUT
    assert time.monotonic() - started < 5

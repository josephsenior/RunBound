"""Bounded synchronous and asynchronous subprocess execution."""

from __future__ import annotations

import asyncio
import contextlib
import os
import subprocess
import threading
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import IO

from .deadline import SuspendAwareDeadline
from .process import (
    kill_async_process_tree,
    popen_group_options,
    terminate_async_process_tree,
    terminate_process_tree,
)
from .prompts import detect_interactive_prompt, detect_shell_stall_reason
from .result import RunResult, TerminationReason

DEFAULT_OUTPUT_LIMIT = 8 * 1024 * 1024
_READ_CHUNK = 64 * 1024
_TRUNCATION_MARKER = "\n\n[RUNBOUND: {stream} exceeded {limit} bytes]\n"


def _validate(args: Sequence[str], output_limit: int) -> tuple[str, ...]:
    normalized = tuple(str(arg) for arg in args)
    if not normalized:
        raise ValueError("args must contain at least one program")
    if output_limit <= 0:
        raise ValueError("output_limit must be greater than zero")
    return normalized


def _read_stream(
    stream: IO[bytes] | None,
    buffer: bytearray,
    limit: int,
    overflow: threading.Event,
    stream_overflow: threading.Event,
) -> None:
    if stream is None:
        return
    try:
        while True:
            chunk = stream.read(_READ_CHUNK)
            if not chunk:
                return
            remaining = limit - len(buffer)
            if len(chunk) > remaining:
                if remaining > 0:
                    buffer.extend(chunk[:remaining])
                stream_overflow.set()
                overflow.set()
                return
            buffer.extend(chunk)
    except (OSError, ValueError):
        return
    finally:
        with contextlib.suppress(OSError, ValueError):
            stream.close()


def _write_stdin(
    stream: IO[bytes] | None,
    data: bytes | str | None,
    encoding: str,
) -> None:
    if stream is None:
        return
    try:
        if data is not None:
            payload = data.encode(encoding) if isinstance(data, str) else data
            stream.write(payload)
            stream.flush()
    except (BrokenPipeError, OSError, ValueError):
        pass
    finally:
        with contextlib.suppress(OSError, ValueError):
            stream.close()


def _decode(
    data: bytearray,
    *,
    encoding: str,
    truncated: bool,
    stream: str,
    limit: int,
) -> str:
    text = data.decode(encoding, errors="replace")
    if truncated:
        text += _TRUNCATION_MARKER.format(stream=stream, limit=limit)
    return text


def _classify_result(result: RunResult) -> RunResult:
    content = result.stdout + "\n" + result.stderr
    prompt = detect_interactive_prompt(content)
    if prompt is not None:
        result.prompt = {
            "type": prompt.prompt_type.value,
            "description": prompt.description,
            "confidence": prompt.confidence,
            "safe_to_respond": prompt.safe_to_respond,
        }
    result.stall_reason = detect_shell_stall_reason(content, " ".join(result.args))
    return result


def run(
    args: Sequence[str],
    *,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
    output_limit: int = DEFAULT_OUTPUT_LIMIT,
    stdin: bytes | str | None = None,
    encoding: str = "utf-8",
    poll_interval: float = 0.1,
    freeze_grace: float = 30.0,
) -> RunResult:
    """Run a child with bounded output and process-tree cleanup."""

    command = _validate(args, output_limit)
    started = time.monotonic()
    try:
        process = subprocess.Popen(
            command,
            cwd=os.fspath(cwd) if cwd is not None else None,
            env=dict(env) if env is not None else None,
            stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **popen_group_options(),
        )
    except OSError as error:
        result = RunResult.spawn_error(command, error)
        result.duration_seconds = time.monotonic() - started
        return result

    stdout_buffer = bytearray()
    stderr_buffer = bytearray()
    overflow = threading.Event()
    stdout_overflow = threading.Event()
    stderr_overflow = threading.Event()
    threads = [
        threading.Thread(
            target=_read_stream,
            args=(
                process.stdout,
                stdout_buffer,
                output_limit,
                overflow,
                stdout_overflow,
            ),
            name="runbound-stdout",
            daemon=True,
        ),
        threading.Thread(
            target=_read_stream,
            args=(
                process.stderr,
                stderr_buffer,
                output_limit,
                overflow,
                stderr_overflow,
            ),
            name="runbound-stderr",
            daemon=True,
        ),
    ]
    for thread in threads:
        thread.start()
    stdin_thread = threading.Thread(
        target=_write_stdin,
        args=(process.stdin, stdin, encoding),
        name="runbound-stdin",
        daemon=True,
    )
    stdin_thread.start()

    reason = TerminationReason.COMPLETED
    with SuspendAwareDeadline(
        timeout,
        poll_interval=poll_interval,
        freeze_grace_seconds=freeze_grace,
    ) as deadline:
        while process.poll() is None:
            if overflow.is_set():
                reason = TerminationReason.OUTPUT_LIMIT
                terminate_process_tree(process)
                break
            if deadline.expired():
                reason = TerminationReason.TIMEOUT
                terminate_process_tree(process)
                break
            before = time.monotonic()
            time.sleep(poll_interval)
            deadline.credit_poll_sleep(time.monotonic() - before)

    # A reader can detect overflow and the child can exit between two polling
    # iterations.  Overflow is authoritative even when `poll()` observed the
    # exit first.
    if reason is TerminationReason.COMPLETED and overflow.is_set():
        reason = TerminationReason.OUTPUT_LIMIT

    if process.poll() is None:
        terminate_process_tree(process)
    with contextlib.suppress(subprocess.TimeoutExpired):
        process.wait(timeout=5)
    for thread in threads:
        thread.join(timeout=2)
    stdin_thread.join(timeout=2)

    return _classify_result(RunResult(
        args=command,
        stdout=_decode(
            stdout_buffer,
            encoding=encoding,
            truncated=stdout_overflow.is_set(),
            stream="stdout",
            limit=output_limit,
        ),
        stderr=_decode(
            stderr_buffer,
            encoding=encoding,
            truncated=stderr_overflow.is_set(),
            stream="stderr",
            limit=output_limit,
        ),
        returncode=process.returncode,
        termination_reason=reason,
        duration_seconds=time.monotonic() - started,
        stdout_truncated=stdout_overflow.is_set(),
        stderr_truncated=stderr_overflow.is_set(),
        pid=process.pid,
    ))


async def _read_async_stream(
    stream: asyncio.StreamReader | None,
    limit: int,
    overflow: asyncio.Event,
) -> tuple[bytearray, bool]:
    buffer = bytearray()
    if stream is None:
        return buffer, False
    while True:
        chunk = await stream.read(_READ_CHUNK)
        if not chunk:
            return buffer, False
        remaining = limit - len(buffer)
        if len(chunk) > remaining:
            if remaining > 0:
                buffer.extend(chunk[:remaining])
            overflow.set()
            return buffer, True
        buffer.extend(chunk)


async def _write_async_stdin(
    process: asyncio.subprocess.Process,
    data: bytes | str | None,
    encoding: str,
) -> None:
    if process.stdin is None:
        return
    try:
        if data is not None:
            payload = data.encode(encoding) if isinstance(data, str) else data
            process.stdin.write(payload)
            await process.stdin.drain()
    except (BrokenPipeError, ConnectionResetError, OSError):
        pass
    finally:
        process.stdin.close()
        wait_closed = getattr(process.stdin, "wait_closed", None)
        if callable(wait_closed):
            with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                await wait_closed()


async def _stop_async_process(
    process: asyncio.subprocess.Process,
    grace: float = 1.0,
) -> None:
    """Terminate a process group, then force-kill it after *grace*."""

    await asyncio.to_thread(terminate_async_process_tree, process, grace)
    try:
        await asyncio.wait_for(process.wait(), timeout=grace)
    except TimeoutError:
        await asyncio.to_thread(kill_async_process_tree, process)
        await process.wait()


async def run_async(
    args: Sequence[str],
    *,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
    output_limit: int = DEFAULT_OUTPUT_LIMIT,
    stdin: bytes | str | None = None,
    encoding: str = "utf-8",
    poll_interval: float = 0.1,
    freeze_grace: float = 30.0,
) -> RunResult:
    """Async equivalent of :func:`run` with identical result semantics."""

    command = _validate(args, output_limit)
    started = time.monotonic()
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=os.fspath(cwd) if cwd is not None else None,
            env=dict(env) if env is not None else None,
            stdin=(
                asyncio.subprocess.PIPE
                if stdin is not None
                else asyncio.subprocess.DEVNULL
            ),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **popen_group_options(),
        )
    except OSError as error:
        result = RunResult.spawn_error(command, error)
        result.duration_seconds = time.monotonic() - started
        return result

    overflow = asyncio.Event()
    stdout_task = asyncio.create_task(
        _read_async_stream(process.stdout, output_limit, overflow)
    )
    stderr_task = asyncio.create_task(
        _read_async_stream(process.stderr, output_limit, overflow)
    )
    stdin_task = asyncio.create_task(_write_async_stdin(process, stdin, encoding))
    reason = TerminationReason.COMPLETED

    try:
        with SuspendAwareDeadline(
            timeout,
            poll_interval=poll_interval,
            freeze_grace_seconds=freeze_grace,
        ) as deadline:
            while process.returncode is None:
                if overflow.is_set():
                    reason = TerminationReason.OUTPUT_LIMIT
                    await _stop_async_process(process)
                    break
                if deadline.expired():
                    reason = TerminationReason.TIMEOUT
                    await _stop_async_process(process)
                    break
                before = time.monotonic()
                await asyncio.sleep(poll_interval)
                deadline.credit_poll_sleep(time.monotonic() - before)
        await process.wait()
    except asyncio.CancelledError:
        reason = TerminationReason.CANCELLED
        await _stop_async_process(process)
        raise
    finally:
        await stdin_task

    # As in the sync runner, a fast exit must not erase the reader's overflow
    # signal merely because process completion won the polling race.
    if reason is TerminationReason.COMPLETED and overflow.is_set():
        reason = TerminationReason.OUTPUT_LIMIT

    stdout_buffer, stdout_truncated = await stdout_task
    stderr_buffer, stderr_truncated = await stderr_task
    transport = getattr(process, "_transport", None)
    if transport is not None:
        transport.close()

    return _classify_result(RunResult(
        args=command,
        stdout=_decode(
            stdout_buffer,
            encoding=encoding,
            truncated=stdout_truncated,
            stream="stdout",
            limit=output_limit,
        ),
        stderr=_decode(
            stderr_buffer,
            encoding=encoding,
            truncated=stderr_truncated,
            stream="stderr",
            limit=output_limit,
        ),
        returncode=process.returncode,
        termination_reason=reason,
        duration_seconds=time.monotonic() - started,
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
        pid=process.pid,
    ))

"""Managed, bounded background subprocesses."""

from __future__ import annotations

import contextlib
import os
import subprocess
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import IO

from .process import popen_group_options, terminate_process_tree
from .prompts import PromptMatch, detect_interactive_prompt
from .runner import DEFAULT_OUTPUT_LIMIT, _validate

_READ_CHUNK = 64 * 1024


class RollingBuffer:
    """Thread-safe byte buffer that retains only its newest bytes."""

    def __init__(self, limit: int) -> None:
        if limit <= 0:
            raise ValueError("limit must be greater than zero")
        self.limit = limit
        self._data = bytearray()
        self._start = 0
        self._lock = threading.Lock()

    def append(self, chunk: bytes) -> None:
        if not chunk:
            return
        with self._lock:
            self._data.extend(chunk)
            excess = len(self._data) - self.limit
            if excess > 0:
                del self._data[:excess]
                self._start += excess

    def snapshot(self, offset: int | None = None) -> tuple[int, bytes, int]:
        """Return ``(next_offset, data, skipped_bytes)`` from an absolute offset."""

        with self._lock:
            end = self._start + len(self._data)
            requested = self._start if offset is None else max(0, offset)
            skipped = max(0, self._start - requested)
            index = max(0, requested - self._start)
            return end, bytes(self._data[index:]), skipped

    @property
    def dropped_bytes(self) -> int:
        with self._lock:
            return self._start


@dataclass(frozen=True, slots=True)
class OutputSnapshot:
    stdout: str
    stderr: str
    stdout_offset: int
    stderr_offset: int
    stdout_skipped: int = 0
    stderr_skipped: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "stdout": self.stdout,
            "stderr": self.stderr,
            "stdout_offset": self.stdout_offset,
            "stderr_offset": self.stderr_offset,
            "stdout_skipped": self.stdout_skipped,
            "stderr_skipped": self.stderr_skipped,
        }


def _pump(stream: IO[bytes] | None, buffer: RollingBuffer) -> None:
    if stream is None:
        return
    try:
        read = getattr(stream, "read1", stream.read)
        while chunk := read(_READ_CHUNK):
            buffer.append(chunk)
    except (OSError, ValueError):
        pass
    finally:
        with contextlib.suppress(OSError, ValueError):
            stream.close()


class BackgroundProcess:
    """A subprocess handle with bounded output and deterministic tree cleanup."""

    def __init__(
        self,
        process: subprocess.Popen[bytes],
        args: tuple[str, ...],
        *,
        output_limit: int,
        encoding: str,
    ) -> None:
        self._process = process
        self.args = args
        self.encoding = encoding
        self.started_at = time.monotonic()
        self._stdout = RollingBuffer(output_limit)
        self._stderr = RollingBuffer(output_limit)
        self._threads = (
            threading.Thread(
                target=_pump,
                args=(process.stdout, self._stdout),
                name="runbound-background-stdout",
                daemon=True,
            ),
            threading.Thread(
                target=_pump,
                args=(process.stderr, self._stderr),
                name="runbound-background-stderr",
                daemon=True,
            ),
        )
        for thread in self._threads:
            thread.start()

    @property
    def pid(self) -> int:
        return self._process.pid

    @property
    def returncode(self) -> int | None:
        return self._process.poll()

    @property
    def running(self) -> bool:
        return self.returncode is None

    @property
    def duration_seconds(self) -> float:
        return time.monotonic() - self.started_at

    @property
    def stdout_dropped_bytes(self) -> int:
        return self._stdout.dropped_bytes

    @property
    def stderr_dropped_bytes(self) -> int:
        return self._stderr.dropped_bytes

    def read(
        self,
        stdout_offset: int | None = None,
        stderr_offset: int | None = None,
    ) -> OutputSnapshot:
        stdout_next, stdout, stdout_skipped = self._stdout.snapshot(stdout_offset)
        stderr_next, stderr, stderr_skipped = self._stderr.snapshot(stderr_offset)
        return OutputSnapshot(
            stdout.decode(self.encoding, errors="replace"),
            stderr.decode(self.encoding, errors="replace"),
            stdout_next,
            stderr_next,
            stdout_skipped,
            stderr_skipped,
        )

    def detect_prompt(self) -> PromptMatch | None:
        output = self.read()
        return detect_interactive_prompt(output.stdout + "\n" + output.stderr)

    def respond_to_prompt(self, *, allow: bool = False) -> bool:
        """Respond only to a recognized safe prompt and only with opt-in."""

        prompt = self.detect_prompt()
        if not allow or prompt is None or not prompt.safe_to_respond:
            return False
        self.write(prompt.response or "")
        return True

    def write(self, data: bytes | str) -> None:
        if self._process.stdin is None or self.returncode is not None:
            raise RuntimeError("process stdin is not available")
        payload = data.encode(self.encoding) if isinstance(data, str) else data
        try:
            self._process.stdin.write(payload)
            self._process.stdin.flush()
        except (BrokenPipeError, OSError, ValueError) as error:
            raise RuntimeError("process stdin is closed") from error

    def wait(self, timeout: float | None = None) -> int:
        return self._process.wait(timeout=timeout)

    def terminate(self, grace: float = 1.0) -> int | None:
        terminate_process_tree(self._process, grace=grace)
        with contextlib.suppress(subprocess.TimeoutExpired):
            self._process.wait(timeout=max(1.0, grace + 1.0))
        return self._process.returncode

    def close(self) -> None:
        if self.running:
            self.terminate()
        if self._process.stdin is not None:
            with contextlib.suppress(OSError, ValueError):
                self._process.stdin.close()
        for thread in self._threads:
            thread.join(timeout=2)

    def __enter__(self) -> BackgroundProcess:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def start_background(
    args: Sequence[str],
    *,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    output_limit: int = DEFAULT_OUTPUT_LIMIT,
    encoding: str = "utf-8",
) -> BackgroundProcess:
    """Start a managed subprocess whose lifetime is owned by the returned handle."""

    command = _validate(args, output_limit)
    process = subprocess.Popen(
        command,
        cwd=os.fspath(cwd) if cwd is not None else None,
        env=dict(env) if env is not None else None,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **popen_group_options(),
    )
    return BackgroundProcess(
        process,
        command,
        output_limit=output_limit,
        encoding=encoding,
    )

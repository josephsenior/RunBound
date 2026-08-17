"""Structured RunBound execution results."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class TerminationReason(str, Enum):
    """Why a bounded run stopped."""

    COMPLETED = "completed"
    TIMEOUT = "timeout"
    OUTPUT_LIMIT = "output_limit"
    CANCELLED = "cancelled"
    SPAWN_ERROR = "spawn_error"


@dataclass(slots=True)
class RunResult:
    """Complete, serializable outcome of a bounded subprocess."""

    args: tuple[str, ...]
    stdout: str = ""
    stderr: str = ""
    returncode: int | None = None
    termination_reason: TerminationReason = TerminationReason.COMPLETED
    duration_seconds: float = 0.0
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    pid: int | None = None
    error: str | None = None
    prompt: dict[str, Any] | None = None
    stall_reason: str | None = None

    @classmethod
    def spawn_error(cls, args: Sequence[str], error: BaseException) -> RunResult:
        return cls(
            args=tuple(str(arg) for arg in args),
            termination_reason=TerminationReason.SPAWN_ERROR,
            error=f"{type(error).__name__}: {error}",
        )

    @property
    def truncated(self) -> bool:
        return self.stdout_truncated or self.stderr_truncated

    @property
    def timed_out(self) -> bool:
        return self.termination_reason is TerminationReason.TIMEOUT

    @property
    def succeeded(self) -> bool:
        return (
            self.termination_reason is TerminationReason.COMPLETED
            and self.returncode == 0
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["termination_reason"] = self.termination_reason.value
        data["truncated"] = self.truncated
        data["timed_out"] = self.timed_out
        data["succeeded"] = self.succeeded
        return data

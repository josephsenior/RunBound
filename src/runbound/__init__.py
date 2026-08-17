"""Public API for RunBound."""

from .background import (
    BackgroundProcess,
    OutputSnapshot,
    RollingBuffer,
    start_background,
)
from .deadline import (
    SuspendAwareDeadline,
    credit_active_deadlines_process_suspend,
)
from .prompts import (
    InteractivePromptDetector,
    PromptMatch,
    PromptType,
    detect_interactive_prompt,
    detect_shell_stall_reason,
    suggest_noninteractive_command,
)
from .result import RunResult, TerminationReason
from .runner import DEFAULT_OUTPUT_LIMIT, run, run_async
from .server import ServerReady, ServerStartupError, detect_server, wait_until_healthy

__all__ = [
    "DEFAULT_OUTPUT_LIMIT",
    "BackgroundProcess",
    "InteractivePromptDetector",
    "OutputSnapshot",
    "PromptMatch",
    "PromptType",
    "RunResult",
    "RollingBuffer",
    "ServerReady",
    "ServerStartupError",
    "SuspendAwareDeadline",
    "TerminationReason",
    "credit_active_deadlines_process_suspend",
    "detect_interactive_prompt",
    "detect_server",
    "detect_shell_stall_reason",
    "run",
    "run_async",
    "start_background",
    "suggest_noninteractive_command",
    "wait_until_healthy",
]

__version__ = "0.1.0"

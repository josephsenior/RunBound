"""Cross-platform process creation and process-tree termination."""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
from typing import Any


def popen_group_options() -> dict[str, Any]:
    """Return `Popen` options that isolate the child into a terminable group."""

    if os.name == "nt":
        flag = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        return {"creationflags": flag}
    return {"start_new_session": True}


def terminate_process_tree(process: subprocess.Popen[Any], grace: float = 1.0) -> None:
    """Best-effort graceful termination followed by forceful tree cleanup."""

    pid = getattr(process, "pid", None)
    if not pid or process.poll() is not None:
        return

    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=max(1.0, grace + 1.0),
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            with contextlib.suppress(OSError):
                process.kill()
        return

    try:
        os.killpg(pid, signal.SIGTERM)
    except (AttributeError, OSError):
        with contextlib.suppress(OSError):
            process.terminate()
    try:
        process.wait(timeout=grace)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(pid, signal.SIGKILL)
    except (AttributeError, OSError):
        with contextlib.suppress(OSError):
            process.kill()


def terminate_async_process_tree(process: Any, grace: float = 1.0) -> None:
    """Terminate an asyncio subprocess using its group-owning PID."""

    pid = getattr(process, "pid", None)
    if not pid:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=max(1.0, grace + 1.0),
                check=False,
            )
            return
        except (OSError, subprocess.SubprocessError):
            pass
    else:
        with contextlib.suppress(AttributeError, OSError):
            os.killpg(pid, signal.SIGTERM)
            return
    with contextlib.suppress(ProcessLookupError):
        process.kill()


def kill_async_process_tree(process: Any) -> None:
    """Force-kill an asyncio subprocess tree after its grace period."""

    pid = getattr(process, "pid", None)
    if not pid:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
            )
            return
        except (OSError, subprocess.SubprocessError):
            pass
    else:
        with contextlib.suppress(AttributeError, OSError):
            os.killpg(pid, signal.SIGKILL)
            return
    with contextlib.suppress(ProcessLookupError):
        process.kill()

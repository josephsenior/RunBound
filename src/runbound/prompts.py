"""Pure prompt, non-interactive-command, and stall classifiers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class PromptType(str, Enum):
    YES_NO = "yes_no"
    PROCEED = "proceed"
    PASSWORD = "password"
    PRESS_KEY = "press_key"
    OVERWRITE = "overwrite"
    LICENSE = "license"


@dataclass(frozen=True, slots=True)
class PromptMatch:
    prompt_type: PromptType
    response: str | None
    description: str
    confidence: float

    @property
    def safe_to_respond(self) -> bool:
        return self.response is not None and self.prompt_type is not PromptType.PASSWORD


_PATTERNS: tuple[tuple[re.Pattern[str], PromptMatch], ...] = (
    (
        re.compile(r"(?:password|passwd)\s*:\s*$", re.I | re.M),
        PromptMatch(PromptType.PASSWORD, None, "password prompt", 1.0),
    ),
    (
        re.compile(r"\[sudo\]\s*password\s+for\s+\S", re.I),
        PromptMatch(PromptType.PASSWORD, None, "sudo password prompt", 1.0),
    ),
    (
        re.compile(r"Ok to proceed\?\s*\(y\)", re.I),
        PromptMatch(PromptType.PROCEED, "y\n", "npm/npx confirmation", 1.0),
    ),
    (
        re.compile(r"Do you want to continue\?\s*\[Y/n\]", re.I),
        PromptMatch(PromptType.YES_NO, "Y\n", "package-manager confirmation", 1.0),
    ),
    (
        re.compile(r"(?:overwrite|replace)\s+.*\?\s*\(y/n\)", re.I),
        PromptMatch(PromptType.OVERWRITE, "y\n", "overwrite confirmation", 0.9),
    ),
    (
        re.compile(r"Press\s+(?:any\s+)?key\s+to\s+continue", re.I),
        PromptMatch(PromptType.PRESS_KEY, "\n", "press-key prompt", 1.0),
    ),
    (
        re.compile(r"Do you accept the license (?:terms|agreement)\?", re.I),
        PromptMatch(PromptType.LICENSE, "yes\n", "license agreement", 0.95),
    ),
    (
        re.compile(r"(?:\(y/n\)|\[y/N\]|\[Y/n\])\s*[?:]?\s*$", re.I | re.M),
        PromptMatch(PromptType.YES_NO, "y\n", "yes/no confirmation", 0.9),
    ),
)

_ANSI_ESCAPE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


class InteractivePromptDetector:
    def __init__(self, min_confidence: float = 0.8) -> None:
        self.min_confidence = min_confidence

    def detect(self, output: str, last_n_lines: int = 10) -> PromptMatch | None:
        clean = _ANSI_ESCAPE.sub("", output or "")
        recent = "\n".join(clean.splitlines()[-last_n_lines:])
        for pattern, match in _PATTERNS:
            if match.confidence >= self.min_confidence and pattern.search(recent):
                return match
        return None


def detect_interactive_prompt(output: str) -> PromptMatch | None:
    return InteractivePromptDetector().detect(output)


_TRANSFORMS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^npx\s+"), "npx --yes "),
    (re.compile(r"^npm\s+install"), "npm install --yes"),
    (re.compile(r"^apt\s+install"), "apt install -y"),
    (re.compile(r"^apt-get\s+install"), "apt-get install -y"),
    (re.compile(r"^apt\s+upgrade"), "apt upgrade -y"),
    (re.compile(r"^apt-get\s+upgrade"), "apt-get upgrade -y"),
)


def suggest_noninteractive_command(command: str) -> str | None:
    command = command.strip()
    if any(flag in command.split() for flag in ("--yes", "-y", "--force", "-f")):
        return None
    for pattern, replacement in _TRANSFORMS:
        modified = pattern.sub(replacement, command)
        if modified != command:
            return modified
    return None


def detect_shell_stall_reason(content: str, command: str = "") -> str | None:
    tail = "\n".join((content or "").strip().splitlines()[-8:])
    if re.search(r"\[sudo\]\s*password\s+for\s+\S", tail, re.I):
        return "sudo is waiting for a password; use a non-interactive alternative"
    if re.search(r"(?:password|passwd)\s*:\s*$", tail, re.I | re.M):
        return "the process is waiting for credentials"
    if re.search(
        r"Could not get lock|Unable to lock|dpkg was interrupted|"
        r"/var/lib/(?:dpkg|apt)/",
        content or "",
        re.I,
    ):
        return "a package-manager lock is blocking progress"
    if re.search(r"Do you want to continue\?\s*\[Y/n\]", tail, re.I):
        return "the package manager is waiting for confirmation; retry with -y"
    if command.strip().lower().startswith("sudo ") and not tail:
        return "sudo may be waiting for a password or policy prompt"
    return None

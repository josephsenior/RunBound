from __future__ import annotations

from runbound import (
    PromptType,
    detect_interactive_prompt,
    detect_shell_stall_reason,
    suggest_noninteractive_command,
)


def test_detects_safe_confirmation() -> None:
    match = detect_interactive_prompt("Package missing. Ok to proceed? (y)")
    assert match is not None
    assert match.prompt_type is PromptType.PROCEED
    assert match.safe_to_respond
    assert match.response == "y\n"


def test_password_prompt_is_never_safe_to_respond() -> None:
    match = detect_interactive_prompt("[sudo] password for alice:")
    assert match is not None
    assert match.prompt_type is PromptType.PASSWORD
    assert not match.safe_to_respond
    assert match.response is None


def test_ansi_does_not_hide_prompt() -> None:
    match = detect_interactive_prompt("\x1b[31mContinue? [y/N]\x1b[0m")
    assert match is not None


def test_suggests_noninteractive_npx() -> None:
    assert (
        suggest_noninteractive_command("npx create-react-app demo")
        == "npx --yes create-react-app demo"
    )


def test_does_not_duplicate_noninteractive_flag() -> None:
    assert suggest_noninteractive_command("apt install -y curl") is None


def test_detects_package_manager_lock() -> None:
    reason = detect_shell_stall_reason(
        "E: Could not get lock /var/lib/dpkg/lock-frontend", "apt install curl"
    )
    assert reason and "lock" in reason


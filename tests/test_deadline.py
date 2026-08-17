from __future__ import annotations

from runbound import (
    SuspendAwareDeadline,
    credit_active_deadlines_process_suspend,
)


def test_poll_overrun_is_credited() -> None:
    deadline = SuspendAwareDeadline(10, poll_interval=0.1, freeze_grace_seconds=1)
    started = deadline._started
    credited = deadline.credit_poll_sleep(5.1)
    assert credited == 5.0
    assert deadline._started == started + 5.0
    deadline.close()


def test_external_suspend_credits_active_deadlines() -> None:
    deadline = SuspendAwareDeadline(10, freeze_grace_seconds=1)
    started = deadline._started
    credit_active_deadlines_process_suspend(5)
    assert deadline._started == started + 4
    deadline.close()


def test_none_budget_never_expires() -> None:
    with SuspendAwareDeadline(None) as deadline:
        assert not deadline.expired()
        assert deadline.remaining() == float("inf")


def test_zero_budget_expires_immediately() -> None:
    with SuspendAwareDeadline(0) as deadline:
        assert deadline.expired()


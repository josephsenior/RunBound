# Changelog

## 0.1.0 - 2026-08-17

- Add sync and async bounded subprocess execution.
- Bound stdout and stderr independently by bytes.
- Terminate process trees on timeouts, output overflow, and cancellation.
- Add suspend-aware deadline accounting.
- Add stdin forwarding and structured JSON results.
- Add interactive-prompt, non-interactive-command, and stall classifiers.
- Add managed background processes with bounded rolling output and stdin control.
- Add development-server detection and HTTP/TCP readiness checks.
- Add the `runbound server --wait-healthy` workflow.
- Add the `runbound` CLI with duration and byte-size units.

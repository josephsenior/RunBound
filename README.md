# RunBound

[![CI](https://github.com/josephsenior/RunBound/actions/workflows/ci.yml/badge.svg)](https://github.com/josephsenior/RunBound/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)

Run subprocesses without allowing unlimited output, wall time, or abandoned
child processes.

RunBound is useful in coding agents, CI workers, graders, test runners, and any
automation service that executes commands it does not completely control. It
originated in and was battle-tested by Grinta.

Its dependency-free core supports Windows, Linux, and macOS.

## Why RunBound?

Unbounded subprocesses are a reliability problem for automation: a command can
hang, fill a pipe, leak descendants, or produce more output than the caller can
store. RunBound provides a small, dependency-free execution layer with explicit
limits and structured results.

Use it when you need to:

- run commands from an agent, worker, test runner, or CI service;
- enforce wall-time and independent stdout/stderr byte limits; or
- manage a long-lived development server and verify that it is healthy.

RunBound is a process-management library, not a security sandbox. See
[Security](#security) before running untrusted commands.

## Install

RunBound requires Python 3.10 or newer. Install the released package with:

```console
python -m pip install runbound
```

For a source checkout with development tools:

```console
python -m pip install -e ".[dev]"
```

## CLI

```console
runbound --timeout 30s --output-limit 8MiB --json -- pytest -q
runbound --stdin "yes\n" -- python script.py
runbound server --wait-healthy -- npm run dev
```

Exit codes normally mirror the child. RunBound uses 124 for a timeout, 125 for
an output-limit termination, 126 when the process could not be started, and
130 when execution is cancelled.

## Python API

```python
from runbound import run

result = run(
    ["pytest", "-q"],
    timeout=30,
    output_limit=8 * 1024 * 1024,
)

print(result.stdout)
print(result.termination_reason)
```

Async callers use `await run_async(...)` with the same options.

For long-lived processes, use a managed background handle. Its rolling buffers
retain the newest output without growing indefinitely, and leaving the context
terminates the whole child process tree.

```python
from runbound import start_background, wait_until_healthy

with start_background(["npm", "run", "dev"]) as server:
    ready = wait_until_healthy(server, timeout=60)
    print(ready.url)
```

`BackgroundProcess.read()` supports incremental offsets, `write()` forwards
stdin, and `detect_prompt()` recognizes common interactive prompts. Automatic
responses require an explicit `respond_to_prompt(allow=True)` call and are
never supplied for password prompts.

## Guarantees

- stdout and stderr are bounded independently in bytes;
- hitting either cap terminates the process tree;
- timeouts are suspend-aware when execution is polled by RunBound;
- stdin is forwarded without using unbounded `communicate()` buffers;
- results serialize to stable JSON;
- background output uses bounded rolling buffers and reports dropped bytes;
- development-server readiness is verified with a real HTTP or TCP probe;
- common interactive prompts and shell-stall causes are reported structurally;
- decoding errors are replaced instead of crashing result collection.

RunBound does not impose CPU, address-space, filesystem, or network isolation.
Those require an OS sandbox or container appropriate to the host application.

## Security

RunBound executes commands with the permissions of its caller and does not
provide isolation. Treat command strings, environment variables, working
directories, and inherited file descriptors as trusted inputs unless you add a
separate sandbox. See [SECURITY.md](SECURITY.md) for vulnerability reporting.

## Development

```console
python -m pip install -e ".[dev]"
python -m ruff check .
python -m pytest -q
python -m build
```

The test suite is intentionally cross-platform. Before opening a pull request,
run the same checks locally with pytest plugin autoloading disabled so unrelated
global plugins cannot affect the result:

```console
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"  # PowerShell
python -m pytest -q
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the pull request workflow.

RunBound originated in and was battle-tested by
[Grinta](https://github.com/josephsenior/Grinta-Coding-Agent).

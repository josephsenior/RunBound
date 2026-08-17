# Grinta integration

RunBound's core was extracted from these Grinta modules:

| Grinta implementation | RunBound destination |
| --- | --- |
| `backend/core/bounded_result.py` | `runbound.result` |
| `backend/execution/utils/files/bounded_io.py` | `runbound.runner`, `runbound.process` |
| `backend/core/timeouts/suspend_aware_deadline.py` | `runbound.deadline` |
| `backend/execution/utils/shell/prompt_detector.py` | `runbound.prompts` |
| `backend/execution/utils/shell/stall_hints.py` | `runbound.prompts` |

The Grinta copies remain active during the extraction phase. This avoids an
unpublished local-path dependency in Grinta's distributable metadata.

After RunBound is moved and tagged:

1. add a pinned RunBound dependency to Grinta;
2. turn Grinta's old modules into thin compatibility adapters;
3. migrate callers to the public RunBound API;
4. run the Grinta execution, shell, LSP, and async-helper suites;
5. remove duplicate implementations once no internal imports remain.

Grinta-specific observation mutation, session registration, logging, and agent
guidance stay in Grinta. RunBound returns neutral structured data and never
imports `backend.*`.


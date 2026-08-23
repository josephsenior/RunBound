# Contributing to RunBound

Thanks for helping improve RunBound. Small, focused pull requests are easiest
to review and safest to merge.

## Development setup

RunBound supports Python 3.10 and newer. From a checkout:

```console
python -m pip install -e ".[dev]"
python -m ruff check .
python -m pytest -q
python -m build
```

If your machine has globally installed pytest plugins, set
`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` before running the test suite.

## Pull requests

1. Explain the user-facing problem and what changed.
2. Add or update tests for behavior changes, including platform-specific cases
   where relevant.
3. Keep public API changes documented in the README and changelog.
4. Run the checks above and include important platform limitations in the
   pull request description.

Please avoid unrelated formatting or refactoring in feature and bug-fix
changes. Maintainers may ask for a focused follow-up if a change needs a larger
design discussion.

## Reporting bugs and requesting features

Use the GitHub issue templates and include the Python version, operating system,
RunBound version or commit, a minimal reproduction, and the observed result.
Do not include secrets or sensitive command output.

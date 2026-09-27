# T02 — Run the Python test suites in CI

Status: open

| | |
|---|---|
| Fixes | [DP15](../gym_data_path_review.md#dp15--ci-runs-no-tests) |
| Priority / size | P0 / S |
| Depends on | — |
| Area | CI |
| Needs a device | No |

## Why

`irobot_gym_ide/tests` (237 tests) and `typesafe_agent/tests` run only when someone remembers to run
them locally. Several later tasks (T11, T12, T14, T18, T21) change `irobot_gym_ide/connection.py`, which
every Python client depends on, so CI must run these suites before those changes land.

## Steps

1. In `.github/workflows/build-and-release.yml`, add a new job next to `build-ubuntu`:

   ```yaml
   python-tests:
     runs-on: ubuntu-latest
     steps:
     - uses: actions/checkout@v4
     - uses: actions/setup-python@v5
       with:
         python-version: "3.12"
     - name: Install dependencies
       run: pip install PyYAML numpy
     - name: irobot_gym_ide tests
       env:
         QT_QPA_PLATFORM: offscreen
       run: python -m unittest discover -s irobot_gym_ide/tests -t . -v
     - name: typesafe_agent tests
       run: python -m unittest discover -s typesafe_agent/tests -t . -v
   ```

2. Don't install PySide6 or `typesafe-sdk`. The suites are designed to run without them. Tests that
   need them skip themselves (17 of the IDE tests skip today). If a test *errors* rather than skips
   because a package is missing, that's a test bug; fix the test's import guard in this PR.

3. Run both commands locally in a fresh virtual environment with only PyYAML and numpy installed,
   to confirm the job will pass before you push.

4. List in the PR description which tests skip and why (the `-v` output shows the skip reason), so
   the team knows what CI isn't covering.

## Done when

- Both suites run in the new `python-tests` job on your PR, and the job is green.
- You've proven the job can fail: push a temporary commit that breaks one assertion, confirm the job
  goes red, then remove it before merging.
- The PR description lists the skipped tests and their reasons.

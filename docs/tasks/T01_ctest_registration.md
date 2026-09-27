# T01 — Register the C++ tests with CTest

Status: open

| | |
|---|---|
| Fixes | [DP15](../gym_data_path_review.md#dp15--ci-runs-no-tests) |
| Priority / size | P0 / S |
| Depends on | — |
| Area | CMake, CI |
| Needs a device | No |

## Why

CI's "Test" step runs `ctest`, but no CMake file calls `enable_testing()` or `add_test()`, so CTest
finds zero tests and reports success. The Catch2 suite in `tests/` (including the loopback agent
tests in `tests/test_agent_reconnect.cpp`) is built by CI but never run. Every other task in this
directory relies on CI catching regressions, so this comes first.

## Steps

1. Open the top-level `CMakeLists.txt`. Before `add_subdirectory(tests)` (around line 180), add:

   ```cmake
   enable_testing()
   ```

2. Open `tests/CMakeLists.txt`. After the `add_executable(${APP_TARGET} ...)` line, register the
   test cases:

   ```cmake
   include(Catch)
   catch_discover_tests(${APP_TARGET})
   ```

   `include(Catch)` works because `find_package(Catch2 CONFIG REQUIRED)` (already at the top of
   the file) makes Catch2's CMake helpers available. It lists every `TEST_CASE` as its own CTest
   test, so a failure report names the failing case.

   If `include(Catch)` fails with your Catch2 version, fall back to one test for the whole binary
   and note it in the PR:

   ```cmake
   add_test(NAME all_tests COMMAND ${APP_TARGET})
   ```

3. Open `.github/workflows/build-and-release.yml`. In the `build-ubuntu` job's "Test" step, change
   the command to:

   ```yaml
   run: ctest -C ${{env.BUILD_TYPE}} --output-on-failure --no-tests=error
   ```

   `--no-tests=error` makes CI fail if registration ever silently breaks again, which is exactly the
   bug this task fixes.

4. Build and run locally:

   ```bash
   cmake -B build -DCMAKE_BUILD_TYPE=Release
   cmake --build build
   ctest --test-dir build --output-on-failure
   ```

5. If any test fails on Linux, **don't disable it**. Record the failure in the PR description and
   ask whether to fix it in this PR or open a follow-up.

## Notes

- Don't run CTest in parallel (`-j`). `test_agent_reconnect.cpp` uses fixed loopback ports 39181
  and 39182, and two copies would collide.
- The Windows job only builds the `irobot` target, not the tests. Running tests on Windows is out of
  scope here; mention it as a follow-up in the PR.

## Done when

- `ctest --test-dir build` lists the individual Catch2 test cases (for example "agent controller
  survives repeated connect/disconnect") and they pass.
- The CI log for your PR shows those tests running in the `build-ubuntu` job.
- You've proven CI can fail: push a temporary commit adding `REQUIRE(false);` to one test, confirm
  the job goes red, then remove the commit before merging.

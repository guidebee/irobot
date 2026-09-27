# T03 — Run the server's Java unit tests in CI

Status: open

| | |
|---|---|
| Fixes | [DP15](../gym_data_path_review.md#dp15--ci-runs-no-tests) |
| Priority / size | P1 / S |
| Depends on | — |
| Area | CI, `irobot_server/` |
| Needs a device | No |

## Why

`irobot_server/app/src/test/` has JUnit tests (`ControlMessageReaderTest`,
`DeviceMessageWriterTest`, and others) that no workflow runs. T14, T16 and T17 change the server's
control and device-message code, so these tests need to run in CI first.

## Steps

1. Check what the server build needs: `irobot_server/app/build.gradle` sets `compileSdk = 36`, and
   the Gradle wrapper is `irobot_server/gradlew`.

2. Add a job to `.github/workflows/build-and-release.yml`:

   ```yaml
   server-tests:
     runs-on: ubuntu-latest
     steps:
     - uses: actions/checkout@v4
     - uses: actions/setup-java@v4
       with:
         distribution: temurin
         java-version: "17"
     - name: Unit tests
       working-directory: irobot_server
       run: ./gradlew test --no-daemon
   ```

   GitHub's Ubuntu runners ship with an Android SDK. If the build fails because platform 36 isn't
   installed, add a step before the tests:

   ```yaml
   - name: Install Android platform
     run: yes | "$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager" "platforms;android-36"
   ```

   If Gradle needs a different JDK version, the error message will say which. Use that one and note
   it in the PR.

3. Run `./gradlew test` locally in `irobot_server/` first, so you know which tests exist and that
   they pass.

4. Upload the test report so failures are readable:

   ```yaml
   - uses: actions/upload-artifact@v4
     if: failure()
     with:
       name: server-test-report
       path: irobot_server/app/build/reports/tests/
   ```

## Done when

- The `server-tests` job runs the JUnit tests on your PR and is green.
- You've proven the job can fail: push a temporary commit that breaks one assertion in, say,
  `ControlMessageReaderTest`, confirm the job goes red, then remove it before merging.

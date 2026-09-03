# irobot-server

The Android side of iRobot: a Java app (forked from [scrcpy](https://github.com/Genymobile/scrcpy)'s
server) that runs on-device, captures the screen (and, by default, audio) as an H.264 + Opus
stream, and relays control messages back as Android input events. It is pushed to the device via
ADB by the desktop client (`irobot`, built from [`../src/`](../src/)) at connection time — you
don't install it manually.

Source: `app/src/main/java/`. Built with a Gradle-free shell script (`build_server.sh`) rather than
a normal Gradle build, specifically to avoid SSL/TLS issues some network configurations hit (e.g.
VPN with TLS inspection) when Gradle tries to resolve dependencies.

## Requirements

- Android SDK with **API level 37** and **Build Tools 35.0.0**
- Java JDK 21 (the one bundled with Android Studio works: `<SDK>/openjdk/jdk-21.x.x`)
- MSYS2 / Git Bash on Windows

## Build

```bash
cd irobot_server   # from the repo root

# Set SDK and JDK paths (adjust to your installation)
export ANDROID_HOME="/c/Users/<user>/AppData/Local/Android/Sdk"
export JAVA_HOME="/c/Program Files/Android/openjdk/jdk-21.0.8"
export PATH="$JAVA_HOME/bin:$PATH"

bash build_server.sh
```

Output: `build_manual/irobot-server` (~100 KB DEX jar). This directory is a build artifact
(gitignored) — rerun `build_server.sh` any time the Java source changes.

### Deploy to the desktop client

The desktop client looks for the server binary in two places; copy the freshly built one to both
so it gets picked up whether you're running from a plain checkout or a CMake build directory:

```bash
cp build_manual/irobot-server ../server/irobot-server
cp build_manual/irobot-server ../build/apps/server/irobot-server
```

### Known gotchas (already handled by the script)

| Issue                                                     | Fix                                             |
|-------------------------------------------------------------|--------------------------------------------------|
| Platform dir named `android-37.0` instead of `android-37` | Script falls back automatically                 |
| `aidl.exe` rejects POSIX paths on Windows                 | Script converts paths with `cygpath -w`         |
| `d8` not found on Windows                                 | Script uses `d8.bat`                            |
| UTF-8 BOM in Java source files copied from Windows        | Strip with `python3 -c "..."` before building   |
| Missing `android/content/IContentProvider.java`           | Fake stub included in source tree               |
| Socket name mismatch with C++ client                      | `DesktopConnection.java` uses `"irobot"` prefix |

## Compatibility

The server has been updated to the current [scrcpy](https://github.com/Genymobile/scrcpy) wire
protocol (see the main [README](../README.md#server-protocol-updated) for the full list of
changes from the original 2020-era protocol), fixing crashes on Android 12+
(`SurfaceControl.createDisplay` API change) and display corruption caused by the old header
format.

## Project layout

```
irobot_server/
├── app/src/main/java/   # server Java source (scrcpy-based)
├── app/src/main/aidl/   # AIDL stubs used at build time
├── build_server.sh      # Gradle-free build script (writes to build_manual/, gitignored)
└── build.gradle, settings.gradle, gradlew   # kept for IDE/editor support; not used to build
```

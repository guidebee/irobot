# irobot-server

The Android side of iRobot: a Java app (forked from [scrcpy](https://github.com/Genymobile/scrcpy)'s
server) that runs on-device, captures the screen (and, by default, audio) as an H.264 + Opus
stream, and relays control messages back as Android input events. It is pushed to the device via
ADB by the desktop client (`irobot`, built from [`../src/`](../src/)) at connection time — you
don't install it manually.

Source: `app/src/main/java/`. Built with a Gradle-free script (`build_server.sh` / `build_server.cmd`)
rather than a normal Gradle build, specifically to avoid SSL/TLS issues some network configurations
hit (e.g. VPN with TLS inspection) when Gradle tries to resolve dependencies.

## Requirements

- Android SDK with **API level 37** and **Build Tools 35.0.0**
- Java JDK 21 (the one bundled with Android Studio works: `<SDK>/openjdk/jdk-21.x.x`)
- MSYS2 / Git Bash — only needed for `build_server.sh`; `build_server.cmd` runs in plain `cmd.exe`

## Build

**Windows, native `cmd.exe`** (no MSYS2/Git Bash required):

```bat
cd irobot_server

set ANDROID_HOME=C:\Users\<user>\AppData\Local\Android\Sdk
set JAVA_HOME=C:\Program Files\Android\openjdk\jdk-21.0.8
set PATH=%JAVA_HOME%\bin;%PATH%

build_server.cmd
```

**Git Bash / MSYS2 / Linux / macOS:**

```bash
cd irobot_server   # from the repo root

# Set SDK and JDK paths (adjust to your installation)
export ANDROID_HOME="/c/Users/<user>/AppData/Local/Android/Sdk"
export JAVA_HOME="/c/Program Files/Android/openjdk/jdk-21.0.8"
export PATH="$JAVA_HOME/bin:$PATH"

bash build_server.sh
```

Both produce the same output: `build_manual/irobot-server` (~100 KB DEX jar). This directory is a
build artifact (gitignored) — rerun the script any time the Java source changes.

### Deploy to the desktop client

The desktop client looks for the server binary in two places; copy the freshly built one to both
so it gets picked up whether you're running from a plain checkout or a CMake build directory:

```bash
cp build_manual/irobot-server ../server/irobot-server
cp build_manual/irobot-server ../build/apps/server/irobot-server
```

```bat
copy /y build_manual\irobot-server ..\server\irobot-server
copy /y build_manual\irobot-server ..\build\apps\server\irobot-server
```

### Known gotchas (already handled by the scripts)

| Issue                                                       | Fix                                                                          |
|--------------------------------------------------------------|-------------------------------------------------------------------------------|
| Platform dir named `android-37.0` instead of `android-37`  | Both scripts fall back automatically                                        |
| `aidl.exe` rejects POSIX paths on Git Bash/MSYS2            | `build_server.sh` converts paths with `cygpath -w`; `build_server.cmd` uses native Windows paths throughout, so it isn't affected |
| `d8` not found on Windows                                   | Both scripts invoke `d8.bat`                                                |
| Windows `cmd.exe` command-line length limit when dexing many `.class` files | `build_server.cmd` jars `classes/` into one file with `jar cf` and dexes that, instead of passing every `.class` path as an argument |
| UTF-8 BOM in Java source files copied from Windows          | Strip with `python3 -c "..."` before building (bash script only)            |
| Missing `android/content/IContentProvider.java`             | Fake stub included in source tree                                           |
| Socket name mismatch with C++ client                        | `DesktopConnection.java` uses `"irobot"` prefix                             |

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

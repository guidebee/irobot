#!/usr/bin/env bash
set -e

IROBOT_DEBUG=false
IROBOT_VERSION_NAME=1.0.0

PLATFORM=${ANDROID_PLATFORM:-37}
BUILD_TOOLS=${ANDROID_BUILD_TOOLS:-37.0.0}
ANDROID_HOME="${ANDROID_HOME:-$LOCALAPPDATA/Android/Sdk}"
PLATFORM_TOOLS="$ANDROID_HOME/platforms/android-$PLATFORM"
if [ ! -d "$PLATFORM_TOOLS" ]; then
    PLATFORM_TOOLS="$ANDROID_HOME/platforms/android-$PLATFORM.0"
fi
BUILD_TOOLS_DIR="$ANDROID_HOME/build-tools/$BUILD_TOOLS"

# On Windows, d8 and aidl are .bat/.exe instead of plain executables
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" || "$OSTYPE" == "win32" ]]; then
    D8="$BUILD_TOOLS_DIR/d8.bat"
else
    D8="$BUILD_TOOLS_DIR/d8"
fi

SERVER_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="$(realpath "${BUILD_DIR:-$SERVER_DIR/build_manual}")"
CLASSES_DIR="$BUILD_DIR/classes"
GEN_DIR="$BUILD_DIR/gen"
SERVER_BINARY=irobot-server
ANDROID_JAR="$PLATFORM_TOOLS/android.jar"
ANDROID_AIDL="$PLATFORM_TOOLS/framework.aidl"
LAMBDA_JAR="$BUILD_TOOLS_DIR/core-lambda-stubs.jar"
AIDL_DIR="$SERVER_DIR/app/src/main/aidl"
JAVA_DIR="$SERVER_DIR/app/src/main/java"

echo "Platform: android-$PLATFORM"
echo "Build-tools: $BUILD_TOOLS"
echo "Build dir: $BUILD_DIR"

rm -rf "$CLASSES_DIR" "$GEN_DIR" "$BUILD_DIR/$SERVER_BINARY" classes.dex
mkdir -p "$CLASSES_DIR"
mkdir -p "$GEN_DIR/com/guidebee/irobot"

cat > "$GEN_DIR/com/guidebee/irobot/BuildConfig.java" << EOF
package com.guidebee.irobot;

public final class BuildConfig {
  public static final boolean DEBUG = $IROBOT_DEBUG;
  public static final String VERSION_NAME = "$IROBOT_VERSION_NAME";
}
EOF

echo "Generating java from aidl..."
# Convert paths to Windows format since aidl.exe requires native path separators
AIDL_DIR_WIN=$(cygpath -w "$AIDL_DIR")
GEN_DIR_WIN=$(cygpath -w "$GEN_DIR")
ANDROID_AIDL_WIN=$(cygpath -w "$ANDROID_AIDL")

"$BUILD_TOOLS_DIR/aidl" "-o$GEN_DIR_WIN" "-I$AIDL_DIR_WIN" \
    "$AIDL_DIR_WIN\\android\\content\\IOnPrimaryClipChangedListener.aidl"
"$BUILD_TOOLS_DIR/aidl" "-o$GEN_DIR_WIN" "-I$AIDL_DIR_WIN" "-p$ANDROID_AIDL_WIN" \
    "$AIDL_DIR_WIN\\android\\view\\IDisplayWindowListener.aidl"

echo "Compiling java sources..."
cd "$JAVA_DIR"

FAKE_SRC=( android/content/*.java )

SRC=(
    com/guidebee/irobot/*.java
    com/guidebee/irobot/audio/*.java
    com/guidebee/irobot/control/*.java
    com/guidebee/irobot/device/*.java
    com/guidebee/irobot/display/*.java
    com/guidebee/irobot/model/*.java
    com/guidebee/irobot/opengl/*.java
    com/guidebee/irobot/util/*.java
    com/guidebee/irobot/video/*.java
    com/guidebee/irobot/wrappers/*.java
)

javac -encoding UTF-8 \
    -bootclasspath "$ANDROID_JAR" \
    -cp "$LAMBDA_JAR:$GEN_DIR" \
    -d "$CLASSES_DIR" \
    -source 1.8 -target 1.8 \
    "${FAKE_SRC[@]}" \
    "${SRC[@]}"

echo "Dexing..."
cd "$CLASSES_DIR"

"$D8" \
    --classpath "$ANDROID_JAR" \
    --output "$BUILD_DIR/classes.zip" \
    android/view/*.class \
    android/content/*.class \
    $(find . -name "*.class" | grep "com/guidebee/irobot")

cd "$BUILD_DIR"
mv classes.zip "$SERVER_BINARY"
rm -rf "$GEN_DIR" "$CLASSES_DIR"

echo "Done: $BUILD_DIR/$SERVER_BINARY"

@echo off
setlocal enabledelayedexpansion
rem Windows-native (cmd.exe) equivalent of build_server.sh -- no MSYS2/Git Bash
rem required. Same Gradle-free build: generates BuildConfig.java, runs aidl,
rem compiles with javac, then dexes with d8. See README.md for requirements
rem (Android SDK API 37 / Build Tools 35.0.0, JDK 21) and ANDROID_HOME/JAVA_HOME
rem setup.

set "IROBOT_DEBUG=false"
set "IROBOT_VERSION_NAME=1.0.0"

if not defined ANDROID_PLATFORM set "ANDROID_PLATFORM=37"
if not defined ANDROID_BUILD_TOOLS set "ANDROID_BUILD_TOOLS=37.0.0"
if not defined ANDROID_HOME set "ANDROID_HOME=%LOCALAPPDATA%\Android\Sdk"

set "PLATFORM_TOOLS=%ANDROID_HOME%\platforms\android-%ANDROID_PLATFORM%"
if not exist "%PLATFORM_TOOLS%" set "PLATFORM_TOOLS=%ANDROID_HOME%\platforms\android-%ANDROID_PLATFORM%.0"
set "BUILD_TOOLS_DIR=%ANDROID_HOME%\build-tools\%ANDROID_BUILD_TOOLS%"
set "D8=%BUILD_TOOLS_DIR%\d8.bat"

set "SERVER_DIR=%~dp0"
if "%SERVER_DIR:~-1%"=="\" set "SERVER_DIR=%SERVER_DIR:~0,-1%"
if not defined BUILD_DIR set "BUILD_DIR=%SERVER_DIR%\build_manual"
set "CLASSES_DIR=%BUILD_DIR%\classes"
set "GEN_DIR=%BUILD_DIR%\gen"
set "SERVER_BINARY=irobot-server"
set "ANDROID_JAR=%PLATFORM_TOOLS%\android.jar"
set "ANDROID_AIDL=%PLATFORM_TOOLS%\framework.aidl"
set "LAMBDA_JAR=%BUILD_TOOLS_DIR%\core-lambda-stubs.jar"
set "AIDL_DIR=%SERVER_DIR%\app\src\main\aidl"
set "JAVA_DIR=%SERVER_DIR%\app\src\main\java"
set "SOURCES_LIST=%BUILD_DIR%\sources.txt"
set "DEX_INPUT_JAR=%BUILD_DIR%\classes-dex-input.jar"

echo Platform: android-%ANDROID_PLATFORM%
echo Build-tools: %ANDROID_BUILD_TOOLS%
echo Build dir: %BUILD_DIR%

if exist "%CLASSES_DIR%" rmdir /s /q "%CLASSES_DIR%"
if exist "%GEN_DIR%" rmdir /s /q "%GEN_DIR%"
if exist "%BUILD_DIR%\%SERVER_BINARY%" del /q "%BUILD_DIR%\%SERVER_BINARY%"
if exist "%SERVER_DIR%\classes.dex" del /q "%SERVER_DIR%\classes.dex"
mkdir "%CLASSES_DIR%"
mkdir "%GEN_DIR%\com\guidebee\irobot"

> "%GEN_DIR%\com\guidebee\irobot\BuildConfig.java" (
    echo package com.guidebee.irobot;
    echo(
    echo public final class BuildConfig {
    echo   public static final boolean DEBUG = %IROBOT_DEBUG%;
    echo   public static final String VERSION_NAME = "%IROBOT_VERSION_NAME%";
    echo }
)

echo Generating java from aidl...
"%BUILD_TOOLS_DIR%\aidl.exe" "-o%GEN_DIR%" "-I%AIDL_DIR%" ^
    "%AIDL_DIR%\android\content\IOnPrimaryClipChangedListener.aidl"
if errorlevel 1 goto :error
"%BUILD_TOOLS_DIR%\aidl.exe" "-o%GEN_DIR%" "-I%AIDL_DIR%" "-p%ANDROID_AIDL%" ^
    "%AIDL_DIR%\android\view\IDisplayWindowListener.aidl"
if errorlevel 1 goto :error

echo Compiling java sources...
rem javac's @argfile format treats backslash as an escape character, so
rem Windows-style paths get corrupted if written as-is (e.g. "\a" is consumed
rem as an escape and disappears) -- write forward-slash paths instead, which
rem javac accepts natively on Windows.
set "SRC_DIRS=android\content com\guidebee\irobot com\guidebee\irobot\audio com\guidebee\irobot\control com\guidebee\irobot\device com\guidebee\irobot\display com\guidebee\irobot\model com\guidebee\irobot\opengl com\guidebee\irobot\util com\guidebee\irobot\video com\guidebee\irobot\wrappers"
> "%SOURCES_LIST%" (
    for %%D in (%SRC_DIRS%) do (
        for %%F in ("%JAVA_DIR%\%%D\*.java") do (
            set "P=%%~F"
            set "P=!P:\=/!"
            echo "!P!"
        )
    )
)

javac -encoding UTF-8 ^
    -bootclasspath "%ANDROID_JAR%" ^
    -cp "%LAMBDA_JAR%;%GEN_DIR%" ^
    -d "%CLASSES_DIR%" ^
    -source 1.8 -target 1.8 ^
    @"%SOURCES_LIST%"
if errorlevel 1 goto :error

echo Packaging classes for dexing...
if exist "%DEX_INPUT_JAR%" del /q "%DEX_INPUT_JAR%"
pushd "%CLASSES_DIR%"
jar cf "%DEX_INPUT_JAR%" .
if errorlevel 1 (popd & goto :error)
popd

echo Dexing...
call "%D8%" --classpath "%ANDROID_JAR%" --output "%BUILD_DIR%\classes.zip" "%DEX_INPUT_JAR%"
if errorlevel 1 goto :error

move /y "%BUILD_DIR%\classes.zip" "%BUILD_DIR%\%SERVER_BINARY%" >nul
del /q "%DEX_INPUT_JAR%" "%SOURCES_LIST%" 2>nul
rmdir /s /q "%GEN_DIR%"
rmdir /s /q "%CLASSES_DIR%"

echo Done: %BUILD_DIR%\%SERVER_BINARY%
exit /b 0

:error
echo Build failed.
exit /b 1

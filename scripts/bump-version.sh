#!/bin/sh
# Bump the project version in CMakeLists.txt (project(... VERSION x.y.z ...)).
#
# Usage:
#   scripts/bump-version.sh              # bump patch: 1.0.0 -> 1.0.1
#   scripts/bump-version.sh patch|minor|major
#   scripts/bump-version.sh 1.2.0        # set version explicitly

set -eu

cd "$(dirname "$0")/.."

CMAKE_FILE="CMakeLists.txt"
ARG="${1:-patch}"

CURRENT=$(grep -oE 'project\([^)]*VERSION[[:space:]]+[0-9]+\.[0-9]+\.[0-9]+' "$CMAKE_FILE" \
    | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')

MAJOR=$(echo "$CURRENT" | cut -d. -f1)
MINOR=$(echo "$CURRENT" | cut -d. -f2)
PATCH=$(echo "$CURRENT" | cut -d. -f3)

case "$ARG" in
    patch)
        PATCH=$((PATCH + 1))
        ;;
    minor)
        MINOR=$((MINOR + 1))
        PATCH=0
        ;;
    major)
        MAJOR=$((MAJOR + 1))
        MINOR=0
        PATCH=0
        ;;
    [0-9]*.[0-9]*.[0-9]*)
        MAJOR=$(echo "$ARG" | cut -d. -f1)
        MINOR=$(echo "$ARG" | cut -d. -f2)
        PATCH=$(echo "$ARG" | cut -d. -f3)
        ;;
    *)
        echo "Usage: $0 [patch|minor|major|X.Y.Z]" >&2
        exit 1
        ;;
esac

NEW="$MAJOR.$MINOR.$PATCH"

sed -i -E "s/(project\([^)]*VERSION[[:space:]]+)$CURRENT/\1$NEW/" "$CMAKE_FILE"

echo "Version bumped: $CURRENT -> $NEW"

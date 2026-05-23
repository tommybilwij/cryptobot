#!/usr/bin/env bash
# cryptobot — project version bumper.
#
# Files this script bumps:
#   - VERSION                    (canonical source; one-line semver)
#   - backend/pyproject.toml     ([project].version)
#   - backend/app/main.py        (FastAPI(..., version="..."))
#
# Usage:
#   scripts/bump-version.sh patch | minor | major | <x.y.z>
#
# Does NOT commit, tag, or push — leaves all of that to the caller
# (typically /pr-summary or a manual git commit + git tag + git push).

set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

if [ $# -ne 1 ]; then
    echo "usage: $0 patch|minor|major|<x.y.z>" >&2
    exit 1
fi
ARG="$1"

# ── Read current version ────────────────────────────────────────────────
# Canonical source: VERSION file at repo root. Bootstrap-create if missing
# (so the first ever run can compute the next version from pyproject.toml).
if [ -f VERSION ]; then
    CURRENT="$(cat VERSION | tr -d '[:space:]')"
else
    CURRENT="$(python3 -c "
import re, pathlib
text = pathlib.Path('backend/pyproject.toml').read_text()
m = re.search(r'(?m)^version\s*=\s*[\"\\']([^\"\\']+)[\"\\']', text)
print(m.group(1) if m else '0.0.0')
")"
fi

if ! [[ "$CURRENT" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "error: unparseable current version: $CURRENT" >&2
    exit 1
fi

IFS='.' read -r CUR_MAJ CUR_MIN CUR_PAT <<< "$CURRENT"

# ── Compute new version ─────────────────────────────────────────────────
case "$ARG" in
    patch)  NEW="${CUR_MAJ}.${CUR_MIN}.$((CUR_PAT + 1))" ;;
    minor)  NEW="${CUR_MAJ}.$((CUR_MIN + 1)).0" ;;
    major)  NEW="$((CUR_MAJ + 1)).0.0" ;;
    [0-9]*.[0-9]*.[0-9]*) NEW="$ARG" ;;
    *)
        echo "error: argument must be 'patch', 'minor', 'major', or 'x.y.z' (got: $ARG)" >&2
        exit 1
        ;;
esac

if ! [[ "$NEW" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "error: computed new version is not semver: $NEW" >&2
    exit 1
fi

echo "Bumping ${CURRENT} -> ${NEW}"

# ── Update each version-carrying file ───────────────────────────────────

# 1. VERSION file (create or overwrite)
printf '%s\n' "$NEW" > VERSION
echo "  updated: VERSION"

# 2. backend/pyproject.toml — only the [project].version line, not the
#    target-version / python_version lines that also contain "version".
if [ -f backend/pyproject.toml ]; then
    python3 - "$NEW" <<'PY'
import pathlib, re, sys
new = sys.argv[1]
path = pathlib.Path("backend/pyproject.toml")
text = path.read_text()
updated = re.sub(
    r'(?m)^(version\s*=\s*)["\'][^"\']+["\']',
    rf'\g<1>"{new}"',
    text,
    count=1,
)
path.write_text(updated)
PY
    echo "  updated: backend/pyproject.toml"
fi

# 3. backend/app/main.py — FastAPI(..., version="...") parameter
if [ -f backend/app/main.py ]; then
    python3 - "$NEW" <<'PY'
import pathlib, re, sys
new = sys.argv[1]
path = pathlib.Path("backend/app/main.py")
text = path.read_text()
updated = re.sub(
    r'(FastAPI\([^)]*?version\s*=\s*)["\'][^"\']+["\']',
    rf'\g<1>"{new}"',
    text,
    count=1,
)
path.write_text(updated)
PY
    echo "  updated: backend/app/main.py"
fi

echo
echo "Bumped ${CURRENT} -> ${NEW}"
echo
echo "Next steps:"
echo "  git diff --stat"
echo "  git add -u"
echo "  git add VERSION                                   # if not yet tracked"
echo "  git commit -m \"chore: bump version to v${NEW}\""
echo "  git tag -a v${NEW} -m \"v${NEW}\""
echo "  git push --follow-tags"

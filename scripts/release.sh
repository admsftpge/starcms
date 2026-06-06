#!/usr/bin/env bash
# Release ritual. Run AFTER bumping the version in pyproject.toml and
# committing that bump (deciding the version is your job: feat → minor,
# fix → patch while we're 0.x).
#
# Usage:  export UV_PUBLISH_TOKEN="pypi-..."   # project-scoped token, never account-wide
#         uv run poe release
#
# Refuses to run on: dirty tree, not-main, unpushed commits, an existing
# tag, failing checks, or missing token/gh auth — the classic release
# mistakes.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

die() { echo "✗ $*" >&2; exit 1; }

# The tag is derived from pyproject.toml, so the two can't drift.
VERSION=$(uv version --short)
TAG="v$VERSION"

[[ -n "${UV_PUBLISH_TOKEN:-}" ]] || die "UV_PUBLISH_TOKEN is not set"
gh auth status >/dev/null 2>&1 || die "gh is not authenticated"
[[ -z $(git status --porcelain) ]] || die "working tree not clean"
[[ $(git branch --show-current) == "main" ]] || die "not on main"
git rev-parse "$TAG" >/dev/null 2>&1 \
    && die "tag $TAG already exists — bump the version in pyproject.toml first"
git fetch --quiet origin
[[ $(git rev-parse HEAD) == $(git rev-parse origin/main) ]] \
    || die "local main differs from origin/main — push (or pull) first"

uv run poe check
rm -rf dist && uv build

echo
read -rp "Release $TAG to PyPI and GitHub? [y/N] " answer
[[ $answer == [yY] ]] || { echo "aborted — nothing pushed or published"; exit 1; }

# Publish before tagging: if PyPI fails, nothing remote has happened and a
# rerun is clean (--check-url even skips files a partial upload already
# sent). When trusted publishing lands this inverts: the script will end
# at the tag push, and a tag-triggered CI workflow will do the publishing.
uv publish --check-url https://pypi.org/simple/
git tag "$TAG"
git push origin "$TAG"
gh release create "$TAG" --generate-notes
echo "✓ $VERSION is live: https://pypi.org/project/starcms/$VERSION/"

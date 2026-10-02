#!/bin/sh
# tools/release.sh "title" "notes": test, tag, GitHub release, Homebrew formula, landing. One command per version.
# The version comes from plank.py. Commit everything first; a red suite releases nothing.
set -e
cd "$(dirname "$0")/.."
v=$(./plank --version | awk '{print $2}')
title="${1:?usage: tools/release.sh \"title\" \"notes\"}"
notes="${2:?usage: tools/release.sh \"title\" \"notes\"}"

python3 tools/gen-demo.py >/dev/null
if ! python3 test.py >/tmp/plank-test.log; then
    grep -v '^ok' /tmp/plank-test.log
    echo "tests failed, nothing released"
    exit 1
fi
if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "uncommitted changes, commit first"
    exit 1
fi

git tag "v$v"
git push -q origin HEAD "v$v"
gh release create "v$v" --title "$title" --notes "$notes" >/dev/null

# the tap: point the formula at this tag, with the tarball's real checksum
sha=""
for try in 1 2 3 4 5 6; do
    sha=$(curl -sfL "https://github.com/nulljosh/plank/archive/refs/tags/v$v.tar.gz" | shasum -a 256 | cut -d' ' -f1)
    [ -n "$sha" ] && break
    sleep 5
done
[ -n "$sha" ] || { echo "could not fetch the v$v tarball for the formula"; exit 1; }
tap=../homebrew-plank
[ -d "$tap" ] || git clone -q https://github.com/nulljosh/homebrew-plank "$tap"
sed -i '' -e "s|tags/v[0-9.]*\.tar\.gz|tags/v$v.tar.gz|" -e "s|sha256 \".*\"|sha256 \"$sha\"|" "$tap/Formula/plank-lang.rb"
git -C "$tap" commit -qam "plank $v" && git -C "$tap" push -q

npx wrangler deploy 2>&1 | grep -E "Deployed|rror"
echo "released $v"

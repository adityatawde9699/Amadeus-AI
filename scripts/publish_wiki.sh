#!/usr/bin/env bash
# publish_wiki.sh
# Publishes the wiki/ directory to the GitHub Wiki repository.
#
# Usage:
#   bash scripts/publish_wiki.sh
#
# Prerequisites:
#   - Git configured with push access to the repo
#   - GitHub Wiki enabled on the repository (Settings → Features → Wikis)
#   - Run at least once manually from the GitHub UI to initialise the wiki repo

set -euo pipefail

REPO="adityatawde9699/Amadeus-AI"
WIKI_REMOTE="https://github.com/${REPO}.wiki.git"
WIKI_DIR="$(cd "$(dirname "$0")/.." && pwd)/wiki"
WORK_DIR=$(mktemp -d)

echo "📚 Publishing Amadeus-AI wiki..."
echo "   Source: ${WIKI_DIR}"
echo "   Remote: ${WIKI_REMOTE}"

# Clone the wiki repo into a temp dir
git clone "${WIKI_REMOTE}" "${WORK_DIR}"

# Copy all wiki pages (overwrite existing)
cp -r "${WIKI_DIR}/." "${WORK_DIR}/"

# Commit and push
cd "${WORK_DIR}"
git add -A
git diff --cached --quiet && echo "✅ Wiki is already up to date." && exit 0

git commit -m "docs(wiki): update wiki from source [$(date -u +%Y-%m-%d)]"
git push origin master

echo "✅ Wiki published successfully."
echo "   View at: https://github.com/${REPO}/wiki"

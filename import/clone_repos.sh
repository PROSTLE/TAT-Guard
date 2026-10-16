# import/clone_repos.sh — pins each repo to a commit and records it
# Source: 05_RESOURCE_IMPORTER.md §3. Run from the repo root: bash import/clone_repos.sh
set -euo pipefail
mkdir -p vendor_refs && cd vendor_refs
for url in \
  https://github.com/exasol/mcp-server \
  https://github.com/exasol-labs/exasol-agent-skills \
  https://github.com/exasol/pyexasol \
  https://github.com/exasol-labs/exapump \
  https://github.com/exasol/transformers-extension ; do
  name=$(basename "$url")
  [ -d "$name" ] || git clone --depth 1 "$url" "$name"
  commit=$(git -C "$name" rev-parse HEAD)
  lic=$(ls "$name" | grep -iE '^(LICEN[CS]E|COPYING)' | head -1 || true)
  echo "{\"url\":\"$url\",\"commit\":\"$commit\",\"license_file\":\"${lic:-NONE}\",\"retrieved\":\"$(date -Iseconds)\"}"
done > ../import/repos.lock.jsonl

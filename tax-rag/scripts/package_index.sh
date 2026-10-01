#!/usr/bin/env bash
# Packages the SQLite index (hier_v1 chunks + embeddings) for distribution without the raw PDFs.
# Produces dist/taxrag-index-<date>.sqlite.gz (+ split parts if > 90MB for GitHub release/commit limits).
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p dist
STAMP=$(date -u +%Y%m%d)
OUT=dist/taxrag-index-$STAMP.sqlite
.venv/bin/python - <<PY
import sqlite3
src = sqlite3.connect('data/taxrag.sqlite'); dst = sqlite3.connect('$OUT')
src.backup(dst); dst.close(); src.close()
PY
gzip -f "$OUT"
ls -la "$OUT.gz"
if [ "$(stat -c %s "$OUT.gz")" -gt 94371840 ]; then
  split -b 90m -d "$OUT.gz" "$OUT.gz.part"
  echo "split into parts; reassemble with: cat $OUT.gz.part* > $OUT.gz && gunzip $OUT.gz"
fi

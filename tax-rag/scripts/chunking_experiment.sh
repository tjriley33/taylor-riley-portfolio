#!/usr/bin/env bash
# Runs the chunking experiment on a COPY of the index so the shipped DB stays hier_v1-only.
# Usage: scripts/chunking_experiment.sh [strategies]   (default: hier_v1,fixed_512,page_v1)
set -euo pipefail
cd "$(dirname "$0")/.."
STRATS=${1:-hier_v1,fixed_512,page_v1}
EXP_DIR=data/experiment
mkdir -p "$EXP_DIR" eval_results
cp data/taxrag.sqlite "$EXP_DIR/taxrag.sqlite"
rm -f "$EXP_DIR/taxrag.sqlite-wal" "$EXP_DIR/taxrag.sqlite-shm"
export TAXRAG_DB_PATH="$EXP_DIR/taxrag.sqlite"
.venv/bin/python -m taxrag.cli reindex --strategies "$STRATS"
IFS=',' read -ra ARR <<< "$STRATS"
for s in "${ARR[@]}"; do
  echo "=== evaluating $s"
  .venv/bin/python -m taxrag.cli evaluate --strategy "$s" --report "eval_results/eval_${s}.json" | tail -40
done

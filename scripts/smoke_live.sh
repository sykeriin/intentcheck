#!/usr/bin/env bash
# First live smoke test of a real model: 5 DEV scenarios, hard token budget, transcripts recorded.
# Never touches the llm-test split (PREREG.md section 4). Run this before anything else with a new provider.
#
#   export ANTHROPIC_API_KEY=...                 && scripts/smoke_live.sh llm:anthropic:<model>
#   export OPENAI_API_KEY=... OPENAI_BASE_URL=.. && scripts/smoke_live.sh llm:openai:<model>
#   scripts/smoke_live.sh camel:openai:<model>   # same, with the typed-fields-only buyer
set -euo pipefail
SPEC="${1:?usage: smoke_live.sh <llm:anthropic:MODEL | llm:openai:MODEL | camel:...> [token_budget]}"
BUDGET="${2:-300000}"
cd "$(dirname "$0")/.."
python -m dia.cli run --split dev --n 5 --buyers "$SPEC" --configs full \
  --token-budget "$BUDGET" --transcripts results/smoke_transcripts --out results/smoke.jsonl --resamples 200
echo
echo "Check results/smoke.jsonl: any status 'error' or 'incomplete' is a harness or provider bug to fix BEFORE the"
echo "registered run (fixes made now are legitimate; fixes after the first llm-test run need an amendment)."
echo "Transcripts: results/smoke_transcripts/ (one JSON per scenario, replayable with llm:replay:<dir>)."

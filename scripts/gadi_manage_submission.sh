#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Run submission management on Gadi (or any machine) without Pixi.

This script:
1) runs scripts/manage_submission.py
2) recompiles dashboard/progress.json
3) optionally commits/pushes and opens a PR with gh

Usage:
  scripts/gadi_manage_submission.sh \
    --action ingest|update|delete \
    --model MODEL \
    --experiment EXPERIMENT \
    --member MEMBER \
    [--report /path/to/moppy_batch_report.json] \
    [--delete-scope member|cmorisation] \
    [--create-pr] \
    [--base main]

Examples:
  scripts/gadi_manage_submission.sh \
    --action ingest \
    --report /scratch/path/moppy_batch_report.json \
    --model ACCESS-ESM1.6 \
    --experiment historical \
    --member r2i1p1f1

  scripts/gadi_manage_submission.sh \
    --action delete \
    --model ACCESS-ESM1.6 \
    --experiment historical \
    --member r2i1p1f1 \
    --delete-scope cmorisation \
    --create-pr
EOF
}

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "ERROR: required command not found: $cmd" >&2
    exit 1
  fi
}

ACTION=""
MODEL=""
EXPERIMENT=""
MEMBER=""
REPORT=""
DELETE_SCOPE="member"
CREATE_PR="false"
BASE="main"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --action)
      ACTION="${2:-}"
      shift 2
      ;;
    --model)
      MODEL="${2:-}"
      shift 2
      ;;
    --experiment)
      EXPERIMENT="${2:-}"
      shift 2
      ;;
    --member)
      MEMBER="${2:-}"
      shift 2
      ;;
    --report)
      REPORT="${2:-}"
      shift 2
      ;;
    --delete-scope)
      DELETE_SCOPE="${2:-}"
      shift 2
      ;;
    --create-pr)
      CREATE_PR="true"
      shift
      ;;
    --base)
      BASE="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ -z "$ACTION" || -z "$MODEL" || -z "$EXPERIMENT" || -z "$MEMBER" ]]; then
  echo "ERROR: --action, --model, --experiment, and --member are required" >&2
  usage >&2
  exit 1
fi

if [[ "$ACTION" != "ingest" && "$ACTION" != "update" && "$ACTION" != "delete" ]]; then
  echo "ERROR: --action must be one of: ingest, update, delete" >&2
  exit 1
fi

if [[ "$DELETE_SCOPE" != "member" && "$DELETE_SCOPE" != "cmorisation" ]]; then
  echo "ERROR: --delete-scope must be one of: member, cmorisation" >&2
  exit 1
fi

if [[ "$ACTION" == "ingest" || "$ACTION" == "update" ]]; then
  if [[ -z "$REPORT" ]]; then
    echo "ERROR: --report is required for ingest/update" >&2
    exit 1
  fi
  if [[ ! -f "$REPORT" ]]; then
    echo "ERROR: report file not found: $REPORT" >&2
    exit 1
  fi
fi

require_cmd python
require_cmd git

cmd=(python scripts/manage_submission.py
  --action "$ACTION"
  --model "$MODEL"
  --experiment "$EXPERIMENT"
  --member "$MEMBER"
  --delete-scope "$DELETE_SCOPE")

if [[ "$ACTION" == "ingest" || "$ACTION" == "update" ]]; then
  cmd+=( --report "$REPORT" )
fi

echo "Running submission operation..."
"${cmd[@]}"

echo "Rebuilding dashboard/progress.json..."
python scripts/compile_progress.py --output dashboard/progress.json

if [[ "$CREATE_PR" != "true" ]]; then
  echo
  echo "Done. Next steps:"
  echo "  git add progress/ dashboard/progress.json"
  echo "  git commit -m \"chore(progress): ${ACTION} ${MODEL} ${EXPERIMENT}/${MEMBER}\""
  echo "  git push"
  exit 0
fi

require_cmd gh

if [[ -n "$(git status --porcelain)" ]]; then
  BRANCH="submission/${ACTION}-${MODEL}-${EXPERIMENT}-${MEMBER}-$(date -u +%Y%m%dT%H%M%SZ)"
  git checkout -b "$BRANCH"
  git add progress/ dashboard/progress.json
  git commit -m "chore(progress): ${ACTION} ${MODEL} ${EXPERIMENT}/${MEMBER}"
  git push -u origin "$BRANCH"

  gh pr create \
    --base "$BASE" \
    --head "$BRANCH" \
    --title "chore(progress): ${ACTION} ${MODEL} ${EXPERIMENT}/${MEMBER}" \
    --body "Submission update prepared on Gadi.

Action: ${ACTION}
Model: ${MODEL}
Experiment: ${EXPERIMENT}
Member: ${MEMBER}
Delete scope: ${DELETE_SCOPE}"
else
  echo "No changes detected after operation; no PR created."
fi

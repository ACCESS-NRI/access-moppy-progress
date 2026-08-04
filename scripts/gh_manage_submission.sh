#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Dispatch the "Manage submission progress" GitHub Actions workflow.

Usage:
  scripts/gh_manage_submission.sh \
    --action ingest|update|delete \
    --model MODEL \
    --experiment EXPERIMENT \
    --member MEMBER \
    [--report-path PATH_IN_REPO] \
    [--report-url HTTPS_URL] \
    [--delete-scope member|cmorisation] \
    [--ref GIT_REF]

Examples:
  scripts/gh_manage_submission.sh \
    --action ingest \
    --model ACCESS-ESM1.6 \
    --experiment historical \
    --member r2i1p1f1 \
    --report-path reports/uploads/moppy_batch_report.json

  scripts/gh_manage_submission.sh \
    --action delete \
    --model ACCESS-ESM1.6 \
    --experiment historical \
    --member r2i1p1f1 \
    --delete-scope cmorisation
EOF
}

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "ERROR: required command not found: $cmd" >&2
    exit 1
  fi
}

require_cmd gh

ACTION=""
MODEL=""
EXPERIMENT=""
MEMBER=""
REPORT_PATH=""
REPORT_URL=""
DELETE_SCOPE="member"
REF="main"

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
    --report-path)
      REPORT_PATH="${2:-}"
      shift 2
      ;;
    --report-url)
      REPORT_URL="${2:-}"
      shift 2
      ;;
    --delete-scope)
      DELETE_SCOPE="${2:-}"
      shift 2
      ;;
    --ref)
      REF="${2:-}"
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
  if [[ -z "$REPORT_PATH" && -z "$REPORT_URL" ]]; then
    echo "ERROR: ingest/update requires --report-path or --report-url" >&2
    exit 1
  fi
fi

echo "Dispatching manage_submission.yml"
echo "  action      : $ACTION"
echo "  model       : $MODEL"
echo "  experiment  : $EXPERIMENT"
echo "  member      : $MEMBER"
echo "  delete_scope: $DELETE_SCOPE"
echo "  ref         : $REF"
if [[ -n "$REPORT_PATH" ]]; then
  echo "  report_path : $REPORT_PATH"
fi
if [[ -n "$REPORT_URL" ]]; then
  echo "  report_url  : $REPORT_URL"
fi

args=(
  workflow run manage_submission.yml
  --ref "$REF"
  -f "action=$ACTION"
  -f "model=$MODEL"
  -f "experiment=$EXPERIMENT"
  -f "member=$MEMBER"
  -f "delete_scope=$DELETE_SCOPE"
)

if [[ -n "$REPORT_PATH" ]]; then
  args+=( -f "report_path=$REPORT_PATH" )
fi
if [[ -n "$REPORT_URL" ]]; then
  args+=( -f "report_url=$REPORT_URL" )
fi

gh "${args[@]}"

echo
echo "Workflow dispatched. Latest run:"
gh run list --workflow manage_submission.yml --limit 1
echo
echo "To live-watch the latest run:"
echo "  gh run watch \$(gh run list --workflow manage_submission.yml --limit 1 --json databaseId -q '.[0].databaseId')"

# ACCESS CMIP7 Submission Tracker

Entry dashboard for the ACCESS CMIP7 submission workflow. Tracks progress through
CMORisation, QC, and ESGF publication for ACCESS model submissions, with
[access-moppy-qc-registry](https://github.com/access-nri/access-moppy-qc-registry)
serving as the companion QC registry.

## Dashboard

**→ [Open dashboard](https://access-nri.github.io/access-moppy-progress/)**

| View | Description |
|---|---|
| **Overview** | Per-experiment cards with progress bars per ensemble member |
| **Experiment Detail** | Variable × member matrix for one experiment |
| **Member Timeline** | All variables for one (model, experiment, member) sorted by stage |
| **Variable Pipeline** | One variable across all (experiment, member) combinations, with links to inspect or suggest QC checks |
| **CMOR Requests** | GitHub issue-backed CMORisation work requests, plus planned combinations still missing retrospective request metadata |

## States and release gates

CMORisation is the entry condition, not an achievement: every variable with a
report has been CMORised. What the dashboard tracks is whether it has cleared
the three checks that decide if it can be handed to CSIRO for scientific review
and to NCI for publication.

```
planned ──→ CMORised ──→ [ R  value range ] ──→ ready_for_review ──→ published
   │                     [ W  WCRP compliance ]        │
   │                     [ K  repack        ]          └→ scientific review (CSIRO)
   └→ cmorise_failed          │
                              └→ blocked (a gate failed)
```

Each gate is `pass`, `warn`, `fail`, `not_run`, or `implied`. The dashboard
draws them as a three-segment strip in fixed R-W-K order, so a grey segment
reads as "this check has not run" just as clearly as a red one reads as a
failure.

`implied` means a gate is satisfied by inference rather than by a recorded
result, and is drawn hatched. Repack is currently in that position: ACCESS-MOPPy
runs `cmip7repack` inline for CMIP7 output and a repack failure aborts the task,
so a completed task does imply a repacked file — but nothing is written down.
Any recorded result overrides the inference.

A unit's `state` is derived from the three gates:

| State | Meaning |
|---|---|
| `planned` | In the plan, no report yet (or still in flight) |
| `cmorise_failed` | The CMORisation task failed — a build failure, not a QC finding |
| `cmorised` | CMORised, at least one gate still outstanding |
| `blocked` | A gate failed; needs a fix before it can go anywhere |
| `ready_for_review` | All three gates cleared — hand to CSIRO and NCI |
| `published` | Published to ESGF |

Every state here has a producer. The retired `qc_pending` / `qc_pass` /
`qc_warn` / `qc_fail` stages had none, so the dashboard advertised a QC pipeline
that could never report anything, and the "QC checks" bucket was in fact
counting CMORisation failures.

## Recording gate results

Gate results live in `progress/<model>/<experiment>/<member>/qc.json`, following
`schemas/qc.schema.json`:

```json
{
  "schema_version": "access-moppy.qc.v1",
  "model": "ACCESS-ESM1.6",
  "experiment_id": "historical",
  "variant_label": "r1i1p1f1",
  "checked_at": "2026-08-26T04:11:00Z",
  "variables": {
    "ocean.tos.tavg-u-hxy-sea.mon.glb": {
      "range":  {
        "result": "warn",
        "check_id": "global_stats.min_max_range",
        "observed": [-2.1, 34.8], "allowed": [-2.0, 34.0], "units": "degC"
      },
      "wcrp":   {
        "result": "pass",
        "check_id": "wcrp",
        "suites": ["cf:1.11", "wcrp_cmip7:1.0"],
        "cv_version": "esgvoc-1.4.2",
        "backfilled": true
      },
      "repack": { "result": "pass", "tool": "cmip7repack" }
    }
  }
}
```

Variables are keyed by CMIP7 branded name; the compound request name or short
name also resolve. `check_id` refers to a check in
[access-moppy-qc-registry](https://github.com/access-nri/access-moppy-qc-registry),
which is the division of labour between the two repositories: **the registry
holds requirements** (which checks exist and which are mandatory for a variable
or experiment), **this repository holds results**. They join on `check_id`.

Validate before committing:

```bash
python scripts/validate_qc.py
pytest tests -q
```

### Where the results come from

`qc.json` is written automatically during ingestion — `ingest_report.py` and
`sync_reports.py` both call `qc_from_report.py`, which extracts the gates from
the batch report they are ingesting. Nothing has to be recorded by hand:

| Gate | Read from |
|---|---|
| `range` | `tasks[].output_summary.gates.range`, stamped by the worker after each file is validated |
| `repack` | `tasks[].output_summary.gates.repack`, stamped after `cmip7repack` runs |
| `wcrp` | `tasks[].compliance`, from a run with `compliance_check: true` or from `moppy-compliance-backfill` |

Reports produced before ACCESS-MOPPy stamped these fields carry none of them,
and nothing is invented for them: their gates stay `not_run`. For the range
gate there is one fallback — a report built by `moppy-batch-report` *without*
`--skip-qc` carries a batch-level `qc` block, and its findings are matched back
to tasks by output file path.

To fill in the WCRP gate for runs that have already completed, no code change
is needed on the ACCESS-MOPPy side:

```bash
# on Gadi, in the run directory
moppy-compliance-backfill --db cmor_tasks.db     # writes each verdict to the task row
moppy-batch-report --db cmor_tasks.db            # rebuild the report with them in it
```

Then re-run the sync, and the `wcrp` column lights up retrospectively.

## Repository structure

```
plans/                          # Submission intent — one YAML per model
  ACCESS-ESM1.6.yaml
requests/                       # CMORisation work requests accepted from GitHub issues
  <model>_<experiment>_<member>.yaml
progress/                       # Ingested runtime reports
  <model>/
    <experiment>/
      <member>/
        cmorisation.json        ← from moppy_batch_report.json (via ingest_report.py)
        qc.json                 ← release gate results (schemas/qc.schema.json)
        publication.json        ← manually updated or ESGF API script
schemas/                        # JSON Schemas for validation
scripts/
  ingest_report.py              # Place a batch report into the hierarchy
  sync_reports.py               # Bulk-ingest a tree of reports rsynced from Gadi
  compile_progress.py           # Build dashboard/progress.json
  qc_from_report.py             # Extract release gates from a batch report
  validate_plans.py             # Validate plans/*.yaml
  validate_qc.py                # Validate progress/**/qc.json
dashboard/                      # Static GitHub Pages site
  index.html / style.css / app.js
  progress.json                 # Generated by CI — do not edit manually
.github/
  workflows/
    validate_plans.yml          # Run on every PR touching plans/ or progress/
    build_dashboard.yml         # Rebuild + deploy on merge to main
    sync_gadi_reports.yml       # Nightly rsync from Gadi + ingest + deploy
```

## Adding a new model

1. Add `plans/<Model-ID>.yaml` following the schema in `schemas/plan.schema.json`.
2. Open a PR — CI will validate the file automatically.

## Requesting CMORisation work

Open the GitHub issue form:

`https://github.com/access-nri/access-moppy-progress/issues/new?template=propose_submission.yml`

The form captures the experiment/member to CMORise, the Gadi path to the raw
output, the parent experiment metadata needed by ACCESS-MOPPy, extra notes, and
the best contact for follow-up questions.

When a maintainer applies the `status/accepted` label to the issue, CI will:

1. Convert the issue into `requests/<model>_<experiment>_<member>.yaml`.
2. Open a PR with the generated request file for review.
3. Surface the request in the dashboard `CMOR Requests` view.

That request view also highlights planned experiment/member combinations that
still have no request record, so existing work can be backfilled
retrospectively through the same issue workflow.

## Ingesting a batch report

After a MOPPy run completes on the HPC:

```bash
# On NCI or locally, after copying the report file:
python scripts/ingest_report.py \
    --report /path/to/moppy_batch_report.json \
    --model  ACCESS-ESM1.6 \
    --member r1i1p1f1

# Then commit and push:
git add progress/
git commit -m "chore: ingest ACCESS-ESM1.6 historical/r1i1p1f1"
git push
```

CI will recompile `progress.json` and redeploy the dashboard automatically.

## Automated nightly sync from Gadi

`sync_gadi_reports.yml` keeps the dashboard current without manual ingestion. It
runs at **00:00 Australia/Brisbane** (`0 14 * * *` UTC — Brisbane has no daylight
saving) and can also be triggered by hand from the **Actions** tab, with an
optional `dry_run` input that rsyncs and reports what would change without
committing.

Each run:

1. Rsyncs `batch_config.yml` and `moppy_batch_report_*.json` from
   `/scratch/p73/ESM1p6_CMORised/` on Gadi — the same command used manually:

   ```bash
   rsync -av --prune-empty-dirs \
       --include='*/' \
       --include='batch_config.yml' \
       --include='moppy_batch_report_*.json' \
       --exclude='*' \
       <user>@gadi.nci.org.au:/scratch/p73/ESM1p6_CMORised/ ./ESM1p6_CMORised/
   ```

2. Runs `scripts/sync_reports.py` to ingest the tree into `progress/`.
3. Recompiles `progress.json` as a sanity check.
4. Commits and pushes to `main` **only if `progress/` actually changed**, then
   dispatches `build_dashboard.yml` to redeploy the dashboard.

Nothing is committed when the reports are unchanged: `sync_reports.py` compares
report content and leaves the existing `ingested_at` timestamp alone, so
re-running produces no diff.

### Required configuration

| Kind | Name | Value |
|---|---|---|
| Secret | `GADI_USER` | NCI username, e.g. `rb5533` |
| Secret | `DEPLOY_KEY` | Private half of a passphrase-less SSH key whose public half is in `~/.ssh/authorized_keys` on Gadi |
| Secret (optional) | `GADI_DATA_PATH` | Source path to sync; defaults to `/scratch/p73/ESM1p6_CMORised/` |

Generate and install the key with:

```bash
ssh-keygen -t ed25519 -f gadi_dashboard_key -N "" -C "access-moppy-progress CI"
ssh-copy-id -i gadi_dashboard_key.pub <user>@gadi.nci.org.au
```

Then add the contents of `gadi_dashboard_key` (the private file, including the
`BEGIN`/`END` lines) as the `DEPLOY_KEY` repository secret under
**Settings → Secrets and variables → Actions**, and delete the local copy.

### How reports are matched to records

`sync_reports.py` resolves each report's `(source_id, experiment_id,
variant_label)` from the report itself, falling back to the sibling
`batch_config.yml` for older reports that omit them, and normalises the result
against `plans/*.yaml` — so `ACCESS-ESM1-6` / `esm-picontrol` is written to
`progress/ACCESS-ESM1.6/esm-piControl/`. Where one run directory holds several
reports, the most recent wins.

When two *different* run directories claim the same experiment and member, the
combination is skipped and reported rather than guessed at, so a mislabelled
`batch_config.yml` cannot silently overwrite another experiment's record. Fix
the offending config on Gadi, or pass `--allow-collisions` to take the most
recent report anyway.

## Managing submissions (ingest, update, delete)

Use the management script when you need to add, replace, or remove a submission record.

### Local (recommended first)

Ingest a new submission:

```bash
pixi run manage-submission -- \
  --action ingest \
  --report /path/to/moppy_batch_report.json \
  --model ACCESS-ESM1.6 \
  --experiment historical \
  --member r2i1p1f1
```

Update an existing submission:

```bash
pixi run manage-submission -- \
  --action update \
  --report /path/to/moppy_batch_report.json \
  --model ACCESS-ESM1.6 \
  --experiment historical \
  --member r2i1p1f1
```

`update` overwrites the existing `progress/<model>/<experiment>/<member>/cmorisation.json`.
If that submission does not exist yet, the command fails (it will not create a new record).

For a hard replace workflow, run `delete` first and then `ingest`.

Delete a submission:

```bash
# Remove entire member folder under progress/<model>/<experiment>/<member>/
pixi run manage-submission -- \
  --action delete \
  --model ACCESS-ESM1.6 \
  --experiment historical \
  --member r2i1p1f1 \
  --delete-scope member

# Or remove only progress/<model>/<experiment>/<member>/cmorisation.json
pixi run manage-submission -- \
  --action delete \
  --model ACCESS-ESM1.6 \
  --experiment historical \
  --member r2i1p1f1 \
  --delete-scope cmorisation
```

Then rebuild dashboard data:

```bash
pixi run compile-progress
```

### On GitHub (after local validation)

Run the workflow `.github/workflows/manage_submission.yml` from the Actions tab.

Inputs:

- `action`: `ingest`, `update`, or `delete`
- `model`, `experiment`, `member`
- `report_path`: preferred for `ingest` and `update` (path to a JSON file already committed in the repository)
- `report_url`: optional fallback for `ingest` and `update` (accessible HTTPS URL)
- `delete_scope`: `member` or `cmorisation` for delete

The workflow will:

1. apply the operation in `progress/`
2. rebuild `dashboard/progress.json`
3. create a branch and open a PR to `main`

This keeps review and auditability in the normal PR flow.

### Uploading report file on GitHub (no URL needed)

1. Create a small PR that adds your report JSON to a staging path in the repo, for example:
  - `reports/uploads/moppy_batch_report_20260730T022828Z.json`
2. Merge that PR.
3. Run the `Manage submission progress` workflow and set:
  - `action=ingest` (or `update`)
  - `report_path=reports/uploads/moppy_batch_report_20260730T022828Z.json`
  - `model`, `experiment`, `member`

This avoids external URLs entirely and keeps the source report versioned in Git history.

### Dispatch from command line with gh

You can dispatch the same workflow from your terminal using:

```bash
scripts/gh_manage_submission.sh \
  --action ingest \
  --model ACCESS-ESM1.6 \
  --experiment historical \
  --member r2i1p1f1 \
  --report-path reports/uploads/moppy_batch_report_20260730T022828Z.json
```

Update an existing submission:

```bash
scripts/gh_manage_submission.sh \
  --action update \
  --model ACCESS-ESM1.6 \
  --experiment historical \
  --member r2i1p1f1 \
  --report-path reports/uploads/moppy_batch_report_20260730T022828Z.json
```

This `update` action replaces the existing `cmorisation.json` for that model/experiment/member.
If you need to fully recreate the record, do `delete` then `ingest`.

Delete a submission record:

```bash
# Remove entire member record
scripts/gh_manage_submission.sh \
  --action delete \
  --model ACCESS-ESM1.6 \
  --experiment historical \
  --member r2i1p1f1 \
  --delete-scope member

# Or remove only cmorisation.json
scripts/gh_manage_submission.sh \
  --action delete \
  --model ACCESS-ESM1.6 \
  --experiment historical \
  --member r2i1p1f1 \
  --delete-scope cmorisation
```

Fallback to URL source for report file:

```bash
scripts/gh_manage_submission.sh \
  --action ingest \
  --model ACCESS-ESM1.6 \
  --experiment historical \
  --member r2i1p1f1 \
  --report-url https://example.org/path/to/moppy_batch_report.json
```

Notes:

- Requires `gh` to be installed and authenticated (`gh auth status`).
- The script dispatches `.github/workflows/manage_submission.yml` on `main` by default.
- Use `--ref` to target a different branch if needed.

### Run directly on Gadi (no Pixi required)

If your report file is on Gadi scratch, you can run everything in-place with plain Python:

```bash
# one-time setup in your clone
python -m pip install --user pyyaml jsonschema

# ingest/update/delete + compile dashboard/progress.json
scripts/gadi_manage_submission.sh \
  --action ingest \
  --report /scratch/path/to/moppy_batch_report.json \
  --model ACCESS-ESM1.6 \
  --experiment historical \
  --member r2i1p1f1
```

To also create and push a branch and open a PR from Gadi:

```bash
scripts/gadi_manage_submission.sh \
  --action update \
  --report /scratch/path/to/moppy_batch_report.json \
  --model ACCESS-ESM1.6 \
  --experiment historical \
  --member r2i1p1f1 \
  --create-pr
```

Delete examples:

```bash
# remove entire member record
scripts/gadi_manage_submission.sh \
  --action delete \
  --model ACCESS-ESM1.6 \
  --experiment historical \
  --member r2i1p1f1 \
  --delete-scope member

# remove only cmorisation.json
scripts/gadi_manage_submission.sh \
  --action delete \
  --model ACCESS-ESM1.6 \
  --experiment historical \
  --member r2i1p1f1 \
  --delete-scope cmorisation
```

## Updating publication status

Edit `progress/<model>/<experiment>/<member>/publication.json` directly.
The file follows `schemas/publication.schema.json`. Commit and push — the
dashboard updates on the next CI run.

## Local development

```bash
python scripts/validate_plans.py
python scripts/validate_qc.py
python scripts/compile_progress.py
cd dashboard && python -m http.server 8080
```

Dependencies: `pyyaml`, `jsonschema` (Python 3.10+).

### With Pixi

This repo now includes a [`pixi.toml`](/home/romain/PROJECTS/access-moppy-progress/pixi.toml:1) for a managed dev environment.

```bash
pixi run dev
```

That will:

1. validate `plans/*.yaml` and `progress/**/qc.json`
2. rebuild `dashboard/progress.json`
3. serve the dashboard at `http://localhost:8080`

Other handy commands:

```bash
pixi run validate-plans
pixi run validate-requests
pixi run compile-progress
pixi run manage-submission -- --help
scripts/gh_manage_submission.sh --help
scripts/gadi_manage_submission.sh --help
pixi run serve-dashboard
```

## Licence

MIT

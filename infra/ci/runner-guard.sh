#!/bin/bash
# Install outside the checkout and runner directory. Fail before any job steps.
set -eu
test "${GITHUB_REPOSITORY:-}" = GalimovKI/pentada-astr
case "${GITHUB_REF:-}" in
  refs/heads/main|refs/heads/dev) ;;
  *) echo 'This runner only accepts main/dev deployments.' >&2; exit 1 ;;
esac
test "${GITHUB_WORKFLOW_REF:-}" = "GalimovKI/pentada-astr/.github/workflows/ci-cd.yml@${GITHUB_REF}"
test "${GITHUB_JOB:-}" = deploy
case "${GITHUB_EVENT_NAME:-}" in
  push|workflow_dispatch) ;;
  *) echo 'This runner only accepts push/manual deployments.' >&2; exit 1 ;;
esac

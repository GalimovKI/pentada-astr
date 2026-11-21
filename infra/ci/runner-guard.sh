#!/bin/bash
# Install outside the checkout and runner directory. Fail before any job steps.
set -eu
test "${GITHUB_REPOSITORY:-}" = GalimovKI/pentada-astr
test "${GITHUB_REF:-}" = refs/heads/main
test "${GITHUB_WORKFLOW_REF:-}" = GalimovKI/pentada-astr/.github/workflows/ci-cd.yml@refs/heads/main
test "${GITHUB_JOB:-}" = deploy
case "${GITHUB_EVENT_NAME:-}" in
  push|workflow_dispatch) ;;
  *) echo 'This runner only accepts main deployments.' >&2; exit 1 ;;
esac

#!/usr/bin/env bash
# Deletes public applications nobody ever confirmed, and the CVs attached to
# them, once they are past the 30-day retention the privacy notice promises.
# Weekly is often enough: the promise is "within 30 days", not "on day 30".

source "$(dirname "$0")/_lib.sh"

run_command purge_pending_applications "$@"

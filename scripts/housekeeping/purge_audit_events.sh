#!/usr/bin/env bash
# Applies the audit log's 730-day retention. The log is append-only, so this
# is the only thing in the application that ever removes an entry.

source "$(dirname "$0")/_lib.sh"

run_command purge_audit_events "$@"

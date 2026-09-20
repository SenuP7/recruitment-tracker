#!/usr/bin/env bash
# Reverts delegation offers nobody answered within 48 hours of the interview,
# so the round goes back to the assigned interviewer while there is still time
# to act on it. Hourly, because a missed day means nobody turns up.

source "$(dirname "$0")/_lib.sh"

run_command expire_delegations "$@"

#!/usr/bin/env bash
# Shared setup for the Candidflow housekeeping jobs.
#
# cron runs with an almost empty environment: none of the Elastic Beanstalk
# environment properties are in it (DATABASE_URL, SECRET_KEY, the DB_* values),
# and the virtualenv is not on the path. Every housekeeping script sources this
# first so a scheduled run reaches the same database a request does.

set -uo pipefail

APP_DIR=${APP_DIR:-/var/app/current}
ENV_SNAPSHOT=${ENV_SNAPSHOT:-/opt/elasticbeanstalk/deployment/candidflow_env}
LOG_FILE=${LOG_FILE:-/var/log/candidflow-housekeeping.log}

exec >>"$LOG_FILE" 2>&1

job_name=$(basename "$0" .sh)

log() {
    echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $job_name: $*"
}

load_environment() {
    # Elastic Beanstalk writes the environment properties as plain KEY=value
    # lines. Read them rather than sourcing the file: a value containing a
    # space would otherwise be split off into a stray command.
    if [ ! -r "$ENV_SNAPSHOT" ]; then
        log "no environment snapshot at $ENV_SNAPSHOT -- deploy again to create it"
        return 1
    fi

    while IFS='=' read -r key value || [ -n "$key" ]; do
        case "$key" in
            ''|'#'*) continue ;;
        esac
        export "$key=$value"
    done <"$ENV_SNAPSHOT"
}

run_command() {
    load_environment || return 1

    local venv
    venv=$(echo /var/app/venv/*/bin/activate)
    if [ ! -r "$venv" ]; then
        log "no virtualenv under /var/app/venv -- is this an Elastic Beanstalk instance?"
        return 1
    fi

    # shellcheck disable=SC1090
    source "$venv"

    cd "$APP_DIR" || { log "cannot enter $APP_DIR"; return 1; }

    log "running manage.py $*"
    python manage.py "$@"
    local status=$?
    log "finished with exit status $status"
    return $status
}

#!/bin/bash
#
# To update record to request IP (only works for IPv4)
# curl -X PUT https://entrydns.net/records/modify/<TOKEN>
#
# To update record to explicit IP:
# curl -X PUT -d "ip=<IP>" https://entrydns.net/records/modify/<TOKEN>
#

[[ $1 = '--silent' ]] && SILENT=true || SILENT=false
LOGFILE="/tmp/entrydns.log"

function log {
    local output
    output="$(date +'%F %T'): $*"
    echo "$output" >> "$LOGFILE"
    if ! $SILENT; then
        echo "$output"
    fi
}

function perform_update {
    AUTHENTICATION_TOKEN=$(resolve_auth_token) || return 1

    log "Using auth token: $AUTHENTICATION_TOKEN"
    log "Sending update request"

    log curl -X PUT "https://entrydns.net/records/modify/$AUTHENTICATION_TOKEN"

    if res=$(curl --no-progress-meter -X PUT "https://entrydns.net/records/modify/$AUTHENTICATION_TOKEN" 2>&1); then
        log "Updated successfully with response: $res"
        return 0
    else
        log "Entrydns update failed: $res"
        log "Retrying once"
        if res=$(curl -v --no-progress-meter -X PUT "https://entrydns.net/records/modify/$AUTHENTICATION_TOKEN" 2>&1); then
            log "Second attempt successful: $res"
            return 0
        else
            log "Second attempt also failed: $res"
            return 1
        fi
    fi
}
function resolve_auth_token {
    local token_file="$HOME/.config/entrydns/authentication-token"
    if ! [ -f "$token_file" ]; then
        log "Authentication token file not found: $token_file"
        return 1
    fi
    cat "$token_file"
}

rm -f "$LOGFILE"

if ! perform_update; then
    mailx -s "Entrydns update failed" root < "$LOGFILE"
    exit 1
fi

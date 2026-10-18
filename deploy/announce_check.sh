#!/usr/bin/env bash
# Check the announcer's settings, or send a test message / show what it would do.
#   sudo bash deploy/announce_check.sh            validate announce.env and events.json
#   sudo bash deploy/announce_check.sh --dry-run  print what it would post right now, post nothing
#   sudo bash deploy/announce_check.sh --test     post one test message (delete it afterwards)
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "run with sudo"; exit 1; }
MODE=${1:---check}
VF=$(sed -n 's/^Environment=VOICE_FILE=//p' /etc/systemd/system/voice-live-announce.service.d/voice_file.conf 2>/dev/null || true)
set -a; . /etc/discord-voice-live/announce.env; set +a
export EVENTS_FILE=/etc/discord-voice-live/events.json VOICE_FILE=${VF:-/var/www/html/live/voice.json}
export STATE_DIRECTORY=$(mktemp -d)   # never touches the real announcement state
trap 'rm -rf "$STATE_DIRECTORY"' EXIT
python3 -B /usr/local/lib/discord-voice-live/voice_live_announce.py "$MODE"

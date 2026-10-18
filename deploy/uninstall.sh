#!/usr/bin/env bash
# Remove discord-voice-live and the announcer. Website cards fall back to scheduled times.
# Settings in /etc/discord-voice-live are kept unless you add --purge.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "run with sudo"; exit 1; }
OUTCONF=/etc/systemd/system/discord-voice-live.service.d/output.conf
OUT_DIR=$( [[ -f $OUTCONF ]] && sed -n 's/^ReadWritePaths=//p' "$OUTCONF" | head -1 || true)
for u in discord-voice-live voice-live-announce; do
  systemctl disable --now $u.timer 2>/dev/null || true
  rm -rf /etc/systemd/system/$u.service /etc/systemd/system/$u.timer /etc/systemd/system/$u.service.d
done
systemctl daemon-reload
rm -rf /usr/local/lib/discord-voice-live /var/lib/private/voice-live-announce /var/lib/voice-live-announce
if [[ -n "$OUT_DIR" ]]; then rm -f "$OUT_DIR/voice.json"; fi
userdel dvoice 2>/dev/null || true
if [[ "${1:-}" == "--purge" ]]; then rm -rf /etc/discord-voice-live; else echo "kept settings in /etc/discord-voice-live (use --purge to remove)"; fi
echo "UNINSTALL OK"

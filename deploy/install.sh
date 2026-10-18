#!/usr/bin/env bash
# Install or update discord-voice-live (and optionally the Discord announcer).
#
#   sudo bash deploy/install.sh /var/www/example/live              # head counts only
#   sudo bash deploy/install.sh /var/www/example/live --announce   # plus Discord announcements
#
# The folder is where your website serves voice.json from. On later runs you can leave it
# out to keep the current folder. Settings files in /etc/discord-voice-live are created from
# the examples only if they don't exist yet; existing ones are never overwritten.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "run with sudo: sudo bash $0 <public folder> [--announce]"; exit 1; }
cd "$(dirname "$0")/.."
ETC=/etc/discord-voice-live
LIB=/usr/local/lib/discord-voice-live
OUTCONF=/etc/systemd/system/discord-voice-live.service.d/output.conf
ANNCONF=/etc/systemd/system/voice-live-announce.service.d/voice_file.conf

OUT_DIR="" ANNOUNCE=no
for a in "$@"; do
  case "$a" in
    --announce) ANNOUNCE=yes ;;
    -*) echo "unknown option $a"; exit 1 ;;
    *) OUT_DIR=$a ;;
  esac
done
if [[ -z "$OUT_DIR" && -f $OUTCONF ]]; then
  OUT_DIR=$(sed -n 's/^ReadWritePaths=//p' "$OUTCONF" | head -1)
  echo "keeping the current folder: $OUT_DIR"
fi
[[ -n "$OUT_DIR" ]] || { echo "usage: sudo bash $0 /path/to/website/live [--announce]"; exit 1; }
[[ "$OUT_DIR" == /* && "$OUT_DIR" != *" "* && "$OUT_DIR" != *..* ]] || { echo "use an absolute path without spaces"; exit 1; }
OUT_DIR=${OUT_DIR%/}
[[ $ANNOUNCE == no && -f /etc/systemd/system/voice-live-announce.service ]] && ANNOUNCE=yes  # keep it updated
python3 -c 'import sys, zoneinfo; sys.exit(sys.version_info < (3, 9))' || { echo "Python 3.9 or newer is required"; exit 1; }

id dvoice >/dev/null 2>&1 || useradd --system --user-group --no-create-home --home-dir /nonexistent \
  --shell /usr/sbin/nologin dvoice
install -d -o root -g root -m 755 "$LIB" "$ETC"
install -o root -g root -m 755 discord_voice_live.py "$LIB/"
[[ -f $ETC/voice.env ]] || install -o root -g root -m 644 config/voice.env.example "$ETC/voice.env"
install -d -o dvoice -g dvoice -m 755 "$OUT_DIR"
install -o root -g root -m 644 systemd/discord-voice-live.service systemd/discord-voice-live.timer /etc/systemd/system/
install -d -m 755 "$(dirname $OUTCONF)"
printf '# Written by deploy/install.sh: where voice.json goes.\n[Service]\nEnvironment=VOICE_OUT=%s/voice.json\nReadWritePaths=%s\n' \
  "$OUT_DIR" "$OUT_DIR" > "$OUTCONF"

if [[ $ANNOUNCE == yes ]]; then
  install -o root -g root -m 755 voice_live_announce.py "$LIB/"
  [[ -f $ETC/announce.env ]] || install -o root -g root -m 600 config/announce.env.example "$ETC/announce.env"
  [[ -f $ETC/events.json ]] || install -o root -g root -m 644 config/events.json.example "$ETC/events.json"
  install -o root -g root -m 644 systemd/voice-live-announce.service systemd/voice-live-announce.timer /etc/systemd/system/
  install -d -m 755 "$(dirname $ANNCONF)"
  printf '# Written by deploy/install.sh: the voice.json to read.\n[Service]\nEnvironment=VOICE_FILE=%s/voice.json\n' \
    "$OUT_DIR" > "$ANNCONF"
fi
systemctl daemon-reload

if grep -q '^VOICE_GUILD_ID=0*$' "$ETC/voice.env"; then
  echo
  echo "Next: put your server ID and voice channels in $ETC/voice.env, then run:"
  echo "  sudo systemctl enable --now discord-voice-live.timer"
else
  systemctl start discord-voice-live.service || true
  journalctl -u discord-voice-live.service -n 2 --no-pager -o cat || true
  systemctl enable --now discord-voice-live.timer
fi
if [[ $ANNOUNCE == yes ]]; then
  if grep -q 'REPLACE_ME' "$ETC/announce.env"; then
    echo
    echo "Announcer installed but not started. Next:"
    echo "  1. put your webhook URL in $ETC/announce.env and your events in $ETC/events.json"
    echo "  2. check them: sudo bash $(pwd)/deploy/announce_check.sh"
    echo "  3. sudo systemctl enable --now voice-live-announce.timer"
  else
    systemctl enable --now voice-live-announce.timer
  fi
fi
echo "INSTALL OK: $OUT_DIR/voice.json"

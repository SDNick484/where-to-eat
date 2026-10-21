#!/bin/sh
# Where to Eat (lunch list) installer for Alpine Linux (OpenRC) — CT 210, next to Cookbooks / Dinner Log /
# the wish list / Roasted. Build with installer/build.sh.
# Re-runnable: upgrades the app in place; never touches existing data, and only *adds*
# missing settings to existing config files.
#
#   sh setup-lunch.sh               install / upgrade
#   LUNCH_PORT=8769 sh setup-lunch.sh
#   sh setup-lunch.sh --uninstall   remove app + service (keeps /var/lib/lunch and backups)
set -eu
APP_DIR=/opt/lunch
DATA_DIR=/var/lib/lunch
CONF=/etc/conf.d/lunch
OPS_CONF=/etc/conf.d/ct210-ops
SVC_USER=lunch
PORT="${LUNCH_PORT:-8769}"
HOST=lunch.nickandrade.com

if [ "$(id -u)" != 0 ]; then echo "Run as root"; exit 1; fi
command -v apk >/dev/null || { echo "This installer is for Alpine (apk)."; exit 1; }

if [ "${1:-}" = "--uninstall" ]; then
  rc-service lunch stop 2>/dev/null || true
  rc-update del lunch default 2>/dev/null || true
  rm -f /etc/init.d/lunch /etc/periodic/daily/lunch-backup
  rm -rf "$APP_DIR"
  echo "Removed app, service and backup job. Data kept in $DATA_DIR, config in $CONF, backups in /var/backups/ct210."
  exit 0
fi

# an existing install keeps its port
[ -f "$CONF" ] && PORT=$(sed -n 's/^PORT=//p' "$CONF" | head -n1) && PORT=${PORT:-8769}

echo "==> Installing packages"
apk add --no-cache python3 py3-flask py3-gunicorn py3-pillow py3-jwt py3-cryptography sqlite >/dev/null

[ -x /etc/init.d/lunch ] && rc-service lunch stop >/dev/null 2>&1 || true
if netstat -ltn 2>/dev/null | awk '{print $4}' | grep -q ":$PORT\$"; then
  echo "Port $PORT is already in use by something else. Re-run with LUNCH_PORT=<free port>."; exit 1
fi

echo "==> Creating user and folders"
# BusyBox adduser -S puts a new user in "nogroup" unless told otherwise, so make the app's own group first.
grep -q "^$SVC_USER:" /etc/group || addgroup -S "$SVC_USER"
if ! id "$SVC_USER" >/dev/null 2>&1; then
  adduser -S -D -H -h "$DATA_DIR" -s /sbin/nologin -G "$SVC_USER" "$SVC_USER"
fi
mkdir -p "$APP_DIR" "$DATA_DIR/photos" /var/backups/ct210

echo "==> Unpacking app"
TMP=$(mktemp -d)
sed -n '/^__PAYLOAD_BELOW__$/,$p' "$0" | tail -n +2 | base64 -d | tar xz -C "$TMP"
rm -rf "$APP_DIR.new" && mv "$TMP/lunch" "$APP_DIR.new"
rm -rf "$APP_DIR.old"; [ -d "$APP_DIR" ] && mv "$APP_DIR" "$APP_DIR.old"
mv "$APP_DIR.new" "$APP_DIR"; rm -rf "$APP_DIR.old" "$TMP"
chown -R root:root "$APP_DIR"
chown -R "$SVC_USER:$SVC_USER" "$DATA_DIR"
chmod 750 "$DATA_DIR"

# ---------------------------------------------------------------- config
add_setting() {  # add_setting FILE KEY VALUE COMMENT — only if KEY isn't there yet
  grep -q "^$2=" "$1" 2>/dev/null && return 0
  printf '\n# %s\n%s=%s\n' "$4" "$2" "$3" >> "$1"
  ADDED="${ADDED:-} $2"
}
from_siblings() {  # a value already set for Cookbooks or Roasted, so it isn't typed twice
  for f in /etc/conf.d/cookbooks /etc/conf.d/roasted; do
    v=$(sed -n "s/^$1=//p" "$f" 2>/dev/null | head -n1)
    [ -n "$v" ] && { echo "$v"; return; }
  done
}

if [ ! -f "$CONF" ]; then
  echo "==> Writing $CONF"
  cat > "$CONF" <<EOF
# Where to Eat (lunch) configuration — after editing: rc-service lunch restart
PORT=$PORT
DATA_DIR=$DATA_DIR
EOF
fi
add_setting "$CONF" CF_TEAM_DOMAIN "$(from_siblings CF_TEAM_DOMAIN)" "Cloudflare Access team domain, e.g. yourteam.cloudflareaccess.com"
add_setting "$CONF" CF_AUD "" "AUD tag of the Lunch Access application (path: admin)"
add_setting "$CONF" ADMIN_EMAILS "$(from_siblings ADMIN_EMAILS)" "Only these emails may edit (comma separated); empty = anyone the Access policy lets in"
add_setting "$CONF" LAN_EDIT 1 "1 = direct LAN requests (not through Cloudflare) may edit"
add_setting "$CONF" PUBLIC_VIEW 1 "1 = anyone can browse places, deals and the map at /; 0 = everything behind /admin"
add_setting "$CONF" AREAS '"Concord|37.9780|-122.0311;San Francisco|37.7749|-122.4194"' \
  "Areas for the filter chips and map buttons: name|lat|lng separated by ;"
add_setting "$CONF" CHEAP_UNDER 15 "Dishes at or under this many dollars are highlighted as cheap"
add_setting "$CONF" ANTHROPIC_API_KEY "$(from_siblings ANTHROPIC_API_KEY)" "Claude API key for reading menu photos (console.anthropic.com)"
add_setting "$CONF" ANTHROPIC_MODEL claude-sonnet-5-5 "Model used for menu reading"
chmod 640 "$CONF"; chown root:"$SVC_USER" "$CONF"

# health checks: add Lunch to the CT 210 list that app-health reads from ct210-ops
LINE="Lunch|http://127.0.0.1:$PORT/healthz|lunch"
if [ -f "$OPS_CONF" ] && ! grep -q '^HEALTH_CHECKS=' "$OPS_CONF"; then
  cat >> "$OPS_CONF" <<EOF

# Apps checked every 15 min (name|url|service); apps that aren't installed are skipped
HEALTH_CHECKS="Cookbooks|http://127.0.0.1:8767/healthz|cookbooks
Dinner Log|http://127.0.0.1:8765/|dinner-log
Wish list|http://127.0.0.1:8766/healthz|wishlist
Roasted|http://127.0.0.1:8768/healthz|roasted
$LINE"
EOF
  HC=added
elif [ -f "$OPS_CONF" ] && ! grep -q '|lunch"\?[[:space:]]*$' "$OPS_CONF"; then
  # append our line inside the existing quoted list (it may span several lines)
  cp "$OPS_CONF" "$OPS_CONF.bak"
  awk -v line="$LINE" '
    !done && /^HEALTH_CHECKS="/ { inb = 1; rest = substr($0, length("HEALTH_CHECKS=\"") + 1)
      if (rest ~ /"[[:space:]]*$/) { sub(/"[[:space:]]*$/, ""); print; print line "\""; done = 1; inb = 0 } else print
      next }
    inb && !done && /"[[:space:]]*$/ { sub(/"[[:space:]]*$/, ""); if ($0 != "") print; print line "\""; done = 1; inb = 0; next }
    { print }' "$OPS_CONF.bak" > "$OPS_CONF"
  if grep -q "|lunch\"" "$OPS_CONF"; then HC=added; rm -f "$OPS_CONF.bak"; else mv "$OPS_CONF.bak" "$OPS_CONF"; HC=manual; fi
fi

# ---------------------------------------------------------------- service
cat > /etc/init.d/lunch <<'EOF'
#!/sbin/openrc-run
name="lunch"
description="Where to Eat (lunch list)"
: ${PORT:=8769}
: ${DATA_DIR:=/var/lib/lunch}
export HOME=/var/lib/lunch  # newer gunicorn keeps a small control socket under $HOME
export PORT DATA_DIR CF_TEAM_DOMAIN CF_AUD ADMIN_EMAILS LAN_EDIT PUBLIC_VIEW AREAS CHEAP_UNDER ANTHROPIC_API_KEY ANTHROPIC_MODEL
supervisor="supervise-daemon"
respawn_delay=5
respawn_max=10
respawn_period=600
command="/usr/bin/gunicorn"
command_args="--preload --workers 2 --threads 4 --timeout 180 --bind 0.0.0.0:${PORT} --chdir /opt/lunch --access-logfile /var/log/lunch.log --error-logfile /var/log/lunch.log app:app"
command_user="lunch"
depend() { need net; after firewall; }
start_pre() { checkpath -f -o lunch /var/log/lunch.log; }
EOF
chmod +x /etc/init.d/lunch

# ---------------------------------------------------------------- backups
echo "==> Installing nightly backup"
mkdir -p /etc/periodic/daily
install -m 755 "$APP_DIR/ops/lunch-backup" /etc/periodic/daily/lunch-backup
rc-update add crond default >/dev/null 2>&1 || true
rc-service crond start >/dev/null 2>&1 || true

echo "==> Starting service"
rc-update add lunch default >/dev/null 2>&1 || true
rc-service lunch start
i=0
until wget -qO- "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1; do
  i=$((i+1)); [ $i -gt 25 ] && { echo "Service didn't come up; see /var/log/lunch.log"; tail -n 20 /var/log/lunch.log; exit 1; }
  sleep 1
done

echo "==> Taking a first backup"
/etc/periodic/daily/lunch-backup || echo "    (backup reported a problem; see /var/log/ct210-ops.log)"

IP=$(ip -4 -o addr show scope global | awk '{print $4}' | cut -d/ -f1 | head -n1)
echo
echo "Where to Eat is running:  http://$IP:$PORT/        (editing on the LAN: http://$IP:$PORT/admin)"
echo "Health: $(wget -qO- http://127.0.0.1:$PORT/healthz | tr -d '\n ')"
[ -n "${ADDED:-}" ] && echo "New settings added:${ADDED}"
grep -q '^ANTHROPIC_API_KEY=$' "$CONF" && echo "  - Menu reading is off until you set ANTHROPIC_API_KEY in $CONF"
grep -q '^CF_AUD=$' "$CONF" && echo "  - Set CF_AUD in $CONF after creating the Access app for $HOST/admin"
grep -q '^ADMIN_EMAILS=$' "$CONF" && echo "  - ADMIN_EMAILS is empty: anyone your Access policy lets in can edit"
[ "${HC:-}" = added ] && echo "  - Added Lunch to HEALTH_CHECKS in $OPS_CONF"
[ "${HC:-}" = manual ] && echo "  - Couldn't edit HEALTH_CHECKS in $OPS_CONF: add the line  $LINE"
[ -f "$OPS_CONF" ] || echo "  - No $OPS_CONF (Cookbooks' ops jobs): backups still run nightly into /var/backups/ct210"
echo "  - Tunnel: $HOST -> http://$IP:$PORT"
echo "Config: $CONF   Data: $DATA_DIR   Logs: /var/log/lunch.log, /var/log/ct210-ops.log"
exit 0

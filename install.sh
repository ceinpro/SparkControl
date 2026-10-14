#!/usr/bin/env bash
set -euo pipefail
if [[ ${EUID} -ne 0 ]]; then
  echo 'Ejecuta: sudo bash install.sh ceinpro' >&2
  exit 1
fi
SPARK_USER="${1:-ceinpro}"
id "$SPARK_USER" >/dev/null
SPARK_GROUP="$(id -gn "$SPARK_USER")"
SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
command -v python3 >/dev/null
command -v systemctl >/dev/null
command -v docker >/dev/null
command -v sudo >/dev/null
command -v visudo >/dev/null
# Check the catalog before installing, reusing an existing catalog on updates.
CATALOG_SOURCE="$SOURCE_DIR/catalog.json"
if [[ -f /etc/spark-control/catalog.json ]]; then
  CATALOG_SOURCE=/etc/spark-control/catalog.json
fi
/usr/bin/python3 - "$SOURCE_DIR" "$CATALOG_SOURCE" <<'PY'
import os, sys
sys.path.insert(0,sys.argv[1])
from core import load, health
cfg=load(sys.argv[2])
for p in cfg['profiles']:
    if not os.path.isdir(p['cwd']): raise SystemExit('No existe la carpeta: '+p['cwd'])
    executable=p['command'][0]
    if os.path.isabs(executable) and not os.access(executable,os.X_OK):
        raise SystemExit('No existe o no es ejecutable: '+executable)
    if health(p):
        raise SystemExit('Detén primero '+p['name']+'; su API sigue respondiendo. No se ha instalado nada.')
PY
runuser -u "$SPARK_USER" -- docker info >/dev/null
# Only panel-owned paths and unit names are modified.
install -d -m 755 /opt/spark-control /etc/spark-control
systemctl stop spark-panel.service 2>/dev/null || true
for f in core.py ctl.py runner.py server.py index.html; do
  install -o root -g root -m 644 "$SOURCE_DIR/$f" "/opt/spark-control/$f"
done
if [[ ! -f /etc/spark-control/catalog.json ]]; then
  install -o root -g root -m 644 "$SOURCE_DIR/catalog.json" /etc/spark-control/catalog.json
fi
# Root-owned catalog cannot be modified through the web panel.
chown root:root /etc/spark-control/catalog.json
chmod 644 /etc/spark-control/catalog.json
if [[ ! -f /etc/spark-control/panel.token ]]; then
  /usr/bin/python3 -c 'import secrets; print(secrets.token_urlsafe(24))' > /etc/spark-control/panel.token
fi
chown "root:$SPARK_GROUP" /etc/spark-control/panel.token
chmod 640 /etc/spark-control/panel.token
cat > /usr/local/bin/sparkctl <<'EOF'
#!/bin/sh
exec /usr/bin/python3 -E -s /opt/spark-control/ctl.py "$@"
EOF
chown root:root /usr/local/bin/sparkctl
chmod 755 /usr/local/bin/sparkctl
SUDO_TMP="$(mktemp)"
trap 'rm -f "$SUDO_TMP"' EXIT
printf '%s ALL=(root) NOPASSWD: /usr/local/bin/sparkctl\n' "$SPARK_USER" > "$SUDO_TMP"
visudo -cf "$SUDO_TMP" >/dev/null
install -o root -g root -m 440 "$SUDO_TMP" /etc/sudoers.d/spark-control
/usr/bin/python3 - "$SPARK_USER" <<'PY'
import json,sys
from pathlib import Path
cfg=json.loads(Path('/etc/spark-control/catalog.json').read_text())
user=sys.argv[1]
# Each instance conflicts with every other managed profile. systemd waits for
# stop jobs, including ExecStopPost container cleanup, before starting a peer.
for p in cfg['profiles']:
    others=' '.join('spark-app@'+q['id']+'.service' for q in cfg['profiles'] if q['id']!=p['id'])
    directory=Path('/etc/systemd/system/spark-app@'+p['id']+'.service.d')
    directory.mkdir(parents=True,exist_ok=True)
    (directory/'exclusive.conf').write_text('[Unit]\nConflicts='+others+'\n')
Path('/etc/systemd/system/spark-app@.service').write_text(f'''[Unit]
Description=Spark application profile %i
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=simple
User={user}
WorkingDirectory=/opt/spark-control
ExecStart=/usr/bin/python3 -E -s /opt/spark-control/runner.py %i
ExecStopPost=/usr/bin/python3 -E -s /opt/spark-control/runner.py --cleanup %i
KillMode=control-group
TimeoutStopSec=90
Restart=no
StandardOutput=journal
StandardError=journal
''')
Path('/etc/systemd/system/spark-panel.service').write_text(f'''[Unit]
Description=Spark application control panel
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User={user}
WorkingDirectory=/opt/spark-control
Environment=SPARK_PANEL_HOST=0.0.0.0
Environment=SPARK_PANEL_PORT=8090
ExecStart=/usr/bin/python3 -E -s /opt/spark-control/server.py
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
''')
PY
systemctl daemon-reload
systemctl enable --now spark-panel.service
systemctl is-active --quiet spark-panel.service
printf '\nInstalado. Abre http://192.168.30.70:8090\n'
printf 'Contraseña: '
cat /etc/spark-control/panel.token
printf '\nNinguna aplicación se inicia automáticamente.\n'

#!/usr/bin/env bash
set -euo pipefail
set +x

if [[ "${1:-}" != "--apply" ]]; then
  echo 'No certificate request or app activation made. Re-run with --apply only after deployment approval and DNS verification.'
  exit 0
fi
for name in AWS_DEFAULT_REGION PUBLIC_HOSTNAME PUBLIC_IP APP_ORIGIN; do
  [[ -n "${!name:-}" ]] || { printf 'Required setting is missing: %s\n' "$name" >&2; exit 2; }
done
[[ "$(id -u)" -eq 0 ]] || { echo 'Run as root.' >&2; exit 2; }
[[ "$APP_ORIGIN" == "https://$PUBLIC_HOSTNAME" ]] || { echo 'APP_ORIGIN must match the exact HTTPS hostname.' >&2; exit 2; }

PUBLIC_HOSTNAME="$PUBLIC_HOSTNAME" PUBLIC_IP="$PUBLIC_IP" python3 - <<'PY'
import os
import socket

host = os.environ["PUBLIC_HOSTNAME"]
expected = os.environ["PUBLIC_IP"]
addresses = {item[4][0] for item in socket.getaddrinfo(host, 80, type=socket.SOCK_STREAM)}
if expected not in addresses:
    raise SystemExit("Public DNS does not yet resolve to the approved EC2 address.")
PY

if ! command -v certbot >/dev/null; then
  dnf install -y certbot
fi
install -d -m 0755 /var/www/certbot
certbot certonly --webroot -w /var/www/certbot \
  --domain "$PUBLIC_HOSTNAME" \
  --non-interactive --agree-tos --register-unsafely-without-email

sed "s/INF2006_HOSTNAME/$PUBLIC_HOSTNAME/g" \
  /opt/inf2006/src/infra/nginx/inf2006-https.conf \
  > /etc/nginx/conf.d/inf2006.conf.tmp
install -m 0644 /etc/nginx/conf.d/inf2006.conf.tmp /etc/nginx/conf.d/inf2006.conf
rm -f /etc/nginx/conf.d/inf2006.conf.tmp
nginx -t
systemctl reload nginx

cat > /usr/local/sbin/inf2006-certbot-renew.sh <<'RENEW'
#!/usr/bin/env bash
set -euo pipefail
/usr/bin/certbot renew --quiet --deploy-hook 'systemctl reload nginx'
RENEW
chmod 0750 /usr/local/sbin/inf2006-certbot-renew.sh
cat > /etc/systemd/system/inf2006-certbot-renew.service <<'UNIT'
[Unit]
Description=Renew the INF2006 HTTPS certificate
After=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/inf2006-certbot-renew.sh
UNIT
cat > /etc/systemd/system/inf2006-certbot-renew.timer <<'UNIT'
[Unit]
Description=Daily INF2006 HTTPS certificate renewal check

[Timer]
OnCalendar=daily
RandomizedDelaySec=6h
Persistent=true

[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
systemctl enable --now inf2006-certbot-renew.timer

docker compose --env-file /etc/inf2006/compose.env \
  -f /opt/inf2006/compose.cloud.yml up -d --wait
cat > /etc/systemd/system/inf2006-health-metric.service <<'UNIT'
[Unit]
Description=Publish INF2006 /health/ready to CloudWatch
After=docker.service

[Service]
Type=oneshot
EnvironmentFile=/etc/inf2006/stack.env
ExecStart=/opt/inf2006/src/infra/scripts/publish-health-metric.sh
UNIT
cat > /etc/systemd/system/inf2006-health-metric.timer <<'UNIT'
[Unit]
Description=Publish INF2006 readiness to CloudWatch every minute

[Timer]
OnBootSec=1min
OnUnitActiveSec=1min
Persistent=true

[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
systemctl enable --now inf2006-health-metric.timer
printf 'HTTPS is active for %s; verify health and real Google sign-in separately.\n' "$PUBLIC_HOSTNAME"

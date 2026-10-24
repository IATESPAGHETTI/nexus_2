#!/bin/sh
# Start-up for the single-container (Hugging Face Space) build.
set -e
mkdir -p /app/run
if [ -n "$DASHBOARD_PASSWORD" ]; then
  printf '%s:%s\n' "${DASHBOARD_USER:-nexus}" "$(openssl passwd -apr1 "$DASHBOARD_PASSWORD")" > /app/run/htpasswd
  printf 'auth_basic "NEXUS";\nauth_basic_user_file /app/run/htpasswd;\n' > /app/run/auth.conf
  echo "dashboard: basic auth ENABLED"
else
  printf 'auth_basic off;\n' > /app/run/auth.conf
  echo "dashboard: WARNING basic auth is OFF (set the DASHBOARD_PASSWORD secret before sharing the URL)"
fi
# the approver token is attached by nginx, server-side
printf 'set $approver_token "%s";\n' "${NEXUS_APPROVER_TOKEN:-}" > /app/run/token.conf
exec /usr/bin/supervisord -n -c /app/deploy/space/supervisord.conf

#!/bin/sh
# Writes the nginx auth include. With DASHBOARD_PASSWORD set the whole site (including the approval buttons)
# needs HTTP basic auth; with it empty auth is off, which is only acceptable for local use.
set -e
if [ -n "$DASHBOARD_PASSWORD" ]; then
  printf '%s:%s\n' "${DASHBOARD_USER:-nexus}" "$(openssl passwd -apr1 "$DASHBOARD_PASSWORD")" > /etc/nginx/.htpasswd
  printf 'auth_basic "NEXUS";\nauth_basic_user_file /etc/nginx/.htpasswd;\n' > /etc/nginx/auth.conf
  echo "dashboard: basic auth ENABLED"
else
  printf 'auth_basic off;\n' > /etc/nginx/auth.conf
  echo "dashboard: WARNING basic auth is OFF (set DASHBOARD_PASSWORD before exposing this to the internet)"
fi

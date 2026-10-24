#!/bin/sh
# Creates .env for a public deployment: random tokens + a random dashboard password, and asks for the DeepSeek key
# WITHOUT echoing it. Run on the VM from the repository root:  sh deploy/azure/make_env.sh <public-host-name>
set -e
HOST="${1:?usage: make_env.sh <public-host-name e.g. nexus-me.centralindia.cloudapp.azure.com>}"
[ -e .env ] && { echo ".env already exists; move it away first"; exit 1; }
printf "DeepSeek API key (input hidden): "; stty -echo; read KEY; stty echo; echo
PW=$(openssl rand -base64 18 | tr -d '/+=' | cut -c1-20)
umask 077
cat > .env <<ENVEOF
DEEPSEEK_API_KEY=$KEY
DASHBOARD_USER=nexus
DASHBOARD_PASSWORD=$PW
NEXUS_APPROVER_TOKEN=$(openssl rand -hex 24)
NEXUS_INTERNAL_TOKEN=$(openssl rand -hex 24)
DASHBOARD_BIND=127.0.0.1
DOMAIN=$HOST
ENVEOF
echo ".env written (mode 600). Dashboard login -> user: nexus  password: $PW   (shown once; it is also in .env)"

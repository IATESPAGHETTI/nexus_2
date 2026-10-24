#!/bin/sh
# Health check for the running stack (run on the VM). Exit code 0 = healthy, 1 = something is wrong; prints what.
#   sh deploy/azure/healthcheck.sh
# Cron example (every 5 minutes; restarts what is down and logs it):
#   */5 * * * * sh $HOME/nexus/deploy/azure/healthcheck.sh --fix >> $HOME/healthcheck.log 2>&1
set -u
FIX=0; [ "${1:-}" = "--fix" ] && FIX=1
cd "$(dirname "$0")/../.."
COMPOSE="docker compose -f docker-compose.yml -f docker-compose.tls.yml"
BAD=0

STATUS=$(curl -s -m 8 http://127.0.0.1:8000/demo/status || true)
case "$STATUS" in
  *'"agents_reachable_count":7'*'"production_reachable":true'*|*'"production_reachable":true'*'"agents_reachable_count":7'*) echo "OK   status: shop reachable, 7/7 agents" ;;
  *) echo "FAIL status: ${STATUS:-no answer from the backend}"; BAD=1 ;;
esac

DOWN=$($COMPOSE ps --format '{{.Service}} {{.State}}' | awk '$2 != "running" {print $1}')
if [ -n "$DOWN" ]; then echo "FAIL containers not running: $DOWN"; BAD=1; fi

DISK=$(df -P / | awk 'NR==2 {gsub("%","",$5); print $5}')
[ "$DISK" -ge 90 ] && { echo "FAIL disk ${DISK}% full"; BAD=1; } || echo "OK   disk ${DISK}% used"

if [ "$BAD" -eq 1 ] && [ "$FIX" -eq 1 ]; then
  echo "restarting the stack"
  $COMPOSE up -d
fi
exit $BAD

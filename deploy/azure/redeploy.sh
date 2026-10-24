#!/bin/sh
# One-command redeploy from your own computer: pulls the branch on the VM and rebuilds only what changed.
#   sh deploy/azure/redeploy.sh [resource-group] [vm-name] [git-branch]
# Uses `az vm run-command` (no SSH key and no open SSH port needed; you only need `az login`). The VM must be running.
set -eu
RG="${1:-nexus-rg}"
VM="${2:-nexus-vm}"
BRANCH="${3:-claude/project-review-requirements-dfdda7}"

STATE=$(az vm show -d -g "$RG" -n "$VM" --query powerState -o tsv)
[ "$STATE" = "VM running" ] || { echo "VM is '$STATE'. Start it first: az vm start -g $RG -n $VM"; exit 1; }

SCRIPT="set -e; cd /home/azureuser/nexus; git fetch origin; git checkout $BRANCH; git pull --ff-only origin $BRANCH; \
docker compose -f docker-compose.yml -f docker-compose.tls.yml up -d --build 2>&1 | tail -n 15; \
docker compose -f docker-compose.yml -f docker-compose.tls.yml ps --format 'table {{.Service}}\t{{.Status}}'"

az vm run-command invoke -g "$RG" -n "$VM" --command-id RunShellScript --scripts "sudo -u azureuser bash -lc '$SCRIPT'" \
  --query "value[0].message" -o tsv

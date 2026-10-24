#!/bin/sh
# Reproducible creation of the NEXUS VM on Azure for Students (run in Cloud Shell or any shell with `az` logged in).
#   sh deploy/azure/create_vm.sh [resource-group] [region]
# It tries several VM sizes with >= 8 GB RAM (student subscriptions often lack capacity for any single one), opens ports 80 and 443 only,
# gives the public IP a DNS name, and prints the address. Nothing is created twice: an existing group/VM is reused.
# The region must be one your subscription's policy allows (see deploy/AZURE.md step 1; ours allowed centralindia).
set -eu
RG="${1:-nexus-rg}"
LOC="${2:-centralindia}"
NAME="${NEXUS_VM_NAME:-nexus-vm}"
SIZES="${NEXUS_VM_SIZES:-Standard_D2s_v3 Standard_D2as_v5 Standard_D2s_v5 Standard_B2as_v2 Standard_B2ms}"

az group create -n "$RG" -l "$LOC" -o none
if az vm show -g "$RG" -n "$NAME" -o none 2>/dev/null; then
  echo "VM $NAME already exists in $RG; reusing it."
else
  DNS="nexus-$(date +%s | tail -c 6)"
  for S in $SIZES; do
    echo "== trying $S"
    if az vm create -g "$RG" -n "$NAME" --image Ubuntu2204 --size "$S" --admin-username azureuser --generate-ssh-keys \
         --public-ip-sku Standard --public-ip-address-dns-name "$DNS" --os-disk-size-gb 40 -o none 2>/tmp/azvm.err; then
      echo "created with $S"
      break
    fi
    grep -E "Code:|Message:" /tmp/azvm.err | head -n 2 || true
  done
  az vm show -g "$RG" -n "$NAME" -o none || { echo "no size worked; try another region or sizes (NEXUS_VM_SIZES)"; exit 1; }
fi
az vm open-port -g "$RG" -n "$NAME" --port 80  --priority 1010 -o none 2>/dev/null || true
az vm open-port -g "$RG" -n "$NAME" --port 443 --priority 1020 -o none 2>/dev/null || true
az vm show -d -g "$RG" -n "$NAME" --query "{size:hardwareProfile.vmSize, ip:publicIps, dns:fqdns, state:powerState}" -o table
echo "Next: SSH in, install Docker, clone the repo and run deploy/azure/make_env.sh (see deploy/AZURE.md)."

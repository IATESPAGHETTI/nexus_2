# Deploy NEXUS on Azure for Students (no credit card)

One Ubuntu VM runs the whole Docker Compose stack; Caddy adds HTTPS with a free certificate. Use **Azure Cloud Shell**
(the `>_` button at the top of portal.azure.com, choose Bash): the Azure CLI is already installed there and you are already logged in.

Cost guide: a 2 vCPU / 8 GB VM is about $60-70 a month while running. Your ~$100 student credit therefore lasts several weeks
**if you stop the VM when you are not using it** (step 7). A stopped (deallocated) VM costs almost nothing but its disk.

## 1. Pick a region and size the subscription allows

Student subscriptions only allow some regions and sizes. Try a region close to you; if a command says a size/region is not allowed, try the next.

```bash
az account show --query "{name:name, state:state}" -o table
az vm list-skus --location centralindia --size Standard_B2 --query "[?restrictions==\`[]\`].name" -o tsv
```

Use `Standard_B2ms` (2 vCPU, 8 GB) if it is listed; `Standard_B2s` (4 GB) also works if you add swap (step 3). Other regions to try:
`southeastasia`, `eastasia`, `uksouth`, `westeurope`, `eastus`.

## 2. Create the VM and open ports 80/443 (Cloud Shell)

```bash
RG=nexus-rg; LOC=centralindia; NAME=nexus-vm; DNS=nexus-$RANDOM     # note the DNS name it prints
az group create -n $RG -l $LOC
az vm create -g $RG -n $NAME --image Ubuntu2204 --size Standard_B2ms \
  --admin-username azureuser --generate-ssh-keys --public-ip-sku Standard \
  --public-ip-address-dns-name $DNS --os-disk-size-gb 40
az vm open-port -g $RG -n $NAME --port 80  --priority 1010
az vm open-port -g $RG -n $NAME --port 443 --priority 1020
echo "Your address: $DNS.$LOC.cloudapp.azure.com"
```

(Port 22 for SSH is opened by default. Do not open any other port: only the dashboard should be reachable.)

## 3. Install Docker on the VM

```bash
az ssh vm -g $RG -n $NAME --local-user azureuser 2>/dev/null || ssh azureuser@$DNS.$LOC.cloudapp.azure.com
# --- now on the VM ---
curl -fsSL https://get.docker.com | sudo sh && sudo usermod -aG docker azureuser && newgrp docker
# only if the VM has 4 GB:  sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
```

## 4. Get the code and create the settings

```bash
git clone <URL of your repository> nexus && cd nexus
git checkout claude/project-review-requirements-dfdda7        # or your merged branch
sh deploy/azure/make_env.sh <DNS>.<LOC>.cloudapp.azure.com      # asks for the DeepSeek key (hidden); prints the dashboard password once
```

Never paste the key into a file you commit; `.env` is git-ignored and written with mode 600.

## 5. Start it

```bash
docker compose -f docker-compose.yml -f docker-compose.tls.yml up -d --build      # first build ~10-15 min
docker compose ps                                                                  # all services "running"/"healthy"
```

Open `https://<DNS>.<LOC>.cloudapp.azure.com`, log in as `nexus` with the printed password, turn the agents ON (they are always on in
this deployment; the switch only shows status), and press **Inject**.

CrewAI critic variant: add `CRITIC_URL=http://crewai-critic:8106` and `NEXUS_CRITIC_FRAMEWORK=crewai` to `.env`, then add `--profile crewai` to the command.

## 6. Check it really works (what to show your reviewer)

```bash
docker compose ps
docker compose logs --tail=20 orchestrator
curl -s -u nexus:<password> https://<DNS>.<LOC>.cloudapp.azure.com/api/demo/status      # 7 of 7 agents reachable
```

On the incident page, the **Audit trail & provenance** panel shows the trace id each agent received (same id for ADK and CrewAI agents).

## 7. Save your credit

```bash
az vm deallocate -g nexus-rg -n nexus-vm      # stop paying for compute (keeps disk + data); start again with: az vm start ...
# when you are completely done:  az group delete -n nexus-rg --yes
```

The public IP stays the same only if you keep the VM allocated; the DNS name follows the IP, so after a restart check the address with
`az vm show -d -g nexus-rg -n nexus-vm --query publicIps -o tsv`.

## Troubleshooting

- *"SkuNotAvailable / not allowed in this subscription"*: choose another region or size (step 1).
- *HTTPS certificate fails*: ports 80 and 443 must be open and `DOMAIN` must be the exact VM DNS name; `docker compose logs caddy`.
- *Out of memory (containers restarting)*: use the 8 GB size or add swap; `docker stats`.
- *Investigation never starts*: `docker compose logs orchestrator backend`; verify `DEEPSEEK_API_KEY` is set in `.env`
  and re-create with `docker compose up -d --force-recreate`.
- Security: the dashboard password protects the **Approve** buttons. Keep `.env` private and rotate the DeepSeek key if it ever leaks.

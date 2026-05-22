# opensre Azure Integration

This document describes everything added to opensre to support Azure Monitor Workspace (AMW) alerting, AKS cluster inspection, and Discord delivery — all changes are additive and do not modify existing behaviour.

---

## Architecture Overview

```
Azure services (RabbitMQ, PostgreSQL, etc.)
        ↓
Azure Monitor Workspace (AMW)
— scrapes Prometheus metrics from AKS via ama-metrics agent
— evaluates PrometheusRuleGroups
        ↓
Azure Action Group (webhook)
        ↓
AMW Bridge  (Azure Container Apps)
— translates Azure common alert schema → AlertManager v2
— forwards to opensre /api/v1/alerts
        ↓
opensre  (running locally or on-prem)
— authenticates to AKS via DefaultAzureCredential
— investigates using 11 AKS tools
— posts results to Discord
```

---

## New Alert Ingestion Endpoints

### `POST /azure-alert?token=<BRIDGE_TOKEN>`

Accepts the [Azure Monitor common alert schema](https://learn.microsoft.com/en-us/azure/azure-monitor/alerts/alerts-common-schema) sent by an Azure Action Group webhook. Translates to AlertManager v2 format internally and queues an investigation.

**File:** `app/remote/server.py`

```bash
curl -X POST "https://<opensre-host>/azure-alert?token=<token>" \
  -H "Content-Type: application/json" \
  -d @azure-alert-payload.json
```

### `POST /api/v1/alerts`

Accepts AlertManager v2 webhook format (object `{"alerts":[...]}` or raw list). Used by in-cluster Alertmanager pointed at opensre's public URL.

**File:** `app/remote/server.py`

---

## AMW Bridge

A lightweight FastAPI translator deployed as an Azure Container App.

**Source:** `bridge/main.py`  
**Image:** built via `az acr build` and stored in ACR

**What it does:**
- Receives Azure common alert schema from the Action Group
- Translates `essentials` and `alertContext` fields to AlertManager v2 labels/annotations
- POSTs to `OPENSRE_WEBHOOK_URL/api/v1/alerts`

**Environment variables:**
| Variable | Description |
|---|---|
| `OPENSRE_WEBHOOK_URL` | opensre `/api/v1/alerts` endpoint (tunnel URL when running locally) |
| `BRIDGE_TOKEN` | Shared secret — must match `BRIDGE_TOKEN` in opensre `.env` |

**Deploy:**
```bash
az containerapp update \
  --name amw-bridge \
  --resource-group <rg> \
  --set-env-vars "OPENSRE_WEBHOOK_URL=https://<tunnel>/api/v1/alerts" \
                 "BRIDGE_TOKEN=<token>"
```

---

## AKS Integration

### Authentication

Uses `azure-identity` `DefaultAzureCredential` — resolves in this order:
1. `AZURE_TENANT_ID` / `AZURE_CLIENT_ID` / `AZURE_CLIENT_SECRET` (Service Principal)
2. Managed Identity (when running inside Azure)
3. Azure CLI login (`az login`) — default for local development

No kubeconfig file is required. Cluster credentials are fetched at runtime via `azure-mgmt-containerservice`.

**File:** `app/services/aks/aks_k8s_client.py`

### Configuration

Add to `.env`:

```env
AKS_SUBSCRIPTION_ID=<subscription-id>
AKS_RESOURCE_GROUP=<resource-group>
AKS_CLUSTER_NAME=<cluster-name>
AKS_NAMESPACE=<default-namespace>   # e.g. chaos-targets

# Optional — only needed when az login is not available
AZURE_TENANT_ID=<tenant-id>
AZURE_CLIENT_ID=<client-id>
AZURE_CLIENT_SECRET=<client-secret>
```

### Available Tools (11)

#### Kubernetes API tools
| Tool | What it returns |
|---|---|
| `list_aks_pods` | Pod phase, restart count, container states, conditions |
| `list_aks_deployments` | Replica counts, availability, rollout conditions |
| `get_aks_deployment_status` | Single deployment deep-dive — generation, replica history |
| `list_aks_namespaces` | All namespaces and their phase |
| `get_aks_pod_logs` | Container logs with `tail_lines`, `previous`, `container` params |
| `get_aks_events` | Kubernetes Warning events — OOMKilled, BackOff, probe failures |
| `get_aks_node_health` | Node conditions, capacity, allocatable, pressure flags |

#### Azure Management Plane tools
| Tool | What it returns |
|---|---|
| `list_aks_clusters` | All AKS clusters in subscription — location, k8s version, power state |
| `describe_aks_cluster` | Cluster config — network plugin, RBAC, addons, OIDC issuer |
| `list_aks_node_pools` | Node pools — VM SKU, count, autoscaling bounds, power state |
| `get_aks_node_pool_health` | Per-pool provisioning and power state — highlights degraded pools |

### New source files

```
app/services/aks/
├── __init__.py
├── aks_k8s_client.py        # builds CoreV1Api + AppsV1Api via Azure SDK
├── management_client.py     # cluster/node-pool metadata via ContainerServiceClient
└── utils.py                 # credential normalization

app/tools/utils/
├── aks_workload_helper.py   # extract_aks_workload_params, extract_aks_cluster_params
└── availability.py          # + aks_available_or_backend()

app/tools/
├── AKSListPodsTool/
├── AKSListDeploymentsTool/
├── AKSListNamespacesTool/
├── AKSDeploymentStatusTool/
├── AKSPodLogsTool/
├── AKSEventsTool/
├── AKSNodeHealthTool/
├── AKSListClustersTool/
├── AKSDescribeClusterTool/
├── AKSListNodePoolsTool/
└── AKSNodePoolHealthTool/
```

### Modified files

| File | Change |
|---|---|
| `app/types/evidence.py` | Added `'aks'` to `EvidenceSource` Literal |
| `app/integrations/config_models.py` | Added `AzureStaticCredentials`, `AKSIntegrationConfig` |
| `app/integrations/_catalog_impl.py` | AKS env var loading + classification block |
| `app/agent/investigation.py` | AKS tools seeded for `aks`, `azure`, `azure-monitor-workspace` alert sources |
| `app/agent/prompt.py` | Same alert source → tool source mappings |
| `app/tools/utils/availability.py` | `aks_available_or_backend()` |
| `pyproject.toml` | Added `azure-identity`, `azure-mgmt-containerservice` dependencies |

---

## Discord Formatting

Investigation results sent to Discord now use structured embeds:

```
🚨  <alert name>
┌──────────────┬──────────────┬──────────────┐
│  Namespace   │   Severity   │   Restarts   │
└──────────────┴──────────────┴──────────────┘
Root Cause
  <first sentence of root cause>

Key Findings
  • finding 1
  • finding 2 (max 4)

Next Steps
  • `kubectl get pods -n chaos-targets`
  • next step 2 (max 3, kubectl in code blocks)

OpenSRE • d-aks-opensre-poc
```

**Modified files:**
- `app/remote/server.py` — slash command response format
- `app/utils/discord_delivery.py` — channel post format
- `app/delivery/publish_findings/node.py` — passes `root_cause`, `alert_name`, `is_noise` to Discord delivery

**New env var:** `DISCORD_ALERT_CHANNEL_ID` — channel where AMW/Alertmanager-triggered alerts post. Separate from `DISCORD_DEFAULT_CHANNEL_ID` (which should be left empty to avoid duplicate posts from slash commands).

---

## Running Locally

Start script handles opensre + cloudflare tunnel + auto-patching Discord, Alertmanager, and AMW bridge in one command:

```bash
/path/to/opensre/scripts/start.sh
```

On startup it:
1. Starts opensre on port 8001 with `.env` loaded
2. Starts `cloudflared tunnel` to get a public HTTPS URL
3. PATCHes Discord interactions endpoint URL
4. Updates Alertmanager webhook secret in-cluster
5. Updates AMW bridge `OPENSRE_WEBHOOK_URL` on Container Apps

**Note:** Always use `start.sh` — never restart opensre independently without cloudflared, or Discord interactions will timeout.

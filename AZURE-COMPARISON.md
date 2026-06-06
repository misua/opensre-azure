# Azure Coverage Comparison
# misua/opensre-azure vs swapnildahiphale/OpenSRE
# Written: May 2026

---

## Context

You are running `misua/opensre-azure` (a fork of Tracer-Cloud/opensre with Azure additions).
`swapnildahiphale/OpenSRE` is a completely separate codebase (not a fork) that also targets Azure/AKS.

The goal of this document: identify what swapnildahiphale has that misua doesn't,
so those features can be added to your existing opensre-azure setup.

---

## Repos

| Repo | Type | Clone |
|---|---|---|
| misua/opensre-azure | Fork of Tracer-Cloud/opensre + Azure layer | git clone https://github.com/misua/opensre-azure |
| swapnildahiphale/OpenSRE | Independent codebase | git clone https://github.com/swapnildahiphale/OpenSRE |
| Tracer-Cloud/opensre | Upstream base | git clone https://github.com/Tracer-Cloud/opensre |

---

## Architecture Difference

### misua/opensre-azure
- Single Python process (CLI + FastAPI server)
- Tools live in app/tools/ as Python classes with @tool decorator
- LangGraph pipeline: alert -> plan -> investigate -> diagnose -> publish
- Alert ingestion: /azure-alert webhook, /api/v1/alerts
- Output: Slack + Discord
- Auth: DefaultAzureCredential (az login, MI, or SP env vars)
- No database, no UI, no memory

### swapnildahiphale/OpenSRE
- 6 Docker services (PostgreSQL, config-service, LiteLLM, Neo4j, sre-agent, web-ui)
- Tools live in .claude/skills/ as Python/bash scripts with SKILL.md docs
- LangGraph pipeline: init_context -> [memory_lookup + kg_context] -> planner -> subagents -> synthesizer -> writeup -> memory_store
- Alert ingestion: Slack commands, web UI
- Output: Slack
- Auth: kubeconfig or in-cluster SA for Kubernetes (not Azure-native for K8s)
- Has: PostgreSQL episodic memory, Neo4j knowledge graph, Next.js web console

---

## Area 1: AKS Inspection — misua is more Azure-native

misua authenticates to AKS via Azure SDK (azure-mgmt-containerservice).
It fetches cluster credentials at runtime — no kubeconfig on disk needed.
swapnildahiphale uses existing kubeconfig or in-cluster SA — requires az aks get-credentials first.

### Tools side by side

| Capability | misua/opensre-azure | swapnildahiphale |
|---|---|---|
| List pods | AKSListPodsTool (Azure SDK auth) | list_pods.py (kubeconfig) |
| Get pod logs | AKSPodLogsTool (previous, tail_lines, container) | get_logs.py (same params) |
| Get K8s events | AKSEventsTool (Warning filter) | get_events.py |
| Node health | AKSNodeHealthTool (pressure flags, capacity) | describe_node.py --all |
| List deployments | AKSListDeploymentsTool | describe_deployment.py |
| Deployment rollout status | AKSDeploymentStatusTool (replica history) | describe_deployment.py |
| List namespaces | AKSListNamespacesTool | list_namespaces.py |
| List all clusters | AKSListClustersTool (Azure management plane) | list_clusters.py (k8s gateway) |
| Describe cluster | AKSDescribeClusterTool (RBAC, addons, OIDC, network) | describe_aks_cluster.py |
| Node pool list + health | AKSListNodePoolsTool + AKSNodePoolHealthTool | NOT PRESENT |
| Resource usage vs limits | NOT PRESENT | get_resources.py |

### Key advantage of misua
No kubeconfig file required. Authenticates via azure-mgmt-containerservice.
Works immediately on a fresh machine with just az login or a Managed Identity.

### What to add from swapnildahiphale to misua
- get_resources.py equivalent: compare pod CPU/memory usage vs configured limits
  (shows "pod is using 90% of its memory limit" which is useful before an OOMKill)

---

## Area 2: Azure Monitor / AMW Prometheus — misua wins decisively

This is the single most important capability gap.

| Capability | misua/opensre-azure | swapnildahiphale |
|---|---|---|
| AMW Prometheus time-series (PromQL) | AMWPrometheusQueryTool | NOT PRESENT |
| Azure Monitor metrics | via upstream AzureMonitorLogsTool | get_monitor_metrics.py |
| Log Analytics KQL | via upstream AzureMonitorLogsTool | query_log_analytics.py |
| Monitor alert rules list | NOT PRESENT | list_monitor_alerts.py |

### Why AMW Prometheus matters
query_amw_prometheus takes a PromQL query and returns time-series data from your
Azure Monitor Workspace. This is the difference between:

  WITHOUT: "The pod was OOMKilled."
  WITH:    "Memory was rising steadily for 14 minutes before the pod was killed.
            At T-14m: 420Mi. At T-7m: 480Mi. At T-0: 512Mi (limit hit)."

swapnildahiphale has no equivalent. This is misua's strongest unique capability.

### What to add from swapnildahiphale to misua
- list_monitor_alerts.py equivalent: a tool that lists configured Azure Monitor alert rules
  (useful for "what alerts are even set up?" during investigation)

---

## Area 3: Azure Infrastructure Breadth — swapnildahiphale wins

swapnildahiphale covers more Azure resource types that misua completely lacks.

| Capability | misua/opensre-azure | swapnildahiphale | Azure SDK used |
|---|---|---|---|
| Virtual Machines (list + describe) | NOT PRESENT | list_vms.py + describe_vm.py | azure-mgmt-compute |
| Network Security Groups (rules) | NOT PRESENT | get_nsg_rules.py | azure-mgmt-network |
| Cost Management | NOT PRESENT | query_costs.py | azure-mgmt-costmanagement |
| Resource Graph (cross-subscription KQL) | NOT PRESENT | query_resource_graph.py | azure-mgmt-resourcegraph |
| Monitor alert rules | NOT PRESENT | list_monitor_alerts.py | azure-mgmt-monitor |

### VM investigation script (describe_vm.py)
Shows: VM size, OS, network interfaces, disks, power state, instance view.
Useful for: "which VM is this pod running on, and is that VM healthy?"

### NSG rules script (get_nsg_rules.py)
Shows: all inbound/outbound rules, priority, source/dest, port ranges, allow/deny.
Useful for: "is there an NSG rule blocking traffic to this service?"
This directly mirrors the real Azure incident you described (leftover NICs and rules
after VM deletion).

### Cost Management script (query_costs.py)
Args: --start, --end, --granularity (Daily/Monthly/BillingMonth), --group-by (ResourceGroup, ServiceName, etc.)
Useful for: "why did costs spike this month?" post-incident analysis.

### Resource Graph script (query_resource_graph.py)
Runs KQL against Azure Resource Graph — cross-subscription, cross-resource-type queries.
Example: "Resources | where type == 'microsoft.compute/virtualmachines' | project name, location"
Useful for: finding orphaned resources, NICs without VMs, stale public IPs.
This is the EXACT capability for your "VMs deleted but NICs left behind" scenario.

---

## Area 4: Alert Ingestion — misua wins

| Capability | misua/opensre-azure | swapnildahiphale |
|---|---|---|
| Azure common alert schema webhook | /azure-alert?token=<BRIDGE_TOKEN> | NOT PRESENT |
| AMW PrometheusRuleGroup alerts | via /azure-alert | NOT PRESENT |
| AlertManager v2 webhook | /api/v1/alerts | NOT PRESENT |
| Slack slash command | /slack/command | via Slack app |
| Web UI trigger | NOT PRESENT | http://localhost:3002 |

misua was built to receive alerts from Azure Action Groups directly.
swapnildahiphale has no Azure-native alert ingestion.

---

## Area 5: Azure SDK Packages

| Package | misua/opensre-azure | swapnildahiphale | Needed for |
|---|---|---|---|
| azure-identity | YES | YES | DefaultAzureCredential |
| azure-mgmt-containerservice | YES | YES | AKS cluster/credential API |
| azure-mgmt-compute | NO | YES | VMs |
| azure-mgmt-network | NO | YES | NSGs, VNets |
| azure-mgmt-costmanagement | NO | YES | Cost analysis |
| azure-mgmt-resourcegraph | NO | YES | Resource Graph queries |
| azure-mgmt-monitor | NO | YES | Alert rules |
| azure-monitor-query | YES (upstream) | YES | Log Analytics KQL |
| kubernetes | YES (Python SDK) | YES (Python SDK) | K8s API calls |

---

## Area 6: Features unique to swapnildahiphale (not in misua)

### Episodic Memory (PostgreSQL)
Every investigation is stored. When a new alert arrives, it finds similar past episodes
and prepends: "Last time this happened, the root cause was X and the fix was Y."
Stores: summary, root cause, alert type, services, skills used, duration, success flag.
Generated by LLM from each completed investigation.

### Neo4j Knowledge Graph
Maps service topology and dependencies.
Allows: blast radius analysis ("if orders-api dies, what else breaks?")
Before investigation starts, it queries the graph to understand what depends on what.
Populated from Kubernetes infrastructure data.

### Web Console (Next.js)
- Dashboard with investigation history
- Agent run viewer (see what the agent did step by step)
- Memory browser (view stored episodes)
- Config editor (manage integrations via UI, not just .env)
- Team management

### LiteLLM Proxy
Normalizes API calls across all LLM providers.
Supports: Claude, OpenAI, Gemini, DeepSeek, Mistral, Ollama, OpenRouter.
Your current misua setup only supports the providers that Tracer-Cloud/opensre supports natively.

### Multi-tenancy
org -> team hierarchy with deep-merge config.
Each team can have different integrations, LLM settings, enabled skills.

---

## What to add to misua/opensre-azure (priority order)

### Priority 1 — High value, low complexity
These are Python scripts that can be added as new tool classes in app/tools/
following the exact same pattern as existing AKS tools.

1. VirtualMachinesInspectionTool
   Source: swapnildahiphale/infrastructure-azure/scripts/list_vms.py + describe_vm.py
   SDK: azure-mgmt-compute
   What it adds: VM listing and description — useful when investigating
                 "is this K8s node actually a healthy Azure VM?"

2. NetworkSecurityGroupTool
   Source: swapnildahiphale/infrastructure-azure/scripts/get_nsg_rules.py
   SDK: azure-mgmt-network
   What it adds: NSG rule inspection — directly relevant to your "leftover rules
                 after VM deletion" scenario. Also for "why can't service A reach service B?"

3. ResourceGraphQueryTool
   Source: swapnildahiphale/infrastructure-azure/scripts/query_resource_graph.py
   SDK: azure-mgmt-resourcegraph
   What it adds: Cross-subscription resource queries — find orphaned NICs, stale IPs,
                 resources that shouldn't exist after a cleanup.

4. MonitorAlertRulesTool
   Source: swapnildahiphale/infrastructure-azure/scripts/list_monitor_alerts.py
   SDK: azure-mgmt-monitor
   What it adds: List what alert rules exist — "what is Azure Monitor even watching?"

### Priority 2 — Medium value, medium complexity

5. AzureCostManagementTool
   Source: swapnildahiphale/infrastructure-azure/scripts/query_costs.py
   SDK: azure-mgmt-costmanagement
   What it adds: Cost breakdown by ResourceGroup, ServiceName, time period.
                 Post-incident: "did this incident cause unexpected Azure spend?"

6. AKSResourceUsageTool
   Source: swapnildahiphale/infrastructure-kubernetes/scripts/get_resources.py
   Pattern: extend existing AKS tool set
   What it adds: Pod CPU/memory usage vs configured limits.
                 Pre-OOMKill: "pod is at 95% of memory limit, container = app"

### Priority 3 — High value, high complexity (separate project)

7. Episodic Memory System
   Source: swapnildahiphale/sre-agent/memory/
   Requires: PostgreSQL + config-service
   What it adds: "Last time this exact alert fired, the fix was X"
   Complexity: Needs a database, a config-service, migration management.
               Could be simplified to SQLite for smaller deployments.

8. Neo4j Knowledge Graph
   Source: swapnildahiphale/sre-agent/tools/neo4j_semantic_layer.py
   Requires: Neo4j instance
   What it adds: Service dependency mapping and blast radius analysis.

---

## Adding Priority 1 tools to misua/opensre-azure — implementation notes

All 4 tools follow the same pattern as existing AKS tools:

    app/tools/VirtualMachinesInspectionTool/__init__.py
    app/tools/NetworkSecurityGroupTool/__init__.py
    app/tools/ResourceGraphQueryTool/__init__.py
    app/tools/MonitorAlertRulesTool/__init__.py

Each needs:
1. @tool decorator with name, description, use_cases, requires, input_schema
2. is_available function (checks env vars AKS_SUBSCRIPTION_ID etc.)
3. extract_params function
4. The actual function body using Azure SDK

Auth pattern (same as all existing AKS tools):
    from app.services.aks.management_client import _get_credential
    OR
    from azure.identity import DefaultAzureCredential
    credential = DefaultAzureCredential()

New packages to add to pyproject.toml:
    "azure-mgmt-compute>=30.0.0",
    "azure-mgmt-network>=25.0.0",
    "azure-mgmt-resourcegraph>=8.0.0",
    "azure-mgmt-monitor>=6.0.0",
    "azure-mgmt-costmanagement>=4.0.0",

---

## Summary scorecard

| Azure Scenario | misua better | swapnildahiphale better |
|---|---|---|
| AKS pod/log/event inspection without kubeconfig | YES | |
| AKS node pool health (scaling, failures) | YES | |
| AMW Prometheus time-series metric trends | YES | |
| Azure alert webhook ingestion from Action Groups | YES | |
| VM inspection (list, describe, health) | | YES |
| NSG rule inspection (blocking traffic?) | | YES |
| Orphaned resource detection (Resource Graph) | | YES |
| Monitor alert rules (what is configured?) | | YES |
| Cost analysis | | YES |
| Episodic memory (what fixed this last time?) | | YES |
| Neo4j blast radius analysis | | YES |
| Web console | | YES |

Bottom line: misua wins for AKS-native investigation and AMW metric history.
swapnildahiphale wins for Azure infrastructure breadth and memory/knowledge features.
The ideal production setup adds Priority 1-2 tools from swapnildahiphale into misua.

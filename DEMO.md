# OpenSRE on Azure — Demo Runbook

A step-by-step script for demonstrating the OpenSRE AI SRE agent running against a live
AKS cluster. The demo shows OpenSRE **autonomously investigating real failures** and
delivering root-cause analysis to Slack, both **automatically (alert-driven)** and
**on-demand (interactive `/investigate` slash command)**.

> **Audience:** read this start-to-finish once before presenting, then keep it open and
> follow the **Demo flow** section live.

---

## 1. What you are demonstrating

OpenSRE is an AI SRE agent that investigates production incidents and produces an
evidence-backed root-cause analysis (RCA). In this environment it runs as an Azure
Container App, queries a live AKS cluster with 11 AKS tools, and posts findings to Slack.

Two delivery paths, both shown in the demo:

| Path | Trigger | Output format | "Wow" factor |
|------|---------|---------------|--------------|
| **Alert-driven** | A metric crosses an Azure Monitor (AMW) alert rule | Full RCA report | Fully autonomous — no human in the loop |
| **Interactive** | A human types `/investigate …` in Slack | Terse RCA (root cause + top findings + top actions) | On-demand, conversational |

---

## 2. Architecture (one slide)

```
 chaos / real failure on AKS
   │
   ├─ (AUTOMATIC) metric crosses AMW PrometheusRuleGroup
   │     → Action Group  ag-opensre-amw
   │     → Container App  amw-bridge   (/azure-alert)
   │     → Container App  opensre
   │     → Claude LLM investigation (~90–110s, 11 AKS tools)
   │     → Slack #azure-opensre  (FULL report)
   │
   └─ (INTERACTIVE) human types  /investigate <symptom>  in Slack
         → Slack slash command  → Container App opensre (/slack/command)
         → same investigation engine
         → Slack #azure-opensre  (TERSE report)
```

Key environment facts:

- **AKS cluster:** `d-aks-opensre-poc` (RG `d-rg-aks-opensre-poc`, canadacentral)
- **OpenSRE Container App:** `https://opensre.mangosmoke-000c4421.canadacentral.azurecontainerapps.io`
- **Slack channel:** `#azure-opensre`
- **Chaos targets namespace:** `chaos-targets` (postgres, rabbitmq, nginx, producer, consumer)

---

## 3. Pre-flight checklist (run ~10 min before)

```bash
# 1. kubectl points at the right cluster
kubectl config current-context            # expect: d-aks-opensre-poc

# 2. Chaos targets are healthy at baseline
kubectl -n chaos-targets get pods         # postgres/rabbitmq/nginx/producer/consumer all Running

# 3. OpenSRE Container App is up
curl -s https://opensre.mangosmoke-000c4421.canadacentral.azurecontainerapps.io/ok
#    expect: {"ok":true, ...}

# 4. Slack slash command is registered
#    In Slack, type "/inv" — "/investigate" should autocomplete.
#    If not: api.slack.com/apps → SRE-helper → Install App → Reinstall to Workspace → Allow,
#    then fully quit & reopen Slack.
```

If all four pass, you are ready.

---

## 4. Demo flow

### Part 0 — Frame the problem (talk, ~1 min)
- "When an alert fires at 3am, an SRE spends 20–40 minutes gathering logs, events, and pod
  state before they even form a hypothesis. OpenSRE does that first pass automatically."
- Show the architecture slide (section 2).

### Part 1 — Autonomous, alert-driven investigation (~3–4 min)

This is the headline: **inject a real failure, then do nothing — OpenSRE notices and reports.**

1. **Inject** the postgres out-of-memory failure (see *Scenario A* below). Postgres OOMKills
   within ~24s and goes into CrashLoopBackOff — the database is fully down.
2. **Narrate while you wait:** the OOM raises restart metrics → AMW `PostgresOutOfMemory`
   rule fires → Action Group → `amw-bridge` → OpenSRE. No human touched anything.
3. **Watch `#azure-opensre`.** In ~90–110s a **full RCA report** posts automatically:
   root cause, validated findings, recommended `kubectl` actions with expected outcomes.
4. **Call out the root cause:** OpenSRE identifies the OOMKill + the too-low memory limit
   from the pod's own `lastState.terminated.reason` and resource limits.

### Part 2 — Interactive `/investigate` slash command (~2–3 min)

While postgres is still down, show the on-demand path:

1. In `#azure-opensre`, run a **specific, symptom-shaped** prompt (vague questions get
   classified as noise — see *Tips*):
   ```
   /investigate postgres-postgresql-0 is OOMKilled and in CrashLoopBackOff in namespace chaos-targets
   ```
2. OpenSRE replies instantly with an ephemeral `:mag: Investigating…` ack (<3s).
3. ~90s later it posts a **terse** report to the channel: root cause + top-3 findings +
   top-3 actions only — readable in a chat, no wall of text.
4. **Contrast the two:** same incident, same engine — full report for the autonomous
   alert path, compact report for the human-in-the-loop path.

### Part 3 — Heal & wrap (talk, ~1 min)
- Run the **heal** command (Scenario A) — postgres recovers in ~18s.
- "OpenSRE didn't just detect the failure; it handed the operator the exact remediation
  commands. The human stays in control and approves the fix."

---

## 5. Failure scenarios — exact commands

> All scenarios target the `chaos-targets` namespace. Postgres is a **single-replica
> StatefulSet**, so these take the database fully down for the demo window (intended).

### Scenario A — Postgres OOM (PRIMARY — most reliable, manual control)

Best for the live demo because you control exactly when it breaks and heals.

**Inject** (memory limit shrunk to 24Mi → OOMKilled in ~24s, sustained CrashLoopBackOff):
```bash
NS=chaos-targets; STS=postgres-postgresql; C=postgresql

kubectl -n $NS patch statefulset $STS -p \
'{"spec":{"template":{"spec":{"containers":[{"name":"postgresql","resources":{"limits":{"memory":"24Mi"},"requests":{"memory":"24Mi"}}}]}}}}'
```

**Watch it break:**
```bash
kubectl -n chaos-targets get pod postgres-postgresql-0 -w
# expect: OOMKilled → CrashLoopBackOff, restarts climbing
```

**Heal** (revert to original limits, then delete the pod so it recreates fresh and skips
the exponential 5-minute CrashLoopBackOff timer — recovers in ~18s):
```bash
NS=chaos-targets; STS=postgres-postgresql; C=postgresql

kubectl -n $NS patch statefulset $STS -p \
'{"spec":{"template":{"spec":{"containers":[{"name":"postgresql","resources":{"limits":{"memory":"512Mi"},"requests":{"memory":"128Mi"}}}]}}}}'

kubectl -n $NS delete pod postgres-postgresql-0

# confirm recovery
kubectl -n $NS get pod postgres-postgresql-0     # expect 2/2 Running, 0 restarts
```

> **Calibration note:** 24Mi is below postgres' ~30Mi idle working set, so the OOM is
> reliable. Do **not** raise above ~28Mi (32Mi sometimes fits when idle → no OOM, no alert).

### Scenario A (scripted alternative — auto inject → wait → heal)

If you prefer a hands-off run that injects, waits for detection, then heals automatically:
```bash
cd /home/charles/opensre
./scripts/chaos-cycle.sh extra:postgres-low-memory
```
The script reverts the limit and deletes the pod at the end. Use the **manual** commands
above if you want to hold the failure open while you show both Slack paths.

### Scenario B — Postgres disk fill (secondary)

Fills the postgres data volume so free space drops below 10% → AMW `opensre-postgres-rules`:
```bash
cd /home/charles/opensre
./scripts/chaos-cycle.sh extra:postgres-disk-fill
```

### Scenario C — Chaos Mesh pod/network experiments (optional, richer)

Run a bundled Chaos Mesh manifest by prefix (`a*` nginx, `b*` postgres, `c*` rabbitmq):
```bash
cd /home/charles/opensre
./scripts/chaos-cycle.sh --list          # see all scenarios
./scripts/chaos-cycle.sh c1              # e.g. rabbitmq pod-kill
```

### Dry run (rehearse with zero impact)
```bash
cd /home/charles/opensre
DRY_RUN=1 YES=1 ./scripts/chaos-cycle.sh extra:postgres-low-memory
```

---

## 6. Slack prompts to use

Use **specific, symptom-shaped** prompts. Vague questions ("what's wrong?") get classified
as noise and return `N/A`.

Good:
```
/investigate postgres-postgresql-0 is OOMKilled and in CrashLoopBackOff in namespace chaos-targets
/investigate PostgresOutOfMemory — postgres pod restarting, database is down
```

Avoid:
```
/investigate what pods are having issues        ← too vague, may return [noise] / N/A
```

The slash command also accepts a JSON alert payload if you want to paste a structured alert.

---

## 7. Tips & talking points

- **Lead with the autonomous path.** The strongest moment is injecting a failure and then
  *doing nothing* while OpenSRE reports it to Slack on its own.
- **Highlight the evidence.** Point at the `Cited Evidence` / tool calls — OpenSRE reports
  what the AKS tools actually returned, it does not hallucinate.
- **Highlight the remediation format.** Each action is `[RISK] what → exact command →
  expected outcome`. The human approves and runs it.
- **Single-replica blast radius.** Postgres going fully down is a realistic "whole service
  impacted" story — good for showing severity.
- **Recovery is fast.** Deleting the crashlooping pod skips the backoff timer; postgres is
  back in ~18s, so you can re-run the demo quickly.

---

## 8. Troubleshooting

| Symptom | Fix |
|---------|-----|
| `/investigate` → "not a valid command" | Slash command not active. api.slack.com/apps → SRE-helper → **Install App → Reinstall to Workspace → Allow**, then fully quit & reopen Slack. |
| Slash command returns `[noise] / N/A` | Prompt was too vague. Use a specific symptom (section 6). |
| Postgres won't OOM | Memory limit too high. Use 24Mi, not 32Mi (section 5 calibration note). |
| Postgres stuck in CrashLoopBackOff after heal | Backoff timer. `kubectl -n chaos-targets delete pod postgres-postgresql-0` to recreate fresh. |
| No Slack post from alert path | Confirm the AMW rule path, not the local Alertmanager path (the latter is firewall-blocked). Alerts must flow via AMW PrometheusRuleGroup → `ag-opensre-amw` → `amw-bridge`. |
| Container App health fails | `curl …/ok`; check the active revision is serving 100% traffic. |

---

## 9. Quick reference — copy/paste block

```bash
# --- PRE-FLIGHT ---
kubectl config current-context
kubectl -n chaos-targets get pods
curl -s https://opensre.mangosmoke-000c4421.canadacentral.azurecontainerapps.io/ok

# --- BREAK postgres (OOM) ---
kubectl -n chaos-targets patch statefulset postgres-postgresql -p \
'{"spec":{"template":{"spec":{"containers":[{"name":"postgresql","resources":{"limits":{"memory":"24Mi"},"requests":{"memory":"24Mi"}}}]}}}}'

# (then in Slack)
# /investigate postgres-postgresql-0 is OOMKilled and in CrashLoopBackOff in namespace chaos-targets

# --- HEAL postgres ---
kubectl -n chaos-targets patch statefulset postgres-postgresql -p \
'{"spec":{"template":{"spec":{"containers":[{"name":"postgresql","resources":{"limits":{"memory":"512Mi"},"requests":{"memory":"128Mi"}}}]}}}}'
kubectl -n chaos-targets delete pod postgres-postgresql-0
kubectl -n chaos-targets get pod postgres-postgresql-0
```

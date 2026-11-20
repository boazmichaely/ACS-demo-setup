# ACS Lightspeed demo notes

Use after `acs-lightspeed` status is **ok**.

## What you just installed

- OpenShift Lightspeed on the **same OpenShift cluster as Central**
- An LLM credential Secret + `OLSConfig` (default: OpenAI)
- RBAC so Central’s ServiceAccount can call OLS (`ols-user`)
- A NetworkPolicy allowing Central → OLS on port 8443

RHACS 5.0 Tech Preview then calls OLS for plain-language **Risk** explanations (`ROX_LIGHTSPEED_RISK_SUMMARY`). There is no separate ACS “AI integration” object in 5.0.0 - Central uses the in-cluster OLS endpoint by default.

## Talk track (about 2 minutes)

1. Optional: OpenShift console → Lightspeed chat - ask a simple cluster question to show OLS itself is alive.
2. Open Central → **Risk** (status summary links there when ready).
3. Pick a non-trivial deployment (demo workloads from `ms-demo` / `init-demo` are good).
4. Use the AI risk explanation control.
5. Call out: output is **AI-generated** - security teams still decide remediation. Prefer Red Hat validated models when customers ask about model choice.

## Lab credentials

Integration Secrets → **OpenShift Lightspeed LLM**: provider / model / API URL / API token. The token never ships in git defaults.

## Uninstall

Module uninstall removes demo-owned OLS Operator pieces on Central OCP. Central API plane has nothing extra to delete on RHACS 5.0.

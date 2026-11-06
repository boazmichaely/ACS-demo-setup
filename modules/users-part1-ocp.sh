#!/usr/bin/env bash
# Module: users-part1-ocp - OpenShift HTPasswd users + RBAC (ACS console plugin demo lead-in)
set -euo pipefail

MODULE_ID="users-part1-ocp"
IDP_NAME="lab_htpasswd"
SECRET_NS="openshift-config"
SECRET_NAME="htpasswd-secret"
PW_ADAM="adam"
PW_BOAZ="boaz"
PW_CHRIS="chris"
DEMO_USERS=(adam boaz chris)
MS_NS="ms-demo"
INIT_NS="acs-init-container-test"
# Extra namespaces for chris admin (--chris-ns); ms-demo + init always included.
CHRIS_EXTRA_NS=()
# Orchestrator / CLI: at most one SC id (OpenShift-only module).
U1_SC_IDS=()
U1_SC_ID=""
U1_PLANE=""

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEMO_MD="${ROOT}/modules/users-part1-ocp-demo.md"
PYTHON="${ACS_DEMO_PYTHON:-}"
if [[ -z "$PYTHON" ]]; then
  if [[ -x "${ROOT}/gui/.venv/bin/python" ]]; then
    PYTHON="${ROOT}/gui/.venv/bin/python"
  else
    PYTHON="$(command -v python3)"
  fi
fi

usage() {
  cat <<EOF
# users-part1-ocp

Lead-in for the ACS console plugin visibility demo: create OpenShift
HTPasswd users (adam, boaz, chris) and project RBAC so different people
can log into the OpenShift console and open Security → Vulnerabilities.

This module alone is not the complete story. Run Users Part 2 (OAuth)
and Users Part 3 (ACS) after this for Central OpenShift login and ACS
role/scope mappings. The ACS console plugin must already be installed
on the cluster.

If ACS is installed but you do not see the Security menu in the
OpenShift console, enable it in the OpenShift UI:
Administration → Cluster Settings → Configuration → Console →
Console plugins, then enable \`advanced-cluster-security\`.

Demo script (before/after tables for adam, boaz, chris):
\`modules/users-part1-ocp-demo.md\` (GUI: \`/help?doc=users-part1-ocp-demo\`).
Status → Demo also links there.

**Personas** (password = username)

- \`adam\` - cluster-admin
- \`boaz\` - admin on \`${MS_NS}\`
- \`chris\` - admin on \`${MS_NS}\` and \`${INIT_NS}\` (plus optional \`--chris-ns\`)

Lab passwords are listed under Status → Credentials.

Catalog: \`impactPlanes: ["openshift"]\`. With \`--secured-cluster-id\`,
targets that SC (console plugin / HTPasswd live there). With none, uses
the lab soft-default SC.

## Usage

\`\`\`
$(basename "$0") --help
$(basename "$0") --status [--secured-cluster-id ID]
$(basename "$0") --run [--dry-run] [--secured-cluster-id ID] [--chris-ns NS]...
$(basename "$0") --uninstall [--dry-run] [--secured-cluster-id ID]
\`\`\`

## Flags

- \`--secured-cluster-id ID\` - lab secured-cluster id (at most one)
- \`--plane openshift\` - accepted (implied); other planes rejected
- \`--chris-ns NS\` - Extra OpenShift namespace where chris gets admin
  (repeatable; always includes \`${MS_NS}\` and \`${INIT_NS}\`)
- \`--dry-run\` - Print the plan; change nothing

## Status Info

- Demo script link
- Lab logins (adam / boaz / chris passwords)
- HTPasswd IdP and \`htpasswd-secret\` state
- RBAC RoleBindings for the three personas

## Pre Conditions

- ACS console plugin enabled on the cluster
- \`htpasswd\` and \`openssl\` on PATH

## Side effects

- \`--run\` ensures Secret \`${SECRET_NS}/${SECRET_NAME}\`, IdP \`${IDP_NAME}\`,
  and named RoleBindings for adam/boaz/chris
- \`--uninstall\` removes those RoleBindings, IdP \`${IDP_NAME}\`, the Secret,
  OCP User and Identity objects for adam/boaz/chris (\`lab_htpasswd:*\`),
  and waits for oauth-openshift to roll out so the login page drops the IdP.
  Hard-refresh the browser if the old IdP name still appears
EOF
}

ensure_oc() {
  local kc errf err
  if ! command -v oc >/dev/null 2>&1; then
    printf 'oc not on PATH\n' >&2
    return 1
  fi
  errf="$(mktemp)"
  if ! kc="$(
    cd "${ROOT}" || exit 1
    if [[ -n "${U1_SC_ID}" ]]; then
      "$PYTHON" -m lib.openshift login --secured-cluster-id "${U1_SC_ID}" --print-kubeconfig 2>"${errf}"
    else
      "$PYTHON" -m lib.openshift login --print-kubeconfig 2>"${errf}"
    fi
  )"; then
    err="$(tr '\n' ' ' <"${errf}" 2>/dev/null)"
    rm -f "${errf}"
    printf '%s\n' "${err:-OpenShift access failed}" >&2
    return 1
  fi
  rm -f "${errf}"
  if [[ -z "${kc}" || ! -f "${kc}" ]]; then
    printf 'ensure_oc did not return a kubeconfig path\n' >&2
    return 1
  fi
  export KUBECONFIG="${kc}"
  return 0
}

require_bins() {
  local b
  for b in oc htpasswd openssl python3 jq; do
    if ! command -v "$b" >/dev/null 2>&1; then
      printf 'required tool not on PATH: %s\n' "$b" >&2
      return 1
    fi
  done
}

chris_namespaces() {
  local ns
  for ns in "${CHRIS_EXTRA_NS[@]}" "$MS_NS" "$INIT_NS"; do
    [[ -n "$ns" ]] && printf '%s\n' "$ns"
  done | sed '/^$/d' | sort -u
}

write_htpasswd_temp() {
  local tmp="$1"
  : >"$tmp"
  htpasswd -Bb "$tmp" adam "$PW_ADAM" >/dev/null
  htpasswd -Bb "$tmp" boaz "$PW_BOAZ" >/dev/null
  htpasswd -Bb "$tmp" chris "$PW_CHRIS" >/dev/null
}

# bcrypt salts change every htpasswd -Bb; compare by verifying fixed passwords.
htpasswd_secret_matches() {
  local tmpf u pw
  if ! oc -n "$SECRET_NS" get secret "$SECRET_NAME" >/dev/null 2>&1; then
    return 1
  fi
  tmpf="$(mktemp)"
  if ! oc -n "$SECRET_NS" get secret "$SECRET_NAME" -o jsonpath='{.data.htpasswd}' \
    | base64 -d >"$tmpf" 2>/dev/null; then
    rm -f "$tmpf"
    return 1
  fi
  for u in adam boaz chris; do
    case "$u" in
      adam) pw="$PW_ADAM" ;;
      boaz) pw="$PW_BOAZ" ;;
      chris) pw="$PW_CHRIS" ;;
    esac
    if ! htpasswd -vb "$tmpf" "$u" "$pw" >/dev/null 2>&1; then
      rm -f "$tmpf"
      return 1
    fi
  done
  rm -f "$tmpf"
  return 0
}

apply_htpasswd_secret() {
  local tmp="$1"
  oc -n "$SECRET_NS" create secret generic "$SECRET_NAME" \
    --from-file=htpasswd="$tmp" \
    --dry-run=client -o yaml | oc apply -f -
  oc -n "$SECRET_NS" label secret "$SECRET_NAME" \
    oauth-config.openshift.io/managed-by=config.openshift.io --overwrite >/dev/null 2>&1 || true
}

idp_present() {
  local names
  names="$(oc get oauth.config.openshift.io cluster -o jsonpath='{range .spec.identityProviders[*]}{.name}{"\n"}{end}' 2>/dev/null || true)"
  printf '%s\n' "$names" | grep -qxF "$IDP_NAME"
}

ensure_htpasswd_idp() {
  if idp_present; then
    echo "${MODULE_ID}: IdP ${IDP_NAME} already configured"
    return 0
  fi
  echo "${MODULE_ID}: appending IdP ${IDP_NAME}"
  local edited rc
  edited="$(
    oc get oauth.config.openshift.io cluster -o json | HTNAME="$IDP_NAME" python3 -c '
import json, sys, os
j = json.load(sys.stdin)
spec = j.setdefault("spec", {})
idps = spec.setdefault("identityProviders", [])
name = os.environ["HTNAME"]
if any(p.get("name") == name for p in idps):
    sys.exit(3)
idps.append({
    "name": name,
    "mappingMethod": "claim",
    "type": "HTPasswd",
    "htpasswd": {"fileData": {"name": "htpasswd-secret"}},
})
print(json.dumps(j))
'
  )" && rc=0 || rc=$?
  if [[ "$rc" -eq 3 ]]; then
    return 0
  fi
  [[ "$rc" -eq 0 ]] || return 1
  printf '%s\n' "$edited" | oc replace -f -
}

remove_htpasswd_idp() {
  if ! idp_present; then
    echo "${MODULE_ID}: IdP ${IDP_NAME} already absent"
    return 0
  fi
  echo "${MODULE_ID}: removing IdP ${IDP_NAME}"
  local edited
  edited="$(
    oc get oauth.config.openshift.io cluster -o json | HTNAME="$IDP_NAME" python3 -c '
import json, sys, os
j = json.load(sys.stdin)
name = os.environ["HTNAME"]
spec = j.setdefault("spec", {})
idps = spec.get("identityProviders") or []
spec["identityProviders"] = [p for p in idps if p.get("name") != name]
print(json.dumps(j))
'
  )"
  printf '%s\n' "$edited" | oc replace -f -
}

# First login via HTPasswd creates User + Identity; uninstall must remove them too.
remove_demo_users_and_identities() {
  local u
  for u in "${DEMO_USERS[@]}"; do
    if oc get "identity/${IDP_NAME}:${u}" >/dev/null 2>&1; then
      echo "${MODULE_ID}: deleting identity/${IDP_NAME}:${u}"
      oc delete "identity/${IDP_NAME}:${u}" --ignore-not-found=true
    else
      echo "${MODULE_ID}: identity/${IDP_NAME}:${u} already absent"
    fi
    if oc get "user/${u}" >/dev/null 2>&1; then
      echo "${MODULE_ID}: deleting user/${u}"
      oc delete "user/${u}" --ignore-not-found=true
    else
      echo "${MODULE_ID}: user/${u} already absent"
    fi
  done
}

# OAuth pods must reload before the login page stops listing a removed IdP.
wait_for_oauth_rollout() {
  echo "${MODULE_ID}: waiting for oauth-openshift rollout (login page IdP list)"
  if ! oc -n openshift-authentication rollout status deploy/oauth-openshift --timeout=180s; then
    echo "${MODULE_ID}: warning: oauth-openshift rollout did not finish in time; hard-refresh the login page" >&2
    return 0
  fi
}

ensure_rbac() {
  if oc get clusterrolebinding adam-cluster-admin >/dev/null 2>&1; then
    echo "${MODULE_ID}: RBAC adam-cluster-admin already present"
  else
    echo "${MODULE_ID}: RBAC adam -> cluster-admin"
    oc adm policy add-cluster-role-to-user cluster-admin adam \
      --rolebinding-name="adam-cluster-admin" 2>/dev/null \
      || oc adm policy add-cluster-role-to-user cluster-admin adam
  fi

  if oc get "project/${MS_NS}" >/dev/null 2>&1; then
    if oc get rolebinding boaz-namespace-admin -n "${MS_NS}" >/dev/null 2>&1; then
      echo "${MODULE_ID}: RBAC boaz-namespace-admin already present"
    else
      echo "${MODULE_ID}: RBAC boaz -> admin on ${MS_NS}"
      oc adm policy add-role-to-user admin boaz -n "${MS_NS}" \
        --rolebinding-name="boaz-namespace-admin" 2>/dev/null \
        || oc adm policy add-role-to-user admin boaz -n "${MS_NS}"
    fi
  else
    echo "${MODULE_ID}: skip boaz admin - project ${MS_NS} missing"
  fi

  local ns
  while IFS= read -r ns; do
    [[ -z "$ns" ]] && continue
    if oc get "project/${ns}" >/dev/null 2>&1; then
      if oc get rolebinding "chris-admin-${ns}" -n "${ns}" >/dev/null 2>&1; then
        echo "${MODULE_ID}: RBAC chris-admin-${ns} already present"
      else
        echo "${MODULE_ID}: RBAC chris -> admin on ${ns}"
        oc adm policy add-role-to-user admin chris -n "${ns}" \
          --rolebinding-name="chris-admin-${ns}" 2>/dev/null \
          || oc adm policy add-role-to-user admin chris -n "${ns}"
      fi
    else
      echo "${MODULE_ID}: skip chris admin on ${ns} - project missing"
    fi
  done < <(chris_namespaces)
}

remove_rbac() {
  oc delete clusterrolebinding adam-cluster-admin --ignore-not-found=true
  oc delete rolebinding boaz-namespace-admin -n "${MS_NS}" --ignore-not-found=true 2>/dev/null || true
  local ns
  while IFS= read -r ns; do
    [[ -z "$ns" ]] && continue
    oc delete rolebinding "chris-admin-${ns}" -n "${ns}" --ignore-not-found=true 2>/dev/null || true
  done < <(chris_namespaces)
}

htpasswd_user_present() {
  local user="$1"
  oc -n "$SECRET_NS" get secret "$SECRET_NAME" -o jsonpath='{.data.htpasswd}' 2>/dev/null \
    | base64 -d 2>/dev/null \
    | grep -q "^${user}:"
}

emit_status_sections() {
  local demo_body="$1"
  local cred_body="$2"
  local cred_sum="$3"
  local cred_tag="$4"
  local idp_body="$5"
  local idp_sum="$6"
  local idp_tag="$7"
  local secret_body="$8"
  local secret_sum="$9"
  local secret_tag="${10}"
  local rbac_body="${11}"
  local rbac_sum="${12}"
  local rbac_tag="${13}"
  local sections_json

  sections_json="$(
    jq -nc \
      --arg demo "$demo_body" \
      --arg cred_body "$cred_body" \
      --arg cred_sum "$cred_sum" \
      --arg cred_tag "$cred_tag" \
      --arg idp_body "$idp_body" \
      --arg idp_sum "$idp_sum" \
      --arg idp_tag "$idp_tag" \
      --arg secret_body "$secret_body" \
      --arg secret_sum "$secret_sum" \
      --arg secret_tag "$secret_tag" \
      --arg rbac_body "$rbac_body" \
      --arg rbac_sum "$rbac_sum" \
      --arg rbac_tag "$rbac_tag" \
      '{
        sections: [
          {
            group: "Demo",
            title: "Demo script",
            summary: "users walkthrough",
            tag: "ok",
            tagLabel: "guide",
            body: $demo,
            bodyFormat: "prose"
          },
          {
            group: "Credentials",
            title: "Lab logins",
            summary: $cred_sum,
            tag: $cred_tag,
            tagLabel: $cred_sum,
            body: $cred_body,
            bodyFormat: "prose"
          },
          {
            group: "OpenShift",
            title: "HTPasswd IdP",
            summary: $idp_sum,
            tag: $idp_tag,
            tagLabel: $idp_sum,
            body: $idp_body,
            bodyFormat: "prose"
          },
          {
            group: "OpenShift",
            title: "htpasswd-secret",
            summary: $secret_sum,
            tag: $secret_tag,
            tagLabel: $secret_sum,
            body: $secret_body,
            bodyFormat: "prose"
          },
          {
            group: "OpenShift",
            title: "RBAC",
            summary: $rbac_sum,
            tag: $rbac_tag,
            tagLabel: $rbac_sum,
            body: $rbac_body,
            bodyFormat: "prose"
          }
        ]
      }'
  )"
  printf 'ACS_SECTIONS_JSON=%s\n' "$sections_json"
}

do_status() {
  local errf err
  local demo_body cred_body cred_sum cred_tag
  local idp_body idp_sum idp_tag
  local secret_body secret_sum secret_tag
  local rbac_body rbac_sum rbac_tag
  local state message
  local u present_n=0 required_rbac_ok=1

  if [[ -f "$DEMO_MD" ]]; then
    demo_body="Users Part 1 (OCP): OpenShift users and project RBAC for the ACS console plugin demo.

Before/after experience tables for adam, boaz, and chris:
  modules/users-part1-ocp-demo.md
  GUI: /help?doc=users-part1-ocp-demo

Run Part 2 and Part 3 for Act 2 (console vs ACS Central: boaz aligned, chris misaligned)."
  else
    demo_body="Missing demo script: ${DEMO_MD}
GUI: /help?doc=users-part1-ocp-demo"
  fi

  errf="$(mktemp)"
  if ! ensure_oc 2>"${errf}"; then
    err="$(tr '\n' ' ' <"${errf}" 2>/dev/null)"
    rm -f "${errf}"
    emit_status_sections "$demo_body" \
      "OpenShift login failed." "error" "error" \
      "-" "error" "error" \
      "-" "error" "error" \
      "${err:-OpenShift access failed}" "error" "error"
    printf '%s\terror\t%s\n' "$MODULE_ID" "${err:-OpenShift access failed}"
    return 0
  fi
  rm -f "${errf}"

  cred_body="Fixed lab passwords (password = username):"$'\n'
  cred_body+="  adam / ${PW_ADAM}"$'\n'
  cred_body+="  boaz / ${PW_BOAZ}"$'\n'
  cred_body+="  chris / ${PW_CHRIS}"$'\n'
  cred_body+=$'\n'"Cluster htpasswd lines:"$'\n'
  local residue=""
  for u in "${DEMO_USERS[@]}"; do
    if htpasswd_user_present "$u"; then
      cred_body+="  ${u}: present"$'\n'
      present_n=$((present_n + 1))
    else
      cred_body+="  ${u}: MISSING"$'\n'
    fi
    if oc get "user/${u}" >/dev/null 2>&1 || oc get "identity/${IDP_NAME}:${u}" >/dev/null 2>&1; then
      residue+="${u} "
    fi
  done
  if [[ -n "$residue" ]]; then
    cred_body+=$'\n'"OCP User/Identity objects: ${residue}(created on first login; removed on uninstall)"$'\n'
  else
    cred_body+=$'\n'"OCP User/Identity objects: none for adam/boaz/chris"$'\n'
  fi
  cred_sum="${present_n}/3 users"
  if [[ "$present_n" -eq 3 ]]; then
    cred_tag="ok"
  else
    cred_tag="warn"
  fi
  # After uninstall, htpasswd is gone but User/Identity can linger without this check.
  if [[ "$present_n" -eq 0 && -n "$residue" ]]; then
    cred_tag="warn"
    cred_sum="residue"
  fi

  if idp_present; then
    idp_sum="present"
    idp_tag="ok"
    idp_body="IdP ${IDP_NAME} on oauth.config.openshift.io/cluster"
  else
    idp_sum="missing"
    idp_tag="warn"
    idp_body="IdP ${IDP_NAME} not configured"
  fi

  if oc -n "$SECRET_NS" get secret "$SECRET_NAME" >/dev/null 2>&1; then
    secret_sum="present"
    secret_tag="ok"
    secret_body="Secret ${SECRET_NS}/${SECRET_NAME}"
  else
    secret_sum="missing"
    secret_tag="warn"
    secret_body="Secret ${SECRET_NS}/${SECRET_NAME} not found"
  fi

  rbac_body=""
  if oc get clusterrolebinding adam-cluster-admin >/dev/null 2>&1; then
    rbac_body+="adam-cluster-admin: present"$'\n'
  else
    rbac_body+="adam-cluster-admin: MISSING"$'\n'
    required_rbac_ok=0
  fi

  if oc get "project/${MS_NS}" >/dev/null 2>&1; then
    if oc get rolebinding boaz-namespace-admin -n "${MS_NS}" >/dev/null 2>&1; then
      rbac_body+="boaz-namespace-admin (${MS_NS}): present"$'\n'
    else
      rbac_body+="boaz-namespace-admin (${MS_NS}): MISSING"$'\n'
      required_rbac_ok=0
    fi
  else
    rbac_body+="boaz on ${MS_NS}: project missing"$'\n'
    required_rbac_ok=0
  fi

  local ns
  for ns in "$MS_NS" "$INIT_NS"; do
    if oc get "project/${ns}" >/dev/null 2>&1; then
      if oc get rolebinding "chris-admin-${ns}" -n "${ns}" >/dev/null 2>&1; then
        rbac_body+="chris-admin-${ns}: present"$'\n'
      else
        rbac_body+="chris-admin-${ns}: MISSING"$'\n'
        required_rbac_ok=0
      fi
    else
      rbac_body+="chris on ${ns}: project missing"$'\n'
      required_rbac_ok=0
    fi
  done

  if [[ "$required_rbac_ok" -eq 1 ]]; then
    rbac_sum="ready"
    rbac_tag="ok"
  else
    rbac_sum="needs run"
    rbac_tag="warn"
  fi

  emit_status_sections "$demo_body" \
    "$cred_body" "$cred_sum" "$cred_tag" \
    "$idp_body" "$idp_sum" "$idp_tag" \
    "$secret_body" "$secret_sum" "$secret_tag" \
    "$rbac_body" "$rbac_sum" "$rbac_tag"

  if [[ "$cred_tag" == "ok" && "$idp_tag" == "ok" && "$secret_tag" == "ok" && "$rbac_tag" == "ok" ]]; then
    state="ok"
    message="users-part1-ocp ready (adam/boaz/chris; IdP ${IDP_NAME})"
  else
    state="needs-run"
    message="users ${cred_sum}; IdP ${idp_sum}; secret ${secret_sum}; RBAC ${rbac_sum}"
  fi
  printf '%s\t%s\t%s\n' "$MODULE_ID" "$state" "$message"
}

do_run() {
  local errf err tmp
  errf="$(mktemp)"
  if ! ensure_oc 2>"${errf}"; then
    err="$(tr '\n' ' ' <"${errf}" 2>/dev/null)"
    rm -f "${errf}"
    printf '%s\terror\t%s\n' "$MODULE_ID" "${err:-OpenShift access failed}"
    return 1
  fi
  rm -f "${errf}"
  require_bins || {
    printf '%s\terror\tmissing required tools\n' "$MODULE_ID"
    return 1
  }

  if htpasswd_secret_matches; then
    echo "${MODULE_ID}: ${SECRET_NAME} unchanged"
  else
    tmp="$(mktemp)"
    write_htpasswd_temp "$tmp"
    echo "${MODULE_ID}: applying ${SECRET_NS}/${SECRET_NAME}"
    apply_htpasswd_secret "$tmp"
    rm -f "$tmp"
  fi

  echo "${MODULE_ID}: lab logins (password = username):"
  echo "  adam / ${PW_ADAM}"
  echo "  boaz / ${PW_BOAZ}"
  echo "  chris / ${PW_CHRIS}"

  ensure_htpasswd_idp
  ensure_rbac

  printf '%s\tok\tusers-part1-ocp ready (IdP %s; adam/boaz/chris)\n' "$MODULE_ID" "$IDP_NAME"
  return 0
}

do_dry_run() {
  local errf err have_secret="missing" have_idp="missing" secret_note
  errf="$(mktemp)"
  if ! ensure_oc 2>"${errf}"; then
    err="$(tr '\n' ' ' <"${errf}" 2>/dev/null)"
    rm -f "${errf}"
    printf '%s\terror\t%s\n' "$MODULE_ID" "${err:-OpenShift access failed}"
    return 1
  fi
  rm -f "${errf}"

  if oc -n "$SECRET_NS" get secret "$SECRET_NAME" >/dev/null 2>&1; then
    have_secret="present"
  fi
  if idp_present; then
    have_idp="present"
  fi
  if htpasswd_secret_matches; then
    secret_note=" (passwords match; no change)"
  else
    secret_note=" (would apply/update)"
  fi

  cat <<EOF
${MODULE_ID}: dry-run
  Lab logins (fixed): adam/${PW_ADAM} boaz/${PW_BOAZ} chris/${PW_CHRIS}
  Secret ${SECRET_NS}/${SECRET_NAME}: ${have_secret}${secret_note}
  IdP ${IDP_NAME}: ${have_idp}$(
    if [[ "$have_idp" == "missing" ]]; then echo " (would append)"; else echo " (no change)"; fi
  )
  Would ensure RBAC:
    adam-cluster-admin
    boaz-namespace-admin on ${MS_NS} (if project exists)
    chris-admin-<ns> on: $(chris_namespaces | tr '\n' ' ')
  Demo script: ${DEMO_MD}
EOF
  printf '%s\tok\tdry-run only\n' "$MODULE_ID"
}

do_uninstall() {
  local errf err
  errf="$(mktemp)"
  if ! ensure_oc 2>"${errf}"; then
    err="$(tr '\n' ' ' <"${errf}" 2>/dev/null)"
    rm -f "${errf}"
    printf '%s\terror\t%s\n' "$MODULE_ID" "${err:-OpenShift access failed}"
    return 1
  fi
  rm -f "${errf}"

  remove_rbac
  remove_htpasswd_idp
  oc -n "$SECRET_NS" delete secret "$SECRET_NAME" --ignore-not-found=true
  remove_demo_users_and_identities
  wait_for_oauth_rollout

  printf '%s\tok\tremoved IdP, secret, RoleBindings, Users/Identities; oauth rolled out\n' "$MODULE_ID"
  return 0
}

do_uninstall_dry_run() {
  local errf err
  errf="$(mktemp)"
  if ! ensure_oc 2>"${errf}"; then
    err="$(tr '\n' ' ' <"${errf}" 2>/dev/null)"
    rm -f "${errf}"
    printf '%s\terror\t%s\n' "$MODULE_ID" "${err:-OpenShift access failed}"
    return 1
  fi
  rm -f "${errf}"

  echo "${MODULE_ID}: uninstall dry-run"
  echo "  Would delete (if present):"
  if oc get clusterrolebinding adam-cluster-admin >/dev/null 2>&1; then
    echo "    clusterrolebinding/adam-cluster-admin"
  fi
  if oc get rolebinding boaz-namespace-admin -n "${MS_NS}" >/dev/null 2>&1; then
    echo "    rolebinding/boaz-namespace-admin -n ${MS_NS}"
  fi
  local ns
  while IFS= read -r ns; do
    [[ -z "$ns" ]] && continue
    if oc get rolebinding "chris-admin-${ns}" -n "${ns}" >/dev/null 2>&1; then
      echo "    rolebinding/chris-admin-${ns} -n ${ns}"
    fi
  done < <(chris_namespaces)
  if idp_present; then
    echo "    IdP ${IDP_NAME} from oauth cluster"
  fi
  if oc -n "$SECRET_NS" get secret "$SECRET_NAME" >/dev/null 2>&1; then
    echo "    secret/${SECRET_NAME} -n ${SECRET_NS}"
  fi
  local u
  for u in "${DEMO_USERS[@]}"; do
    if oc get "identity/${IDP_NAME}:${u}" >/dev/null 2>&1; then
      echo "    identity/${IDP_NAME}:${u}"
    fi
    if oc get "user/${u}" >/dev/null 2>&1; then
      echo "    user/${u}"
    fi
  done
  echo "    wait for deploy/oauth-openshift rollout in openshift-authentication"
  printf '%s\tok\tuninstall dry-run only\n' "$MODULE_ID"
}

emit_status() {
  local output state
  output="$(do_status)"
  printf '%s\n' "$output"
  state="$(printf '%s\n' "$output" | awk -F'\t' 'NF >= 3 { s=$2 } END { print s }')"
  [[ "$state" != "error" ]]
}

run_module() {
  local dry_run="${1:-false}"
  if [[ "$dry_run" == "true" ]]; then
    do_dry_run
    return
  fi
  do_run
}

uninstall_module() {
  local dry_run="${1:-false}"
  if [[ "$dry_run" == "true" ]]; then
    do_uninstall_dry_run
    return
  fi
  do_uninstall
}

main() {
  local action="" dry_run=false

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --help|-h) usage; exit 0 ;;
      --status) action=status ;;
      --run) action=run ;;
      --uninstall) action=uninstall ;;
      --dry-run) dry_run=true ;;
      --plane)
        shift
        [[ $# -gt 0 ]] || { echo "$(basename "$0"): --plane needs openshift" >&2; exit 1; }
        U1_PLANE="$1"
        case "$U1_PLANE" in
          openshift) ;;
          *)
            echo "$(basename "$0"): OpenShift-only module; --plane must be openshift (got ${U1_PLANE})" >&2
            exit 1
            ;;
        esac
        ;;
      --secured-cluster-id)
        shift
        [[ $# -gt 0 ]] || { echo "$(basename "$0"): --secured-cluster-id needs an id" >&2; exit 1; }
        U1_SC_IDS+=("$1")
        ;;
      --chris-ns)
        shift
        [[ $# -gt 0 ]] || { echo "$(basename "$0"): --chris-ns needs a namespace" >&2; exit 1; }
        CHRIS_EXTRA_NS+=("$1")
        ;;
      *)
        echo "$(basename "$0"): unknown option: $1" >&2
        usage >&2
        exit 1
        ;;
    esac
    shift
  done

  if ((${#U1_SC_IDS[@]} > 1)); then
    echo "$(basename "$0"): OpenShift-only module expects at most one --secured-cluster-id" >&2
    exit 1
  fi
  U1_SC_ID="${U1_SC_IDS[0]:-${ACS_DEMO_SC_ID:-}}"

  [[ -n "$action" ]] || { usage; exit 0; }

  case "$action" in
    status) emit_status ;;
    run) run_module "$dry_run" ;;
    uninstall) uninstall_module "$dry_run" ;;
  esac
}

main "$@"

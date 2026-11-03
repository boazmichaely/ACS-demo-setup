# Users demo script (adam, boaz, chris)

This demo has 2 acts

Act1: OCP users can use the console plugin for vulnerabilities

- Lab module does:
  - define three OpenShift users and passwords
- Your script:
  - No need for any additional setting on ACS. Users see what they are supposed to

Act2: ACS views when logging in with the same users

- Lab module does:
  -  Set up OpenShift OAth in ACS
  - Define roles in ACS and assigning them to users
- Your script:
  - This view is sensitive to ACS roles. If mapped different that OCP, users will see different views - can be confusing.



Lab logins use password equal to username: adam, boaz, and chris.

The ACS console plugin must already be installed. If you do not see
Security in the OpenShift console, enable it under Administration →
Cluster Settings → Configuration → Console → Console plugins
(`advanced-cluster-security`).

## Act 1 - OpenShift Console (Users Part 1 only)

Part 1 is enough for this act. You do not need Part 2 or Part 3.
Console Security follows OpenShift RBAC. ACS Central roles are not
required for the plugin to work in a project the user can open.

Part 1 creates HTPasswd users and OpenShift RBAC:

| User | OpenShift role |
|------|----------------|
| adam | `cluster-admin` (whole cluster) |
| boaz | `admin` on `ms-demo` only |
| chris | `admin` on `ms-demo` and on `acs-init-container-test` (init-demo) |

### Warning: project filter

In Security → Vulnerabilities, if the view is set to **All projects** and
you see an error, switch the filter to **that user's project** (for
example `ms-demo` for boaz, or `acs-init-container-test` for chris).
The default All-projects view is a common false alarm in this demo.

### Act 1 Walkthrough

1. Log into the OpenShift console as **adam** / adam. Open Security →

   Vulnerabilities. Adam can see the whole cluster.
2. Log in as **boaz** / boaz. Open Security on `ms-demo`. He sees that

   namespace. He does not administer other app projects.
3. Log in as **chris** / chris. Show that he administers both `ms-demo`

   and `acs-init-container-test`. On each of those projects, Security
    works for him. Contrast with boaz, who only has `ms-demo`.

## Act 2 - Console vs ACS Central (Users Part 2 + Part 3)

Part 2 adds Login with OpenShift on Central. Part 3 maps the three  
people to ACS roles and scopes. Chris **is done incorrectly on purpose.**

- adam → built-in **Admin** (full ACS)
- boaz → **boaz-in-acs** (Analyst, access scope `ms-demo` only)
- chris → **chris-in-acs** (Analyst, access scope `ms-demo` only - lacks access to `acs-init-container-test`)

Act 2 compares Console access t with what each person sees in ACS  
Central after the ACS mapping.

| | Console (OpenShift RBAC) | ACS Central (ACS roles / scopes) |
|--|--------------------------|-----------------------------------|
| **boaz** (aligned) | Admin on `ms-demo` only → Security works on `ms-demo` | Analyst scoped to `ms-demo` → same namespace story |
| **chris** (misaligned) | Admin on `ms-demo` **and** `acs-init-container-test` → Security works on both | Analyst scoped to `ms-demo` only → init-demo is missing in ACS |

Punch line: when ACS mapping matches OpenShift grants (boaz), console  
and ACS agree. When it does not (chris), Central view is not related to OCP which can be a source of confusion.

### Act 2 Walkthrough

1. Install Part 2, then Part 3.
2. **boaz (aligned):** In the OpenShift console, confirm Security still

   works on `ms-demo`. Log into Central with OpenShift as boaz. Show
    Analyst access limited to `ms-demo`. Console and ACS tell the same
    story.
3. **chris (misaligned):** In the OpenShift console, confirm Security

   still works on both `ms-demo` and `acs-init-container-test`. Log into
    Central as chris. Show Analyst access on `ms-demo`,
    then look for `acs-init-container-test` / init-demo. He cannot see
    that namespace in ACS, even though OpenShift still lets him administer
    it.
4. Optional: log in as adam in Central and show full Admin access.

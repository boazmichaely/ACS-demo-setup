# ACS console plugin demo (lead-in: Users Part 1)

This module is a **lead-in**. It creates OpenShift HTPasswd users and project RBAC.

**Users Part 2 (OAuth) and Users Part 3 (ACS) are required for the complete story.** The ACS console plugin must already be installed on the cluster.

Lab logins (password = username): **adam**, **boaz**, **chris**.

## Phase 1 - OpenShift model only (no ACS user-to-role mapping)

Starts with the OpenShift model only and shows **here's what these users are able to see and not see** in the ACS console plugin. Visibility follows **OCP RBAC / selected namespace** (not ACS scopes yet).

1. Log into the **OpenShift console** as **adam** / `adam`.
2. Open **Security → Vulnerabilities** (ACS console plugin). Select project `ms-demo`, then `acs-init-container-test`, then another project if any.
3. **What adam can see:** vulnerabilities for whichever project he can open (cluster-admin).
4. Log out; log in as **boaz** / `boaz`.
5. **What boaz can see:** plugin vulnerabilities for **`ms-demo`** when that project is selected.
6. **What boaz cannot see / cannot reach:** projects without OCP access (for example `acs-init-container-test` if he is not bound there).
7. Log out; log in as **chris** / `chris`.
8. **What chris can see:** plugin vulnerabilities for **`ms-demo`** and **`acs-init-container-test`**.
9. **What chris cannot see / cannot reach:** namespaces outside that OCP admin set.

With no ACS mapping, OpenShift project access drives what you can open; plugin content is namespace-scoped to the selected project.

## Phase 2 - ACS user mapping, then a different picture

Then we do the **ACS user mapping** and then we see a **different picture**.

1. Run **Users Part 2 (OAuth)** (`users-part2-oauth`) so these same users authenticate to ACS as OpenShift identities.
2. Run **Users Part 3 (ACS)** (`users-part3-acs`) for ACS roles and access scopes for these users. Concrete role/scope names are defined when that module is implemented - update this section then.
3. Repeat the walkthrough: adam → boaz → chris in the ACS console plugin.
4. Call out how ACS mapping changes the picture compared to Phase 1.

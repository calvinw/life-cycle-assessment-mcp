# Deploy Background-Intensity Cache to `main` After Observation

Date: August 17, 2026
Status: **complete**. The observation gate passed, Tier 1 merged to `main` as
`47d9cb9`, and `main` was deployed with the cache enabled on August 18, 2026.

## Current production state

- Deployment branch: `plan/background-intensity-feasibility`
- Active commit: `4f4b5efc1553cb728ed8a0aa67b1b5575bb0a633`
- Active mode: `LCA_BACKGROUND_INTENSITY_CACHE=on`
- Active service: `lca-benchmark` on `lca.mathplosion.com`
- Immediate rollback container: the same commit in `compare` mode
- Pre-feature known-good commit, still redeployable by SHA:
  `aade58d7b595f127e6f4d9101228ff4cf8e376d1`

The BAFU-linked plastic-broom flow was exercised through the GitHub Pages
application in `on` mode. Its base and contribution API calls both returned
`200 OK`; no background-cache warning, mismatch, invariant failure, or API
error was logged.

## One-day observation gate

Leave the deployed branch in `on` mode for approximately one day of ordinary
frontend and REST API use. Before proceeding, confirm all of the following:

- No `Background intensity cache disabled` messages.
- No cache discrepancy, score-reconciliation, or INVARIANT B1 failures.
- No unexpected API errors in the LCA base, contribution, SVG, or normal
  frontend flows.
- BAFU-linked and mock-backed calculations return expected results.
- Memory remains healthy; the active container was approximately 358 MiB at
  the initial check on a 1.9 GiB Droplet.

Useful server log check:

```bash
source .env.deploy
ssh -i "$LCA_DEPLOY_SSH_KEY" -p "$LCA_DEPLOY_PORT" \
  "${LCA_DEPLOY_USER:-root}@${LCA_DEPLOY_HOST}" \
  'docker logs --since 24h lca-benchmark 2>&1 | grep -Ei \
  "background.*(warning|disagree|mismatch|disabled)|invariant b1|error" || true'
```

Review ordinary `POST /api/lca/base` and `POST /api/lca/contribution` entries
as well; successful requests should be `200 OK`.

## Merge and deploy procedure

1. Ensure the observation gate passes.
2. Open a pull request from `plan/background-intensity-feasibility` to `main`.
   Review and merge it using the repository's normal PR process. Confirm the
   resulting `main` commit has been pushed to `origin`.
3. Before deployment, record the active release and verify health:

   ```bash
   source .env.deploy
   ssh -i "$LCA_DEPLOY_SSH_KEY" -p "$LCA_DEPLOY_PORT" \
     "${LCA_DEPLOY_USER:-root}@${LCA_DEPLOY_HOST}" \
     'docker inspect --format "commit={{index .Config.Labels \"com.mathplosion.lca.commit\"}} health={{.State.Health.Status}}" lca-benchmark'
   ```

4. Deploy the pushed `main` branch with the cache explicitly enabled:

   ```bash
   source .env.deploy
   LCA_BACKGROUND_INTENSITY_CACHE=on \
     ./scripts/deploy_lca_server.sh main
   ```

   Image construction occurs while the existing API is online. There is a
   brief interruption only when the script replaces the container. The script
   health-checks the new release and automatically restores the prior container
   if deployment fails.

5. Verify immediately after deployment:

   ```bash
   curl --fail --silent --show-error https://lca.mathplosion.com/api/health
   ```

   Exercise the normal GitHub Pages application, including the BAFU-linked
   plastic broom. Confirm the base and contribution calls return `200 OK` and
   inspect the deployment-period logs for cache warnings.

## Rollback

To restore the immediately preceding release:

```bash
source .env.deploy
./scripts/deploy_lca_server.sh --rollback
```

To redeploy the pre-feature known-good release if required:

```bash
source .env.deploy
./scripts/deploy_lca_server.sh aade58d7b595f127e6f4d9101228ff4cf8e376d1
```

Container rollback preserves the Brightway Docker volume. It does not undo any
intentional changes to persistent Brightway data.


## Outcome — August 18, 2026

### Observation gate: passed

Checked against the branch deployment `4f4b5ef`, healthy and up for roughly 25
hours:

- no `Background intensity cache disabled` messages;
- no cache discrepancy, score-reconciliation, or INVARIANT B1 failures;
- 32 LCA API calls in 24 hours, all `200`. The only non-200 responses were
  `/mcp` protocol handshakes and bot requests for `/`, `/robots.txt`, and
  `/favicon.ico`;
- memory steady at 356 MiB of 1.92 GiB, matching the ~358 MiB baseline.

### Merge and deploy

Tier 1 merged to `main` as `47d9cb9` and pushed. The 75-test suite passed on
the merged `main` before pushing. Tier 2 was deliberately **not** included; it
remains on `plan/tier2-provider-intensities`.

`main` deployed with `LCA_BACKGROUND_INTENSITY_CACHE=on`. Post-deploy
verification:

| Check | Result |
|---|---|
| Container commit | `47d9cb930ae3f4c8613bca5e01878ef64fbfeff6` |
| Health | `healthy` |
| Memory | 295 MiB / 1.92 GiB |
| `POST /api/lca/base`, BAFU broom | `200`, 3.21s, scores unchanged |
| `POST /api/lca/contribution` | `200`, 3.21s |
| Cache warnings after deploy | none |

Scores match the pre-deploy values exactly: climate change `1.70897253`,
acidification `0.006516547`.

### Startup time is at the documented limit

Cache warm-up measured **4.4s** on this deploy and **5.0s** on the previous
container. The plan's stop-for-review trigger was "approximately five seconds
on BAFU", so production sits on that line; locally the same warm-up takes
0.8-2.0s. This is not a regression introduced by the merge — it is the same
code that was already running — but every container restart now spends roughly
five seconds before reporting healthy. Worth revisiting if the background
database grows.

### Rollback

```bash
source .env.deploy
./scripts/deploy_lca_server.sh --rollback          # previous container
./scripts/deploy_lca_server.sh aade58d7b595f127e6f4d9101228ff4cf8e376d1   # pre-feature
```

### Next

Tier 2 (`plan/tier2-provider-intensities`) is implemented but not merged. Its
Phase 3 measurement and Phase 4 REST documentation land before it deploys. The
editor's `realtime` branch ships only after Tier 2 is live, since the Realtime
view needs `background_link_intensities`.

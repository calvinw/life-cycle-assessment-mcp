# Deploy Background-Intensity Cache to `main` After Observation

Date: August 17, 2026
Status: observation in progress; do not merge or redeploy `main` until the
one-day observation gate passes.

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

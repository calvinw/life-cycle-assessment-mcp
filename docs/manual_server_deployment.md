# Manual deployment to the standalone LCA server

The standalone server uses Docker directly. Caddy is installed separately on
the host and continues to provide HTTPS while the application container is
replaced. The deployment scripts do not modify Caddy, DNS, or the firewall.

The server's IP address is public information, so committing it would not be a
credential leak. It is still better not to hard-code it: Droplet addresses can
change, and a hostname or SSH alias keeps the deployment portable. The scripts
therefore require `LCA_DEPLOY_HOST` instead of embedding an address.

## Requirements on a deployment machine

- A clone of this repository.
- Bash, OpenSSH, and an SSH private key accepted by the server.
- The Git commit to deploy must already be pushed to the configured remote
  repository. Local uncommitted changes are never copied to production.

The server needs Git, Docker, `curl`, `flock`, and `tar`. These are already
installed on the current DigitalOcean server.

## Configure a machine

Create an untracked configuration file from the example:

```bash
cp .env.deploy.example .env.deploy
```

Review the values, then load them into the current terminal:

```bash
source .env.deploy
```

The default target is `lca.mathplosion.com`. A DigitalOcean IP address or an
entry from `~/.ssh/config` also works as `LCA_DEPLOY_HOST`.

Do not commit `.env.deploy` or private SSH keys. The example contains no
secrets and is safe to commit.

## Deploy

Deploy the latest pushed `main` branch:

```bash
./scripts/deploy_lca_server.sh
```

Deploy an explicit branch, tag, or commit SHA:

```bash
./scripts/deploy_lca_server.sh release-v1
./scripts/deploy_lca_server.sh 70c26bb5043a4b7118aecf89c24716c90e18d54c
```

The script performs the following sequence:

1. Connects over SSH using normal host-key verification.
2. Fetches the requested Git ref on the server.
3. Builds a clean, versioned Docker image from the pushed commit while the
   existing API remains online.
4. Stops the existing container and retains it as `lca-benchmark-rollback`.
5. Starts the replacement on private address `127.0.0.1:9000`, reusing the
   persistent `lca_benchmark_brightway` volume.
6. Waits up to four minutes for `/api/health`.
7. Restores the previous container automatically if the new release fails.

There is a short outage between stopping the old container and the new health
check succeeding. Image construction happens before this outage.

## Roll back

Swap the active and previous containers:

```bash
./scripts/deploy_lca_server.sh --rollback
```

The rollback is also health-checked. The displaced release becomes the new
rollback target, so the command can be reversed if necessary.

The Brightway Docker volume is shared across releases. Container rollback does
not undo changes to persistent data. Take a volume backup before any release
that intentionally changes the Brightway database format or content.

## Using an SSH alias

An SSH alias avoids repeating usernames, key paths, or nonstandard ports:

```sshconfig
Host lca-production
    HostName lca.mathplosion.com
    User root
    IdentityFile ~/.ssh/id_ed25519
```

Then configure only:

```bash
export LCA_DEPLOY_HOST=lca-production
```

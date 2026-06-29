# Connecting to Claude.ai as a Remote MCP Connector

The LCA MCP server supports two ways to connect to Claude.ai — via the live
production server or via a local cloudflared tunnel from your Mac.

No OAuth or authentication is required. Claude.ai's remote MCP connectors work
on the free tier.

---

## Option 1 — Live server (always on)

The production server runs at `https://lca-mcp.mathplosion.com` (Digital Ocean
droplet, managed by Coolify). It is always available after a successful deploy.

1. Go to **[claude.ai/customize/connectors](https://claude.ai/customize/connectors)**
2. Click **Add custom connector**
3. Fill in:
   - **Name:** `LCA MCP`
   - **URL:** `https://lca-mcp.mathplosion.com/mcp`
   - **Authentication:** None
4. Click **Save**

Claude.ai will connect and list all available tools.

---

## Option 2 — Local server via cloudflared tunnel

Use this when you want to test local changes before deploying, or when the
production server is being redeployed.

### Step 1 — Install cloudflared (once)

```bash
brew install cloudflared
```

### Step 2 — Start the local MCP server

```bash
cd /path/to/life-cycle-assessment-mcp
python sse_server.py
# Server starts on port 9000
```

### Step 3 — Start the tunnel (second terminal)

```bash
cloudflared tunnel --url http://localhost:9000
```

It prints a line like:

```
Your quick Tunnel has been created! Visit it at:
https://random-words-here.trycloudflare.com
```

Copy the `https://….trycloudflare.com` URL.

### Step 4 — Add the connector in Claude.ai

1. Go to **[claude.ai/customize/connectors](https://claude.ai/customize/connectors)**
2. Click **Add custom connector**
3. Fill in:
   - **Name:** `LCA MCP (local)`
   - **URL:** `https://random-words-here.trycloudflare.com/mcp`
     *(replace with your actual tunnel subdomain)*
   - **Authentication:** None
4. Click **Save**

> **Note:** The tunnel URL changes every time you restart cloudflared — you
> will need to update the connector URL each session. Stop the tunnel when done
> to close public access.

---

## How it works

`sse_server.py` runs FastMCP with `transport="streamable-http"` on port 9000.
FastMCP exposes the MCP endpoint at `/mcp` — this is what Claude.ai connects to.

The production server is exposed publicly via Traefik (configured in
`docker-compose.yaml` labels). The local tunnel via cloudflared achieves the
same result by forwarding a public `trycloudflare.com` URL to `localhost:9000`.

---

## Troubleshooting

**Claude.ai shows "Could not connect"**
- Check the server is running: `curl https://lca-mcp.mathplosion.com/api/health`
- For local: make sure both `sse_server.py` and `cloudflared` are running
- Confirm the URL ends in `/mcp` not just the domain root

**Tools not showing up after redeploy**
- The BAFU database downloads on first boot (~80MB). Wait 2-3 minutes after
  deploy before connecting — check Coolify logs for the download completing.

**Tunnel URL expired**
- Restart `cloudflared tunnel --url http://localhost:9000` and update the
  connector URL in claude.ai settings.

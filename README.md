<div align="center">

<img src="web/public/favicon.svg" width="72" height="72" alt="LiteBoard" />

# LiteBoard

**A beautiful, at-a-glance health & operations dashboard for Docker Swarm.**

Crash-loop detection · under-replica alerts · one-click image updates · live per-node metrics · cross-node network consistency — behind Authentik SSO.

</div>

---

## What it does

LiteBoard connects to your Swarm **manager socket** and answers the four questions you'd otherwise SSH in for:

| Tab | Answers |
| --- | --- |
| **Overview** | Which apps are **crash-looping** or **under-replicated** (`0/1`), sorted worst-first, with the last error and restart count. |
| **Updates** | Which service images are **behind their tag** (e.g. `:latest` moved on the registry). Update one service or **all of them in one click**. |
| **Nodes** | Live **CPU, memory, load, disk I/O and network** per node, from a tiny daemon on each host. |
| **Networks** | **Overlay inconsistencies** — IP collisions, subnet mismatches, or a task showing different IPs on different nodes (beyond redundancy). |

Metrics and network data come from a small **Python daemon** that runs on every node. The server reaches out to each daemon, and **every request is cryptographically signed** so nothing but your server can talk to them. Daemons can **self-update** — but only from bundles signed by your server's key.

## Architecture

```
                         ┌──────────────────────────────────────┐
   Browser (Vue SPA) ───▶│  LiteBoard server  (FastAPI, manager) │
      OIDC login  ◀──────│  • /var/run/docker.sock (Swarm mgr)   │
                         │  • OIDC client (Authentik)            │
                         │  • registry manifest checker          │
                         │  • Ed25519 signer (Docker secret key) │
                         └───────┬───────────────────┬───────────┘
             signed HTTP (pull)  │                   │  Docker Registry v2
        ┌───────────────────────┐│                   │  (Hub + private)
        ▼            ▼          ▼▼                   │
   ┌─────────┐  ┌─────────┐  ┌─────────┐             │
   │ daemon  │  │ daemon  │  │ daemon  │   one per node (global service)
   │ node A  │  │ node B  │  │ node C  │   verifies signatures w/ server pubkey
   └─────────┘  └─────────┘  └─────────┘   returns metrics + network state
```

- **Server** — Python + FastAPI + docker-py, serving a Vue 3 SPA. Runs on a manager node.
- **Daemon** — dependency-light Python (`psutil` + `cryptography`), one per node via a `global` service.
- **Metrics are live-only** — held in memory, no database.

### Security model

- A **single stable Ed25519 keypair**. The **private** key is a Docker secret held only by the server. The **public** key is handed to every daemon via its environment.
- Each request the server makes to a daemon is signed over `method + path + timestamp + nonce + body-hash`. Daemons reject anything with a bad signature, a stale timestamp, or a replayed nonce.
- **Self-update** pushes a daemon bundle whose payload is *also* Ed25519-signed; the daemon verifies it against the same public key before atomically replacing itself. There is no unauthenticated update path.

---

## Installation

### Prerequisites

- A Docker Swarm with at least one **manager** node (`docker swarm init` if you don't have one).
- An **Authentik** instance reachable from the server.
- `make` and Python 3.11+ on the machine you run the setup commands from (only for `make keygen`).

### 1. Register LiteBoard in Authentik

1. **Providers → Create → OAuth2/OpenID Provider**
   - Redirect URI: `https://<liteboard-host>/auth/callback`
   - Signing key: your default; scopes: `openid profile email` (add a **groups** scope/mapping if you'll use `LITEBOARD_OIDC_REQUIRED_GROUP`).
2. **Applications → Create** and bind it to the provider above. Note the app **slug**.
3. Copy the **Client ID** and **Client Secret**. Your **issuer** is
   `https://<authentik-host>/application/o/<slug>/` (trailing slash matters).

### 2. Generate the signing keypair

```bash
git clone <this-repo> liteboard && cd liteboard
make keygen        # writes secrets/signing_key, prints LITEBOARD_SERVER_PUBKEY=...
```

### 3. Configure

```bash
cp .env.example .env
$EDITOR .env       # paste the pubkey from step 2, fill in OIDC + base URL + session secret
```

### 4. Create the Swarm secrets

```bash
# Private signing key (from make keygen):
docker secret create liteboard_signing_key secrets/signing_key

# Registry credentials for private images. If you only use public images,
# create an empty one so the stack can start:
echo '{}' | docker secret create liteboard_registry_creds -
#   …or, to check PRIVATE repos, use a real Docker config.json:
#   docker secret create liteboard_registry_creds ~/.docker/config.json
```

> `make secret` runs both of the above for the empty-registry case.

### 5. Build & deploy

```bash
make build         # or: docker compose build
docker stack deploy -c docker-compose.yml liteboard
```

The **server** lands on a manager; the **daemon** rolls out to every node automatically as a `global` service. Daemons publish port `9187` in **host mode**, so the server reaches each one at `<node-ip>:9187` — keep that port firewalled to the cluster (the signatures secure it regardless).

### 6. TLS / reverse proxy

Terminate TLS in front of the published port (`8000`). Example Traefik labels or an nginx `proxy_pass` to `server:8000` both work — just make sure `LITEBOARD_BASE_URL` matches the public HTTPS URL so the OIDC redirect is correct.

### 7. Verify

1. Open `https://<liteboard-host>` → you're redirected to Authentik → sign in → the dashboard loads.
2. **Overview** shows your services; deliberately break one (`docker service scale <svc>=0`) and watch it flag.
3. **Nodes** shows a live gauge card per node with a green *daemon up* badge.
4. **Nodes → Update daemons** pushes a signed self-update; the reported version bumps.
5. **Networks** reports *consistent* (or lists any real inconsistencies).

---

## Local development

```bash
# Backend (auth disabled, live-reload) — needs a reachable Docker socket:
cd server && python -m venv .venv && .venv/bin/pip install -e ".[dev]"
cd .. && make keygen && make dev-server        # http://localhost:8000

# Frontend (Vite dev server, proxies /api to :8000):
cd web && npm install && npm run dev           # http://localhost:5173

# A daemon on your host so the Nodes tab has data:
cd daemon && pip install -r requirements.txt
LITEBOARD_SERVER_PUBKEY=$(grep PUBKEY ../.env | cut -d= -f2) python liteboard_daemon.py

# Tests:
make test
```

Set `LITEBOARD_AUTH_DISABLED=true` to bypass OIDC while developing.

---

## Configuration reference

All settings are environment variables prefixed `LITEBOARD_` (see `server/liteboard/config.py`).

| Variable | Purpose |
| --- | --- |
| `BASE_URL` | Public URL; used to build the OIDC redirect URI. |
| `SESSION_SECRET` | Secret for signing session cookies. |
| `OIDC_ISSUER` / `OIDC_CLIENT_ID` / `OIDC_CLIENT_SECRET` | Authentik OIDC application. |
| `OIDC_REQUIRED_GROUP` | Optional group gate. |
| `SERVER_PUBKEY` | Public key given to daemons (server derives it from the secret too). |
| `DAEMON_PORT` / `DAEMON_SCHEME` | Where/how to reach node daemons. |
| `POLL_INTERVAL` | Seconds between node polls / SSE ticks. |
| `REGISTRY_CONFIG_FILE` | Path to the `liteboard_registry_creds` secret (Docker `config.json`). |
| `AUTH_DISABLED` | Dev only — skip OIDC. |

## Security notes

- **Key rotation:** replace the `liteboard_signing_key` secret and redeploy the stack; the new public key propagates to daemons via the updated env. Rotating rejects old daemons until they receive the new pubkey.
- **Daemon exposure:** prefer firewalling `DAEMON_PORT` to intra-cluster traffic. Signatures already prevent unauthorized use, but least-exposure is still best.
- **Private registries:** provide real credentials through the `liteboard_registry_creds` secret to detect updates for private repos.

## Repository layout

```
server/   FastAPI app, docker-py, OIDC, registry checks, signer, node collector
daemon/   the per-node Python daemon (metrics, netinspect, self-update)
web/       Vue 3 + Vite + Tailwind SPA (+ custom favicon)
scripts/   keygen
docker-compose.yml   the Swarm stack
```

## License

MIT.

<div align="center">

<img src="web/public/favicon.svg" width="72" height="72" alt="LiteBoard" />

# LiteBoard

**A beautiful, at-a-glance health & operations dashboard for Docker Swarm.**

Crash-loop detection · under-replica alerts · one-click image updates · live per-node metrics · silent overlay-fault detection with one-click repair — behind Authentik SSO.

</div>

---

## What it does

LiteBoard connects to your Swarm **manager socket** and answers the four questions you'd otherwise SSH in for:

| Tab | Answers |
| --- | --- |
| **Overview** | Which apps are **crash-looping** or **under-replicated** (`0/1`), sorted worst-first, with the last error and restart count. |
| **Updates** | Which service images are **behind their tag** (e.g. `:latest` moved on the registry). Update one service or **all of them in one click**. |
| **Nodes** | Live **CPU, memory, load, disk I/O and network** per node, from a tiny daemon on each host. |
| **Networks** | **Silent overlay faults** — blackholed VXLAN routes, oversized MTUs, desynced service tables — plus IP collisions and divergent task IPs. Repairable faults get a **fix button**. |

## Why the Networks tab exists

Swarm overlays fail in ways that log nothing. A gossip race leaves one node's VXLAN
forwarding table without a destination for a container that is running perfectly, and
that node — and only that node — drops every packet to it: one proxy replica 504s a
route its peers serve fine. An overlay whose MTU exceeds the tunnel underneath it
passes every handshake and ping while quietly shredding real payloads. A node's copy
of the service table loses a VIP and its DNS answers start coming from the *host's*
upstream resolver instead.

None of these show up in `docker service ps`, and each has historically cost an
afternoon of `tcpdump` and `nsenter`. LiteBoard checks all of them every poll:

| Fault | What it does to you | Fix |
| --- | --- | --- |
| **Blackholed route** | one node silently drops traffic to a healthy container | **button** — rewrites the entry, nothing restarts |
| **Overlay MTU too large** | large packets vanish; every reachability test says "fine" | recreate the network at the suggested MTU |
| **Service DNS desync** | name lookups fail on one node, may resolve to a public IP | restart that node's Docker daemon |
| **Swarm engine degraded** | engine runs, swarm module is dead (e.g. lost a boot race) | restart that node's Docker daemon |
| **Orphaned vxlan interface** | node can't rejoin a network ("file exists") | **button** — deletes the leftover device |
| **DNS egress blocked** | containers on the node can't resolve public names | fix the host's resolvers |

Repair buttons are offered **only** where the fix is targeted and non-disruptive. Anything
that would restart a daemon or rebuild a network is reported with guidance instead, never
wired to a button.

Metrics and network data come from a small **Python daemon** that runs on every node. The server reaches out to each daemon, and **every request is cryptographically signed** so nothing but your server can talk to them.

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
- **Daemon** — dependency-light Python (`psutil` + `cryptography`), one per node via a `global` service. Speaks netlink directly for its namespace probes, so the image needs no `iproute2`.
- **Metrics are live-only** — held in memory, no database.

### Security model

- A **single stable Ed25519 keypair**. The **private** key is a Docker secret held only by the server. The **public** key is handed to every daemon via its environment.
- Each request the server makes to a daemon is signed over `method + path + timestamp + nonce + body-hash`. Daemons reject anything with a bad signature, a stale timestamp, or a replayed nonce.
- **Daemons are updated like any other service** — by rolling out a new image. The daemon exposes no code-update path at all, so there is nothing there to abuse.

---

## Installation

### Prerequisites

- A Docker Swarm with at least one **manager** node (`docker swarm init` if you don't have one).
- An **Authentik** instance reachable from the server (you configure it in the wizard).

That's all — no keys, secrets, or config files to prepare up front.

### 1. Deploy the stack

```bash
docker stack deploy -c docker-compose.yml liteboard
```

The compose file pulls prebuilt multi-arch images from GHCR. The **server** lands on a manager; the **daemon** rolls out to every node automatically as a `global` service and boots *unprovisioned* until the server hands it the signing key. Daemons publish port `9187` in **host mode** — keep it firewalled to the cluster (signatures secure it regardless).

> Deploying to a **multi-node** swarm from a **private** registry? Add `--with-registry-auth` so workers can pull the daemon image.

### 2. Point TLS at the server

Terminate TLS in front of the published port (`8000`) with your reverse proxy (Traefik, nginx `proxy_pass` to `server:8000`, …). You'll enter this public HTTPS URL in the wizard.

### 3. Register LiteBoard in Authentik

1. **Providers → Create → OAuth2/OpenID Provider**
   - Redirect URI: `https://<liteboard-host>/auth/callback`
   - Scopes: `openid profile email` (add a **groups** scope/mapping if you'll use a required group).
2. **Applications → Create** and bind it to the provider. Note the app **slug**.
3. Copy the **Client ID** / **Client Secret**. Your **issuer** is
   `https://<authentik-host>/application/o/<slug>/` (trailing slash matters).

### 4. Run the first-login wizard

Grab the one-time setup token from the server logs:

```bash
docker service logs liteboard_server | grep "Setup token"   # or: make token
```

Open `https://<liteboard-host>` — you'll land on the **setup wizard**. Enter the token, your public URL, and the Authentik issuer / client ID / secret from step 3. On submit LiteBoard validates the issuer, **generates its Ed25519 signing key**, saves config to the `liteboard_data` volume, and restarts. Within a few seconds the server also **pushes the public key to every daemon** over the manager socket — no manual key handling.

### 5. Verify

1. After the wizard, you're redirected to Authentik → sign in → the dashboard loads.
2. **Overview** shows your services; deliberately break one (`docker service scale <svc>=0`) and watch it flag.
3. **Nodes** shows a live gauge card per node with a green *daemon up* badge (daemons flip from *unprovisioned* to up once keyed).
4. **Networks** reports *fabric intact* (or lists real faults). If it shows a
   "Limited visibility" panel, the daemon is missing `SYS_ADMIN`/`NET_ADMIN` or the
   `/run/docker/netns` mount — see below.

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

Normally you configure LiteBoard through the **wizard** — the settings below are
persisted to `config.json` in the `liteboard_data` volume. Every one can also be
overridden by an environment variable prefixed `LITEBOARD_` (env wins over the
saved config; see `server/liteboard/config.py`).

| Variable | Purpose |
| --- | --- |
| `DATA_DIR` | Runtime state dir (config, generated signing key, setup token). Default `/data`. |
| `BASE_URL` | Public URL; used to build the OIDC redirect URI. Set by the wizard. |
| `SESSION_SECRET` | Session-cookie secret. Auto-generated + persisted on first boot if unset. |
| `OIDC_ISSUER` / `OIDC_CLIENT_ID` / `OIDC_CLIENT_SECRET` | Authentik OIDC app. Set by the wizard. |
| `OIDC_REQUIRED_GROUP` | Optional group gate. |
| `SIGNING_KEY_FILE` | Path to the Ed25519 private key. Auto-resolves to `<DATA_DIR>/signing_key`. |
| `DAEMON_PORT` / `DAEMON_SCHEME` | Where/how to reach node daemons. |
| `DNS_PROBE_HOST` | Public name the daemon resolves to check container DNS egress. Empty disables the probe. |
| `DOCKER_NETNS_DIR` | Where Docker's network namespaces are mounted in the daemon (default `/host/docker-netns`). |
| `POLL_INTERVAL` | Seconds between node polls / SSE ticks. |
| `FABRIC_INTERVAL` | Seconds between overlay-fabric probes (default 60 — they cost more than a metrics tick). |
| `REGISTRY_CONFIG_FILE` | Docker `config.json` for private-repo update checks (optional). |
| `AUTH_DISABLED` | Dev only — skip OIDC (treats the server as configured). |

### Advanced: pre-provisioning (skip the wizard)

Set `LITEBOARD_BASE_URL`, all three `OIDC_*` values, **and** provide a signing key
(a `liteboard_signing_key` Docker secret, a bind-mounted `signing_key`, or
`LITEBOARD_SIGNING_KEY`) and the server boots already-configured — no wizard, no
setup token. The daemon key-injection still happens automatically. Generate a key
offline with `make keygen` if you want to pin it yourself.

## Security notes

- **One stable Ed25519 keypair.** The private key is generated at setup into the
  `liteboard_data` volume (or supplied as a Docker secret) and never leaves the
  server. The server delivers the **public** key to every daemon by updating the
  daemon service's env over the manager socket — the signing/verify protocol is
  unchanged, only the delivery is automated.
- **Setup token:** before configuration the wizard is gated by a one-time token
  printed only to the server logs, so an exposed public port can't be hijacked.
- **Key rotation:** delete `signing_key` from the `liteboard_data` volume and
  restart the server (it generates a fresh key and re-pushes the new pubkey to
  all daemons). Old daemons are rejected until they receive the new key.
- **Daemon exposure:** prefer firewalling `DAEMON_PORT` to intra-cluster traffic.
  Signatures already prevent unauthorized use, but least-exposure is still best.
- **Daemon capabilities:** the fabric probes need `SYS_ADMIN` (to enter a network
  namespace) and `NET_ADMIN` (to read and repair forwarding entries), granted in
  `docker-compose.yml`, plus a bind mount of `/proc/1/ns/net` — reading the host
  namespace out of the mounted procfs instead would require `CAP_SYS_PTRACE`. Removing both is supported and non-fatal — the daemon keeps
  running and the Docker-API checks keep working; only the namespace probes go dark,
  which the UI reports rather than passing off as health. Repairs are reachable only
  over the same signed, replay-protected channel as everything else, accept a fixed
  set of actions, and re-verify their preconditions before touching anything.
- **Private registries:** provide credentials via a `liteboard_registry_creds`
  secret (see the commented block in `docker-compose.yml`) to detect updates for
  private repos.

## Repository layout

```
server/   FastAPI app, docker-py, OIDC, registry checks, signer, node collector
daemon/   the per-node Python daemon (metrics, netinspect, fabric probes)
web/       Vue 3 + Vite + Tailwind SPA (+ custom favicon)
scripts/   keygen
docker-compose.yml   the Swarm stack
```

## License

MIT.

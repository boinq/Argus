# Deploy Argus

This guide assumes a Linux host with Docker Engine and the Docker Compose plugin.

## 1. Prepare The Host

```bash
git clone <your-repo-url> argus
cd argus
cp .env.example .env
mkdir -p data
```

Edit `.env` and set:

```bash
ARGUS_PUBLIC_BASE_URL=https://argus.example.dk
ARGUS_TRUSTED_HOSTS=*
ARGUS_BIND_ADDRESS=0.0.0.0
ARGUS_BIND_PORT=8088
ARGUS_FORWARDED_ALLOW_IPS=*
ARGUS_POLICE_RSS_INTERVAL_SECONDS=600
```

With those defaults, Argus is reachable on `http://<host-ip>:8088` from other
devices on the same network. Once you deploy behind a real domain, set
`ARGUS_TRUSTED_HOSTS` to that domain, `localhost`, and `127.0.0.1`.

Use `ARGUS_ROOT_PATH=/argus` only when the proxy serves Argus under a path
prefix instead of a dedicated domain.

## 2. Start Argus

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Or use the helper:

```bash
./deploy.sh
```

Check it:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
curl http://127.0.0.1:8088/api/health
```

The SQLite database is stored at `./data/argus.db` on the host.

## 3. Put A Reverse Proxy In Front

Use `deploy/Caddyfile` or `deploy/nginx.conf` as a starting point.

For Caddy, copy the example into your Caddy config, change
`argus.example.dk`, then reload Caddy.

For Nginx, copy `deploy/nginx.conf` to a site config, change
`argus.example.dk`, enable the site, and reload Nginx. Add TLS with your normal
Let's Encrypt/certbot workflow.

## 4. Update

```bash
git pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

The helper script does this automatically with `git pull --ff-only` before
rebuilding. Set `ARGUS_AUTO_UPDATE=false ./deploy.sh` to skip the pull for a
single run.

## 5. Backup And Restore

Stop writes briefly and copy the SQLite file:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml stop argus
cp data/argus.db "argus-$(date +%Y%m%d-%H%M%S).db"
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

Restore by stopping Argus, replacing `data/argus.db`, and starting it again.

## 6. Useful Commands

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f argus
docker compose -f docker-compose.yml -f docker-compose.prod.yml restart argus
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec argus python -m compileall argus
```

Manual source syncs can be run from the web UI or with:

```bash
curl -X POST http://127.0.0.1:8088/api/scheduler/jobs/greenpowerdenmark-incidents/run
```

# Deploy

The API is published on `127.0.0.1` only (`API_HOST_PORT`, default `8000`). The web UI listens on `127.0.0.1:8080`. Nothing in this compose file publishes the API on `0.0.0.0`. If the host already uses `127.0.0.1:8000`, set `API_HOST_PORT=18000` in `.env`.

`sandbox-image` is a one-shot build (`command: true`). It does not use `restart: unless-stopped`, because that would start it again every time it exits.

## portfolio-server

Inspected before any change, on 2026-10-30:

- Ubuntu 22.04.5, x86_64 (not arm64). About 1 GB RAM, so a 3 GB swap file `/swapfile2` was added before the image build.
- Host nginx already owns 80 and 443 and serves `muhammad-dgr.duckdns.org` from `/etc/nginx/sites-available/portfolio` with certbot. Caddy is not installed and the compose `https` profile was not started.
- `/opt/dogar` already listens on `127.0.0.1:8000`. Tahlil's API is on `127.0.0.1:18000` (`API_HOST_PORT=18000`). The UI is on `127.0.0.1:8080`. iptables accepts 22, 80, and 443, then rejects everything else.
- The site file is `/etc/nginx/sites-available/tahlil`. Certbot added the 443 server and the HTTP redirect. Do not replace that file blindly; keep `proxy_buffering off` and `X-Forwarded-For $remote_addr`.
- The app directory is a git checkout of `Ahmad-dev-top/tahlil` at `/home/ubuntu/tahlil`. Update it with `git pull && docker compose up -d --build` only.

## Inspect the VM first

Run this before changing anything, and keep the output:

```bash
uname -a
cat /etc/os-release
free -h
df -h /
sudo ss -tlpn | grep -E ':80|:443' || true
sudo ss -tlpn
curl -sI http://127.0.0.1 | head -n 20
curl -sI https://muhammad-dgr.duckdns.org | head -n 20
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Ports}}' || true
sudo ufw status verbose || true
sudo iptables -L -n | head -n 80
```

In the Oracle console, open the instance's VCN subnet security list and note the ingress rules for 80 and 443. Do not open 8000.

## Which proxy

If `ss` shows nginx, Caddy, or a container already bound to `0.0.0.0:80` or `:443`, do not start a second proxy. Use the existing site below.

If 80 and 443 are free, use the Caddy profile instead.

## .env on the server

Create `.env` on the server only. Do not commit it.

```bash
umask 077
cat > .env << 'EOF'
LLM_MODEL=anthropic/claude-haiku-5-5
LLM_TEMPERATURE=
LLM_MODE=live
USE_CREWAI=false
SANDBOX_MODE=docker
SANDBOX_MEMORY=256m
ANTHROPIC_API_KEY=paste-the-key-here
TAHLIL_API_KEY=replace-with-openssl-rand-hex-32
PUBLIC_DEMO=true
DAILY_COST_LIMIT_USD=1
ASKS_PER_MINUTE=5
MAX_CONCURRENT_ASKS=1
QUEUE_TIMEOUT_S=110
ALLOW_SQLITE_CONNECTOR=false
CORS_ORIGINS=*
# Only if 127.0.0.1:8000 is already in use on the host. Leave unset otherwise.
# API_HOST_PORT=18000
EOF
openssl rand -hex 32
# put that hex string in TAHLIL_API_KEY, then: chmod 600 .env
```

## 1 GB demo profile

This VM has about 1 GB of RAM and a 450 MB cap on the API container. Uvicorn is one worker (`uvicorn app.api:app`, no `--workers`). CrewAI is off. With it on, the API process stayed against the cap (peaks 417 MiB and 447 MiB on the first two questions) and “What is the total revenue?” took 74.7s. With it off, that question took 41.6s, the next two questions sat near 180 MiB, and every answer was still verified on the first report. `MALLOC_ARENA_MAX=2` did not lower the first-question peak (403 MiB either way), so it is not set. The peak is not well under 350 MB, so the cap stays 450 MB.

`QUEUE_TIMEOUT_S=110` is 2.5 times the p90 of those three CrewAI-off times (16.9s, 34.7s, 41.6s; linear p90 40.2s), rounded up to the next 10 seconds. One question runs at a time. A third request waiting behind the two slower ones still gets a slot.

Measured on 2026-10-30, same three questions, API restarted before each config. Portfolio stayed HTTP 200. `dmesg` had no OOM lines. Host swap used was about 1.6 GB idle and up to about 2.0 GB during a question.

| Config | Total revenue | Highest-revenue region | Order count | API idle | API peak | Host available, min | Swap used, max |
|---|---:|---:|---:|---:|---:|---:|---:|
| A CrewAI on, 450 MB | 74.7s, $0.001327, verified | 43.6s, $0.001584, verified | 26.0s, $0.001238, verified | 254 MiB, 356 MB available, swap 1581 | 447 MiB | 215 MB | 1978 MB |
| B CrewAI off, 450 MB | 41.6s, $0.001250, verified | 34.7s, $0.003126, verified | 16.9s, $0.001145, verified | 298 MiB, 418 MB available, swap 1616 | 403 MiB | 268 MB | 1885 MB |
| C CrewAI off, 450 MB, `MALLOC_ARENA_MAX=2` | 45.5s, $0.001451, verified | 33.0s, $0.002943, verified | 16.9s, $0.001210, verified | 260 MiB, 426 MB available, swap 1615 | 403 MiB | 245 MB | 1891 MB |

Every row is `report_attempts` 1. Config B is what the server runs. Config D (350 MB cap) was not run: B's peak of 403 MiB is not well under 350.

## Install Docker (if missing)

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker "$USER"
```

Log out and back in so the `docker` group applies. Ampere images must be built on the VM (or with `--platform linux/arm64`). `docker compose build` on the VM does that.

## Start

```bash
git clone https://github.com/Ahmad-dev-top/tahlil.git
cd tahlil
# write .env as above
docker compose up -d --build
```

Add `--profile https` only when 80/443 are free and `TAHLIL_DOMAIN=tahlil.muhammad-dgr.duckdns.org` is set in `.env`.

## Existing proxy (portfolio already on 80/443)

Leave the Caddy service off. Point the existing proxy at `127.0.0.1:8080`.

nginx example, in its own file so the portfolio server block is untouched:

```nginx
server {
    listen 80;
    server_name tahlil.muhammad-dgr.duckdns.org;
    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_read_timeout 300s;
    }
}
```

Then get a certificate the same way the portfolio did. If that is certbot:

```bash
sudo certbot --nginx -d tahlil.muhammad-dgr.duckdns.org
```

If the portfolio uses Caddy, add a site block for `tahlil.muhammad-dgr.duckdns.org` that reverse-proxies to `127.0.0.1:8080`, and reload Caddy. Do not change the portfolio site block.

Check the portfolio before and after:

```bash
curl -fsS -o /dev/null -w '%{http_code}\n' https://muhammad-dgr.duckdns.org
```

## Checks

```bash
curl -fsS -o /dev/null -w '%{http_code}\n' https://tahlil.muhammad-dgr.duckdns.org
curl -fsS https://tahlil.muhammad-dgr.duckdns.org/api/health
curl -s -o /dev/null -w '%{http_code}\n' -X POST https://tahlil.muhammad-dgr.duckdns.org/api/datasets/connect \
  -H 'content-type: application/json' -d '{"url":"postgresql://u:p@127.0.0.1/db"}'
# from a machine that is not the VM: port 8000 must fail
curl -m 5 -sv http://tahlil.muhammad-dgr.duckdns.org:8000/health
```

`/api/health` should include `"public_demo": true`. Connect should be 403. The sample dataset "Sample: Pakistan sales 2025" should be in `GET /api/datasets`.

To prove the daily cap, set `DAILY_COST_LIMIT_USD=0.001`, `docker compose up -d`, ask twice (the first may succeed; the second should be HTTP 429 `Daily demo budget reached, try again tomorrow`), then set the limit back to `1` and recreate the API container.

## Update

From the git checkout on the server, this is the whole update:

```bash
cd ~/tahlil
git pull && docker compose up -d --build
```

## Logs

```bash
docker compose logs -f api web
docker compose ps
```

## Rotate the API key

```bash
openssl rand -hex 32
# put the new value in TAHLIL_API_KEY in .env
docker compose up -d
```

The browser never sees this key. nginx injects it on `/api/`. Restarting `web` and `api` picks up the new value. Old key stops working immediately.

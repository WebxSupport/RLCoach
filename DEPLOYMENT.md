# RLCoach — Deployment Guide (AWS Lightsail → whatasave.xyz)

Workflow assumed: **Lightsail in-browser SSH** + code pulled from **GitHub** (no local SSH key,
no rsync). Amplify is NOT viable (static/serverless only — can't run Docker, Python, background
jobs, SQLite, or the rrrocket binary). Lightsail runs the existing container as-is.

---

## Part A — In the Lightsail web console (one-time)

1. **Create instance:** Create instance → region (London `eu-west-2` if UK) → Linux/Unix →
   OS Only → **Ubuntu 24.04 LTS** → **$12/mo plan (2 GB RAM)** → name `rlcoach`.
   - Do NOT use $5/$7 (512 MB/1 GB) — carball parsing spikes 400–600 MB/replay and will OOM-kill.
   - The $12 plan bundles **60 GB SSD** — that's all the storage you need; nothing to attach.
2. **Static IP:** Networking → Static IPs → Create → attach to `rlcoach`.
3. **Firewall** (Networking → Firewall): allow TCP **80** and **443** from Anywhere; restrict TCP
   **22** to your IP. NEVER expose 8000 — nginx proxies to it internally.
4. **DNS** (at your domain registrar for whatasave.xyz): A record `@` → static IP, A record
   `www` → static IP. Verify with `dig whatasave.xyz` (up to 30 min to propagate).
5. **Snapshots** (Snapshots tab): enable Automatic snapshots — this is your backup (the root disk
   dies with the instance).

Everything below runs in the **browser SSH terminal**: instance → **Connect using SSH** button.
You're logged in as `ubuntu` — there is no separate `ssh` step.

---

## Part B — In the browser SSH terminal

### Step 1 — Install dependencies

```bash
sudo apt update && sudo apt upgrade -y
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker ubuntu && newgrp docker
sudo apt install -y docker-compose-plugin nginx certbot python3-certbot-nginx
```
> If a later `docker` command says "permission denied", just close and reopen the
> Connect-using-SSH window (re-applies the docker group), then carry on.

### Step 2 — Clone the repo from GitHub

The repo is public, so this is a plain clone:
```bash
cd /home/ubuntu
git clone https://github.com/WebxSupport/RLCoach.git rlcoach
cd rlcoach
ls -la            # sanity check: you should see .env.example, Dockerfile, rlcoach/, etc.
```

> If you later switch the repo to **private**, clone with a GitHub Personal Access Token instead:
> `git clone https://ghp_YOURTOKEN@github.com/WebxSupport/RLCoach.git rlcoach`
> (github.com → Settings → Developer settings → Personal access tokens → Tokens (classic) → `repo` scope).

### Step 3 — Create the secrets file (.env)

This auto-generates the encryption key inline (so you never copy it) and leaves only the
Anthropic key to paste:
```bash
mkdir -p data
cat > .env << EOF
ANTHROPIC_API_KEY=PASTE_YOUR_ANTHROPIC_KEY_HERE
ENCRYPTION_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
SECURE_COOKIES=true
ALLOWED_ORIGINS=https://whatasave.xyz,https://www.whatasave.xyz
DAILY_ANALYSIS_LIMIT=5
EOF
```

Now paste your real Anthropic key in place of the placeholder:
```bash
nano .env        # edit the ANTHROPIC_API_KEY line → Ctrl+O, Enter, Ctrl+X to save
chmod 600 .env
```

### Step 4 — Build & start

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
docker compose ps                 # container should be "running"/"healthy"
curl http://localhost:8000/api/me # sanity check → {"logged_in":false}
```
First build takes ~3–5 min (installs deps + downloads the rrrocket Linux binary).

### Step 5 — nginx + HTTPS

```bash
sudo cp /home/ubuntu/rlcoach/nginx.conf /etc/nginx/sites-available/rlcoach
sudo sed -i 's/YOUR_DOMAIN/whatasave.xyz/g' /etc/nginx/sites-available/rlcoach
sudo sed -i 's/server_name whatasave.xyz;/server_name whatasave.xyz www.whatasave.xyz;/g' \
  /etc/nginx/sites-available/rlcoach

sudo ln -s /etc/nginx/sites-available/rlcoach /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx

sudo certbot --nginx -d whatasave.xyz -d www.whatasave.xyz \
  --non-interactive --agree-tos -m your@email.com
sudo certbot renew --dry-run       # confirm auto-renewal works
```
Now `https://whatasave.xyz` serves the app.

### Step 6 — Auto-start on reboot

```bash
sudo tee /etc/systemd/system/rlcoach.service > /dev/null << 'EOF'
[Unit]
Description=RLCoach
After=docker.service
Requires=docker.service

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/rlcoach
ExecStart=docker compose -f docker-compose.yml -f docker-compose.prod.yml up
ExecStop=docker compose -f docker-compose.yml -f docker-compose.prod.yml down
Restart=on-failure
RestartSec=15

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload && sudo systemctl enable rlcoach
```

### Step 7 — DB backup (optional, on top of snapshots)

```bash
crontab -e
# add:
0 3 * * * sqlite3 /home/ubuntu/rlcoach/data/rlcoach.db ".backup '/home/ubuntu/rlcoach/data/backup.db'"
```

---

## Updating after code changes

Push from your PC as normal (edit in `C:\Users\lukeb\Desktop\RLCoach` → `git push`), then in
the **browser SSH terminal**:
```bash
cd /home/ubuntu/rlcoach
git pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```
Your `.env` and `data/` are git-ignored / volume-mounted, so they survive every update.
> If you later make the repo private and `git pull` asks for credentials, refresh the stored token:
> `git remote set-url origin https://ghp_NEWTOKEN@github.com/WebxSupport/RLCoach.git`.

---

## Troubleshooting

| Symptom | Check |
|---------|-------|
| `git clone` asks for username/password | Private repo — use the `ghp_TOKEN@` URL form (Step 2) |
| `docker: permission denied` | Close/reopen the Connect-using-SSH window, retry |
| 502 Bad Gateway | `docker compose ps` (up?) · `docker compose logs --tail=50` |
| Parse OOM-killed | Confirm $12 (2 GB) plan, not $5/$7 · `dmesg | grep -i oom` |
| Cert renewal fails | Port 80 open in firewall? `sudo certbot renew --dry-run` |
| SSE progress stalls | nginx `proxy_buffering off` present (it is in nginx.conf) |
| Epic auth loops | RL patch changed constants — update `rlapi/psynet.py` (handover §constants) |
| Login fails after redeploy | Changing `ENCRYPTION_KEY` invalidates stored Epic tokens (users reconnect Epic) — but NOT passwords (scrypt-hashed separately). Keep the key stable. |
| Disk filling up | `docker system prune -af` to clear old image layers |
```

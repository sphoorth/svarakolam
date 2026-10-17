# Upload SvaraKolam to your own server

This package is for a **Python-capable VPS, dedicated server, or Docker host**. Uploading it to a static website folder or ordinary PHP-only shared hosting will not run the FastAPI backend. The instructions below assume a Linux VPS with SSH access and a domain/subdomain, such as `kolam.yourdomain.com`.

Start with roughly **2 CPU cores, 4 GB RAM, and 10 GB free disk space** for a small private studio; this is a planning estimate, not a measured minimum. Analysis uses CPU and video encoding uses FFmpeg. GPU support is optional and is not included in the default Docker image.

## 1. Prepare your server

Install Docker Engine and the Docker Compose plugin using [Docker's official installation instructions](https://docs.docker.com/engine/install/). Verify:

```bash
docker --version
docker compose version
```

Commands below assume your SSH user is allowed to run Docker; otherwise prefix Docker commands with `sudo` according to your server's existing administration setup.

Point the domain's **A record** to the server's public IPv4 address. Only create an AAAA record if IPv6 actually reaches the server. Allow inbound TCP **80 and 443** in your hosting-provider firewall. Keep SSH access available. Port 8000 remains bound to loopback and does not need to be opened publicly.

If another web server already occupies ports 80/443, use the existing-proxy alternative below instead of starting the bundled Caddy service.

## 2. Upload and extract the ZIP

From your own computer, upload `SvaraKolam-server.zip` with an SFTP client or SCP:

```bash
scp SvaraKolam-server.zip youruser@YOUR_SERVER_IP:~/
```

Then SSH into the server and extract it:

```bash
ssh youruser@YOUR_SERVER_IP
unzip SvaraKolam-server.zip
cd svarakolam
```

Install your distribution's `unzip` package if the command is unavailable. Extract a new release into a new directory if you already have a folder named `svarakolam`; do not overwrite an existing `.env` unintentionally.

## 3. Set your domain and studio login

Generate a password hash interactively. Type your chosen password at the prompt:

```bash
docker run --rm -it caddy:2-alpine caddy hash-password
cp .env.example .env
chmod 600 .env
nano .env
```

Set these three values, replacing the placeholders:

```dotenv
DOMAIN=kolam.yourdomain.com
BASIC_AUTH_USER=admin
BASIC_AUTH_HASH='PASTE_THE_GENERATED_HASH_HERE'
```

Use the generated hash, **not the plain password**, and retain the single quotes around the hash. No default password is provided. This login protects the entire studio, including API calls, uploaded audio, and exports. It is a shared private-studio login, not separate user accounts or per-user file isolation. [Caddy authentication documentation](https://caddyserver.com/docs/caddyfile/directives/basic_auth), [Compose environment-file quoting](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/).

## 4. Build and start

```bash
docker compose -f compose.yaml -f compose.server.yaml config --quiet
docker compose -f compose.yaml -f compose.server.yaml up -d --build
docker compose -f compose.yaml -f compose.server.yaml ps
```

The first build downloads Python dependencies and may take several minutes. The app uses one Uvicorn worker; Caddy starts after the app becomes healthy. With working DNS and reachable ports, Caddy obtains and renews HTTPS certificates automatically. [Caddy HTTPS documentation](https://caddyserver.com/docs/automatic-https/).

Open **https://kolam.yourdomain.com** and enter the username and password you chose. Upload a real 30–60 second clip, then test playback, SVG export, and MP4 export. Musical controls are collapsed under Advanced settings.

Check process health from the server:

```bash
curl --fail http://127.0.0.1:8000/api/health
```

Expected response: `{"status":"ok","version":"1.0.0"}`.

## Operating the studio

View logs:

```bash
docker compose -f compose.yaml -f compose.server.yaml logs --tail=100 app caddy
```

Stop without deleting retained data:

```bash
docker compose -f compose.yaml -f compose.server.yaml down
```

Restart the app:

```bash
docker compose -f compose.yaml -f compose.server.yaml restart app
```

After replacing application source with a newer release, rebuild:

```bash
docker compose -f compose.yaml -f compose.server.yaml up -d --build
```

Preserve your `.env` and the Docker volumes when updating. `audio_data` stores normalized WAVs and exports, while Caddy's volumes retain certificates. **Jobs and session indexes remain in memory**: restarting the app invalidates active sessions, even when their files remain on disk. Wait for an export to finish before restarting. The container allows up to five minutes for graceful shutdown.

Original uploads are removed after analysis. Derived files are retained up to the application's 24-hour cleanup window (cleanup runs on new uploads and at startup as described in README). The in-app delete button removes an idle session sooner. Twelve sessions and two background threads bound the private studio's workload. Do not increase Uvicorn workers or run multiple app replicas with this in-memory registry.

## If you already use Nginx, Caddy, or a hosting dashboard

Run only the app container:

```bash
docker compose up -d --build
```

Configure your existing HTTPS proxy to forward **all paths** for a dedicated domain/subdomain to `http://127.0.0.1:8000`, with an HTTP request-body allowance of at least 34 MB and password protection. A dedicated subdomain avoids rewriting the app's absolute `/api` and asset paths. Do not start the bundled Caddy container if another proxy already owns 80/443.

An existing Nginx virtual host can use this location block (configure HTTPS and authentication on that virtual host as usual):

```nginx
location / {
    client_max_body_size 34m;
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 300s;
}
```

If your hosting dashboard runs its proxy inside a container, its `127.0.0.1` is not the host. Attach it to the app's Docker network and proxy to `app:8000`, or use the dashboard's documented host-gateway mechanism. The default Dockerfile trusts forwarded headers because the app is reached only through the trusted proxy/loopback configuration; do not expose port 8000 directly to the Internet.

For temporary private access without a domain, run only `docker compose up -d --build`, then create an SSH tunnel from your computer:

```bash
ssh -L 8001:127.0.0.1:8000 youruser@YOUR_SERVER_IP
```

Open `http://127.0.0.1:8001` locally while the SSH session stays connected. This does not publish the app publicly.

## Troubleshooting

- **Site does not open:** verify DNS, provider firewall, and whether something else is using ports 80/443. Inspect Caddy logs for certificate errors.
- **HTTP 401:** use the password you typed when generating the hash, not the hash itself. Check `.env` quoting and username.
- **HTTP 413:** the app accepts files up to 32 MiB; every upstream proxy also needs the configured 34 MB allowance for the complete multipart request.
- **Slow first analysis:** pYIN compiles numerical kernels on first use. CPU-only mode is expected in this image. GPU fallback warnings do not indicate a failed upload.
- **Video fails:** inspect app logs and available disk space. System FFmpeg and a Unicode-capable font are installed in the container.
- **Unknown/expired session after restart:** upload the clip again; sessions are not restart-persistent.
- **Session limit reached:** delete an idle session from its open studio tab, or wait for cleanup. Restarting invalidates all active sessions.
- **Container build fails:** check outbound access to Debian package repositories and PyPI, free disk space, and Docker logs.

## Verification status and scope

The Python application has passed its structural/API and real-recording tests on Windows, including actual audio/video exports and all four accepted audio formats. The upload ZIP is checked for required files, archive integrity, and exclusion of local audio/runtime artifacts. **Docker is unavailable on the packaging computer, so this image has not been built or run here**; run the build, health check, and one real audio export on your server before relying on it.

This deployment targets a small password-protected studio. An unrestricted public multiuser service still requires persistent job/session storage, account isolation, and per-user resource quotas. Python code is packaged for installation, not as a prebuilt executable or prebuilt container image. The server needs Internet access during the first build; Google Fonts are optional frontend requests with local font fallbacks.

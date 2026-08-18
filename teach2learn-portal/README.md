# EquitableT2L Portal

A compact FastAPI portal for guided conversations with subject-specific model adapters. The UI, API, SQLite state, survey feedback, and server-side inference live in one maintainable UV project.

## Local development

Python 3.11+ and [UV](https://docs.astral.sh/uv/) are required. Model weights are never downloaded by the setup scripts; point the environment at weights that already exist on the inference server.

```bash
cp .env.example .env
uv sync --dev
./scripts/run.sh --reload
```

Open <http://127.0.0.1:8000>. Run checks with `uv run pytest`.

On a machine that already has a production `.env`, do not overwrite it. Use `.env.local` plus `./scripts/run-local.sh` instead: it reads only `.env.local`, keeps its database under `data-local/`, and runs the scripted `fake` inference backend so no GPU or model weights are needed. Because Google OAuth is not configured locally, set `T2L_DEV_LOGIN_ENABLED=true` and open `/dev/login` to sign in as a throwaway participant. That route is never registered when `APP_ENV=production`.

## Multilingual sessions

Participants pick a teaching language on the topic-selection form. Sarvam AI translates only participant-visible text: the user's typed answer into English on the way in, and the learner's question, completion message, and final feedback back out. Inference, the private `<evaluation>` block, Bloom completion logic, and everything written to the database and transcripts stay English so research analysis is unaffected.

The OpenRouter judge runs inside the English zone: it reads the translated-to-English answer and returns English feedback, which is then translated back out. A silent translation passthrough therefore degrades evaluation quality as well as readability, and because evaluation drives Bloom completion, affected sessions may run to `max_turns` instead of completing early. Treat `translation_failed` warnings appearing next to `openrouter_turn_evaluation_failed` as one problem, not two.

Set `SARVAM_API_KEY` to enable it. With no key, or when the API errors or times out, every call falls back to the original text and the session continues in English. `T2L_TRANSLATION_BACKEND=echo` prefixes text with the target language code, which exercises the boundary locally without a key. Keep `SARVAM_MODEL=sarvam-translate:v1`: it accepts 2000 input characters, matching the portal's input cap, while `mayura:v1` accepts only 1000.

## Configuration

Copy `.env.example` to `.env` and change values there. Keep `.env` private; it may contain deployment-specific paths and secrets. `T2L_LOG_LEVEL` controls verbosity and `T2L_LOGGING_ENABLED=false` disables application logging. Leave `T2L_LOG_FILE` empty to use the systemd journal, or set it to a writable path for an additional file log.

The application stores its SQLite database and JSONL transcripts below `T2L_DATA_DIR`. Set `INFERENCE_ADAPTER_ROOT` and, when needed, the per-model `INFERENCE_*_BASE_MODEL` variables to resources already present on the server. The app fails clearly when a requested model resource is unavailable rather than downloading one implicitly.

Each successful assistant transcript record keeps the cleaned participant-facing question plus the raw model output, parsed private Bloom level, score, strength, improvement, judge metadata, and generation latency. These private fields support later analysis but are never rendered in the participant chat. Production uses an isolated OpenRouter judge for turn-level and final feedback when configured, with a local evaluator as fallback.

## Ubuntu server deployment

The scripts use a regular UV environment, systemd, and optional Nginx—Docker and the NVIDIA Container Toolkit are unnecessary.

1. Install system packages: `sudo apt-get update && sudo apt-get install -y rsync nginx`.
2. Install UV for the service account: `curl -LsSf https://astral.sh/uv/install.sh | sh` (or use `wget -qO- ... | sh` when curl is unavailable).
3. From this machine, run `REMOTE_HOST=user@server ./scripts/deploy.sh`. The default target is `/data/scratch/sanyam_jain_2022/teach2learn-portal`; override it with `REMOTE_DIR`.
4. On the server, run `cd /data/scratch/sanyam_jain_2022/teach2learn-portal && cp .env.example .env`, then edit paths and the secret. Run `uv sync --frozen --no-dev`, or set `APP_PYTHON` to an existing inference environment that already has CUDA, Transformers, PEFT, and the small web dependencies; this avoids duplicating the model environment.
5. For the current GPU-host deployment, enable user lingering with `loginctl enable-linger "$USER"`, then run `./scripts/install-user-services.sh`. Follow the controlled startup and verification procedure in [Production operations](docs/production-operations.md). The older `deploy/teach2learn.service` remains available for installations that deliberately use a root-managed system service.
6. Optionally copy `deploy/nginx.conf` to `/etc/nginx/sites-available/teach2learn`, enable it, verify with `sudo nginx -t`, and reload Nginx.

Inspect the production services with `systemctl --user status teach2learn-vllm.service teach2learn-portal.service`. Re-deployments are additive: the sync script intentionally never uses `--delete`, never overwrites the server `.env`, database, transcripts, weights, or logs, and does not restart services. After reviewing a sync, restart only the affected user service. See [Production operations](docs/production-operations.md) for exact commands, health checks, logs, startup behavior, and recovery.

Run a live adapter check on the GPU host with `INFERENCE_BACKEND=transformers python scripts/smoke_models.py`. It opens a lesson and performs two changing teacher/student turns through every configured model, unloading each model before loading the next one.

## Cloudflare Tunnel

For a temporary development URL, install `cloudflared` and run `cloudflared tunnel --protocol http2 --url http://127.0.0.1:8000`. The generated `trycloudflare.com` hostname is random and cannot be reserved. Cloudflare requires outbound TCP port 7844 for HTTP/2 or outbound UDP port 7844 for QUIC; the tunnel cannot connect if both are blocked by the server network.

For a stable hostname, add a domain to Cloudflare, create a named tunnel in the Cloudflare dashboard, map the desired hostname to `http://127.0.0.1:8000`, put the issued token in the private server `.env` as `CLOUDFLARE_TUNNEL_TOKEN`, and run `cloudflared tunnel --no-autoupdate run --token "$CLOUDFLARE_TUNNEL_TOKEN"`. Never commit the token.

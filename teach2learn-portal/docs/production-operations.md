# Production operations

EquitableT2L runs on the GPU host as two persistent systemd user services. User lingering is enabled for `sanyam_jain_2022`, so the services start during boot and remain managed without an interactive SSH session.

## Process architecture

`teach2learn-portal.service` runs the FastAPI portal on `127.0.0.1:8010`. It loads the protected `.env`, owns the portal process group, and restarts the portal after any exit.

`teach2learn-vllm.service` runs one parent supervisor. The supervisor starts the five model engines sequentially so model loading and CUDA graph capture do not contend at boot:

| Profile | Port | GPU | Base model |
| --- | ---: | ---: | --- |
| Qwen3 | 18101 | 0 | `Qwen/Qwen3-8B` |
| Gemma 2 | 18102 | 1 | `google/gemma-2-9b-it` |
| Mistral | 18103 | 2 | `mistralai/Mistral-7B-Instruct-v0.3` |
| Granite | 18104 | 3 | `ibm-granite/granite-3.3-8b-instruct` |
| Qwen 2.5 | 18105 | 0 | `Qwen/Qwen2.5-7B-Instruct` |

Each vLLM server owns an EngineCore and resource-tracker child process. Those children are expected: unrelated base models require separate vLLM engines, while each engine shares its loaded base model across the four subject LoRA adapters. All children belong to the `teach2learn-vllm.service` control group, so stopping or restarting that unit controls the complete inference stack.

The relay VM terminates public HTTPS and forwards traffic through the scoped SSH relay to portal port 8010. It does not host inference.

## Service management

Run service commands as `sanyam_jain_2022`; do not use `sudo systemctl` for these user units.

```bash
systemctl --user status teach2learn-vllm.service teach2learn-portal.service
systemctl --user restart teach2learn-portal.service
systemctl --user restart teach2learn-vllm.service
systemctl --user stop teach2learn-portal.service teach2learn-vllm.service
systemctl --user start teach2learn-vllm.service teach2learn-portal.service
```

Both units use `Restart=always`. The vLLM supervisor also restarts an individual failed engine without disturbing healthy engines. systemd restarts the full supervisor if its parent process exits. `KillMode=control-group` prevents orphaned engine processes after a service stop or restart.

The portal declares the vLLM service as a dependency. The model supervisor becomes active before every model finishes loading, so allow roughly four minutes after a cold GPU-stack start. Its staggered sequence is Gemma 2, Mistral, Granite, Qwen3, then Qwen 2.5.

## Installation and boot persistence

The durable unit definitions live in `deploy/user/`. Install or refresh them after changing a unit file:

```bash
cd /data/scratch/sanyam_jain_2022/teach2learn-portal
loginctl show-user "$USER" -p Linger
./scripts/install-user-services.sh
systemctl --user daemon-reload
systemctl --user restart teach2learn-vllm.service teach2learn-portal.service
```

`Linger=yes` is required for automatic startup before login. Enable it once with `loginctl enable-linger "$USER"`. The installer refuses to proceed when lingering is disabled.

## Health verification

Process existence is insufficient; verify every HTTP endpoint:

```bash
python - <<'PY'
import urllib.request

for port in (8010, 18101, 18102, 18103, 18104, 18105):
    response = urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5)
    print(port, response.status)
PY

curl -fsS https://learnbyteaching.sasanktumpati.com/health
```

All six local endpoints and the public endpoint must return HTTP 200. Validate real generation after inference changes:

```bash
cd /data/scratch/sanyam_jain_2022/teach2learn-portal
set -a
source .env
source deploy/oauth.env
set +a
/data/scratch/sanyam_jain_2022/mistral_finetune/.qwendt/bin/python scripts/smoke_models.py
```

The smoke script must report `PASS` for all five profiles.

## Logs and diagnostics

Follow systemd lifecycle and portal logs with:

```bash
journalctl --user -u teach2learn-portal.service -f
journalctl --user -u teach2learn-vllm.service -f
systemctl --user show teach2learn-vllm.service -p MainPID -p ActiveState -p SubState -p NRestarts
systemctl --user show teach2learn-portal.service -p MainPID -p ActiveState -p SubState -p NRestarts
```

Per-engine vLLM output remains in `logs/vllm-<profile>.log`. The systemd-managed portal writes to the journal unless `T2L_LOG_FILE` explicitly enables an additional file. Never log or print `.env`, OAuth credentials, or the OpenRouter key.

## Deployment procedure

`scripts/deploy.sh` synchronizes code additively. It excludes `.env`, OAuth secrets, databases, transcripts, logs, model weights, and caches, and it does not restart anything.

1. Run local tests and lint checks.
2. Deploy with `REMOTE_HOST=... ./scripts/deploy.sh`.
3. Restart `teach2learn-portal.service` for application-only changes.
4. Restart `teach2learn-vllm.service` only for model-engine, adapter, or vLLM configuration changes.
5. Wait for all five model health endpoints after a vLLM restart.
6. Run the public health check and the five-model smoke test.

Avoid restarting the vLLM service for HTML, CSS, database, feedback, or portal Python changes; restarting only the portal preserves warm model engines and limits downtime to a few seconds.

## Recovery

If one model endpoint fails, first inspect its log and the parent service status. The child loop normally retries it after five seconds.

```bash
tail -n 200 logs/vllm-qwen3.log
systemctl --user status teach2learn-vllm.service
```

If the parent is unhealthy, restart the vLLM service and wait for all five ports. If the public site fails but local port 8010 is healthy, inspect the relay tunnel and relay Nginx rather than restarting inference. If the portal fails startup, inspect its journal for configuration or storage-integrity errors before restarting it repeatedly.

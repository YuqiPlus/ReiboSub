# Security

## Local-first deployment

Video Translate is a trusted-user, local workflow tool. The Web UI does not
provide accounts, login, tenant isolation, or authorization. It can start
downloads and processing jobs and can write files under configured project
directories.

The server therefore listens on `127.0.0.1` by default. Do not expose it
directly to the public Internet. For a remote machine, keep the loopback bind
and use an SSH tunnel:

```bash
ssh -L 7860:127.0.0.1:7860 user@server
```

Then open `http://127.0.0.1:7860` locally. If you deliberately bind to
`0.0.0.0`, use only a trusted LAN or put an authenticated HTTPS reverse proxy
in front of the service.

## Secrets and local data

The following paths are local-only and ignored by Git:

- `.env*` except `.env.example`
- `configs/provider_secrets.yaml`
- `configs/providers/*.yml` and `*.yaml`
- `configs/app_settings.yaml`, `configs/local_runtime.yaml`
- `configs/llm.yaml`, `configs/run.yaml`
- `YoutubeDownloads/`, `outputs/`, `models/`
- generated media, subtitle, log, key, and certificate files

Provider keys entered in Settings are stored in
`configs/provider_secrets.yaml` with mode `0600`. The backend returns only
whether a key exists and never returns the key value to the browser. Enter
credentials only over loopback, SSH forwarding, or trusted HTTPS.

Before publishing a branch, review both tracked and staged files:

```bash
git status --short --ignored
git diff --check
git diff --cached --name-only
git grep -nE '/home/|/Users/|/data/|API_KEY=.+|api_key: .+'
```

If a real credential was ever committed, deleting the current file is not
enough: revoke/rotate the credential first, then remove it from Git history.

Downloaded videos, subtitles, thumbnails, and generated translations may be
copyrighted or private. Confirm that you have the right to process and share
them; this repository intentionally ships without user media or model caches.

## Reporting a vulnerability

Please use GitHub's private security-advisory reporting for this repository.
Do not include API keys, private media, local paths, or unredacted logs in a
public issue.

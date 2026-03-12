# Deployment

The detailed deployment guide lives in
[docs/DEPLOY.md](./docs/DEPLOY.md).

Current production model, in short:

- deploy from `main`
- run as user `tg_bot`
- keep `BOT_MODE=semi_auto`
- keep live execution disabled
- use a project-local `.venv`
- keep the web UI bound to `127.0.0.1:8080`
- access the UI through an SSH tunnel unless and until HTTPS is configured

For the complete setup, update flow, and service examples, use:

- [docs/DEPLOY.md](./docs/DEPLOY.md)
- [docs/RUNBOOK.md](./docs/RUNBOOK.md)

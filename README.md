# Hermes Feishu Local Bridge

This worktree is a thin local wrapper around the existing Hermes checkout at:

`/Users/bytedance/Documents/hermes/hermes-agent`

Hermes already includes a Feishu / Lark gateway adapter. The files here make that setup repeatable without committing local secrets.

## Quick Start

1. Create a Feishu app at [open.feishu.cn](https://open.feishu.cn/).
2. Enable the app's Bot capability.
3. In the app's event subscription settings, choose WebSocket / long connection if available.
4. Copy `.env.example` to `.env` and fill `FEISHU_APP_ID` and `FEISHU_APP_SECRET`.
5. Start the local gateway:

```bash
./scripts/hermes-feishu-gateway run
```

For an interactive Hermes-guided setup, run:

```bash
./scripts/hermes-feishu-gateway setup
```

## Commands

```bash
./scripts/hermes-feishu-gateway check
./scripts/hermes-feishu-gateway status
./scripts/hermes-feishu-gateway run
./scripts/hermes-feishu-gateway setup
```

`run` starts Hermes in the foreground so you can watch logs while testing messages from Feishu.

## Feishu Notes

Use WebSocket mode first. It avoids ngrok, reverse proxies, and public callback URLs.

If you must use webhook mode, set:

```bash
FEISHU_CONNECTION_MODE=webhook
FEISHU_WEBHOOK_HOST=127.0.0.1
FEISHU_WEBHOOK_PORT=8765
FEISHU_WEBHOOK_PATH=/feishu/webhook
FEISHU_VERIFICATION_TOKEN=...
FEISHU_ENCRYPT_KEY=...
```

Then expose `http://127.0.0.1:8765/feishu/webhook` to Feishu with your preferred tunnel or reverse proxy.

## Access Control

The default template keeps direct messages restricted:

```bash
FEISHU_ALLOW_ALL_USERS=false
FEISHU_ALLOWED_USERS=
```

Unknown users can request pairing. Approve them from a local terminal with:

```bash
/Users/bytedance/Documents/hermes/hermes-agent/venv/bin/python \
  /Users/bytedance/Documents/hermes/hermes-agent/hermes \
  pairing approve feishu <code>
```

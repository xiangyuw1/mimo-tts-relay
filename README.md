# mimo-tts-relay

This project forwards MiMo TTS and exposes it as a TTS API that can be used directly by Legado (开源阅读).

Its main purpose is exactly this: convert MiMo TTS into a Legado-friendly TTS service interface.

## What it does

- Accepts text requests from clients such as Legado.
- Calls Xiaomi MiMo speech synthesis (defaults to `mimo-v2.5-tts`).
- Returns generated WAV audio.
- Supports language-based built-in voice selection via URL params (`en`, `zh`, or default).
- Supports overriding the voice via the `voice` URL param with any official preset Voice ID.
- Supports optional speed style control via request params.
- Supports session-based auth endpoints for clients that use a login flow.

## Run

Set required environment variables:

- MIMO_API_KEY

Optional auth variables (set all three to enable login/session auth):

- TTS_AUTH_USERNAME
- TTS_AUTH_PASSWORD
- TTS_SESSION_SECRET

Install dependencies and start service:

```bash
uv sync
uv run uvicorn main:app --host 0.0.0.0 --port 8080
```

Quick local test:

```bash
uv run python test-client.py
```

## Legado setup

Use the following values in Legado TTS server settings.

Protocol note:

- This app serves plain HTTP by default.
- If you need HTTPS, put it behind your own reverse proxy/TLS terminator (for example Nginx or Caddy).

- url:
	`http://your-domain/tts?text={{speakText}}&lang=zh`
- Content_Type:
	audio/wav
- concurrentRate:
	1

If auth is enabled in this relay, use login flow values below.

- loginUrl:
	http://your-domain/auth/login
- header:
	Leave empty when using login cookie session.

Language and speed notes:

- lang=zh uses Chinese voice 冰糖.
- lang=en uses English voice Mia.
- no lang uses mimo_default.
- `voice` URL param overrides the built-in voice with an official preset Voice ID, e.g. `&voice=Milo` or `&voice=茉莉` (English names are case-insensitive). Takes priority over the `lang` mapping.
- Preset voices (from MiMo v2.5 docs): Chinese 冰糖 / 茉莉 / 苏打 / 白桦, English Mia / Chloe / Milo / Dean, plus mimo_default.
- when speed is not provided: zh defaults to 变快, en defaults to Speed up.
- you can override speed by passing speed in request params.

## License

MIT

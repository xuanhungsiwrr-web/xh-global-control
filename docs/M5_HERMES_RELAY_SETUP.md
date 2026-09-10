# M5 Hermes relay boundary

Global Control owns Telegram command parsing and execution policy. Hermes owns
Telegram transport only; it must forward a normalized update to:

```text
POST http://127.0.0.1:8765/v1/telegram/update
Content-Type: application/json

{"update_id":"...","user_id":"6008639888","chat_id":"...","text":"/tasks"}
```

The repository helper `scripts/hermes_global_relay.py` performs this POST and
does not call an LLM or read Telegram credentials. It is intended to be invoked
by a Hermes connector/hook that can intercept an inbound message before the
agent loop. Hermes 0.21.1's ordinary Telegram gateway path does not provide
that interception as a declarative setting; do not enable OpenRouter or call
the Telegram Bot API from Global Control to work around it.

Start Global Control's loopback endpoint with the application wiring used by
the deployment, then run Hermes normally. Until a pre-agent Hermes connector
is installed, phone acceptance remains blocked and Hermes may still attempt its
own provider path for ordinary messages.

## Local startup (after the pre-agent relay is available)

Terminal 1, from the Global Control checkout:

```powershell
$env:XH_CONTROL_RUNTIME_ROOT = "C:\Users\xuanh\AppData\Local\xh-global-control\runtime"
.\.venv\Scripts\xhctl.exe telegram-serve `
  --user-id 6008639888 --chat-id 6008639888
```

Terminal 2, from the Hermes installation:

```powershell
& "C:\Users\xuanh\AppData\Local\hermes\bin\hermes.exe" gateway run
```

The relay can be tested locally without a phone using:

```powershell
$body = @{update_id="local-1";user_id="6008639888";chat_id="6008639888";text="/tasks"} | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:8765/v1/telegram/update -Method Post `
  -ContentType "application/json" -Body $body
```

This local test exercises Global parsing and authorization only; it is not
phone acceptance evidence.

## Temporary phone gateway (Windows)

For M5 acceptance without enabling any Hermes LLM provider, use the repository
gateway. It reads `TELEGRAM_BOT_TOKEN` from Hermes' local `.env`, polls Telegram,
POSTs each text message to Global, and sends Global's response back to the same
chat. It is test infrastructure, not Global Control core:

```powershell
cd "G:\My Drive\AI_Space\01_Development\incoming\global-control"
.\.venv\Scripts\python.exe scripts\mock_telegram_gateway.py
```

Run this alongside `telegram-serve`; for the same bot token, stop the ordinary
Hermes gateway first (otherwise both consumers race on Telegram `getUpdates`).
The mock gateway replaces Hermes only for this phone test. Stop it with Ctrl+C.
It must not be committed with a token or used as a production gateway.

For a private Telegram chat, `--user-id 6008639888` is sufficient because the
adapter authorizes the paired user. Add `--chat-id` only when you intentionally
want to restrict the endpoint to a specific chat.

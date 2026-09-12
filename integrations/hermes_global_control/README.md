# Hermes → XH Global Control adapter

This native Hermes plugin keeps Hermes as the Telegram transport and forwards
only `/run`, `/tasks`, `/pause`, and `/resume` to Global Control's loopback HTTP
boundary. It does not select models, route workers, inspect plugin handoffs, or
store Global task state.

The installed Hermes plugin should point to this directory so this repository
remains the only editable source. The optional `XH_GLOBAL_CONTROL_URL` override
must remain an HTTP loopback URL ending in `/v1/telegram/update`.


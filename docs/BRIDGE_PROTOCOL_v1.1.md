# Global Control bridge protocol 1.1

This is the narrow M6 extension to the existing process-plugin contract.

## Contract

```python
async def pause(task_id: str) -> str:
    ...

async def resume(task: TaskEnvelope, handoff_uri: str) -> PluginResult:
    ...
```

`pause()` requests a plugin-owned safe handoff. The process adapter writes a
task-scoped `pause.request.json` control message and accepts only a response
with this shape:

```json
{
  "protocol_version": "1.1",
  "task_id": "T-...",
  "handoff_uri": "opaque://..."
}
```

The plugin must finish its safe pause and exit its process after returning the
response. Global validates the response identity and non-empty URI, but never
opens, parses, copies, or hashes the handoff content.

On resume, Global validates the persisted checkpoint and calls
`resume(task, handoff_uri)`. The URI is passed as an opaque value in the
task-scoped process context. The plugin owns interpretation and loading of its
handoff state. Global keeps ownership of task identity, checkpoint revision,
attempt/generation fencing, permission, and audit state.

Protocol 1.0 plugins remain executable for ordinary `execute()` calls. They do
not support safe pause/resume and must be rejected for those operations rather
than treated as checkpoint-capable.

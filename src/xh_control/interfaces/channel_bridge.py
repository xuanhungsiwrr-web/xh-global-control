"""One-shot local file IPC client invoked by a trusted plugin process.

Files are transient message transport, never authoritative runtime state.
Only the controlling service can authorize/execute the request.
"""

import argparse
import json
from pathlib import Path
import sys
import time


MAX_MESSAGE = 2_000_000


def read_message(path: Path) -> dict:
    if path.stat().st_size > MAX_MESSAGE:
        raise ValueError("message too large")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("object required")
    return value


def publish(path: Path, value: dict) -> None:
    data = json.dumps(value, ensure_ascii=False, allow_nan=False)
    if len(data.encode("utf-8")) > MAX_MESSAGE:
        raise ValueError("message too large")
    temporary = path.with_suffix(".pending")
    with temporary.open("x", encoding="utf-8") as stream:
        stream.write(data)
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", type=Path, required=True)
    args = parser.parse_args()
    try:
        context = read_message(args.context)
        if context["protocol_version"] not in {"1.0", "1.1"}:
            raise ValueError("unsupported transport")
        root = args.context.resolve().parent
        request = json.loads(sys.stdin.buffer.read(MAX_MESSAGE + 1))
        if not isinstance(request, dict):
            raise ValueError("object required")
        # Exclusive claim prevents retries/duplicates from dispatching twice.
        with (root / "channel.claim").open("x"):
            pass
        publish(root / "request.json", request)
        deadline = time.monotonic() + context["timeout_seconds"]
        while time.monotonic() < deadline:
            if (root / "response.json").exists():
                response = read_message(root / "response.json")
                print(json.dumps(response, ensure_ascii=True, allow_nan=False))
                return 0
            time.sleep(0.05)
    except Exception:
        pass
    print("CHANNEL_BRIDGE_UNAVAILABLE", file=sys.stderr)
    return 3


if __name__ == "__main__":
    raise SystemExit(main())

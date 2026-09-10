"""Message-only Hermes -> Global Control relay.

The Hermes-side integration must invoke this script with one normalized JSON
update on stdin. It never calls a model and never handles Telegram credentials.
"""

from __future__ import annotations

import argparse
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def forward(payload: dict, endpoint: str, timeout: float = 10.0) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(endpoint, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read())
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        raise RuntimeError("Global Control relay unavailable") from exc
    if not isinstance(result, dict):
        raise RuntimeError("Global Control relay returned an invalid response")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", default="http://127.0.0.1:8765/v1/telegram/update")
    args = parser.parse_args()
    try:
        payload = json.load(__import__("sys").stdin)
        result = forward(payload, args.endpoint)
    except (ValueError, RuntimeError):
        print(json.dumps({"ok": False, "error": "Global Control relay failed"}))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Generic protocol fixture, deliberately contains no xh-tuvan workflow."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from urllib.parse import unquote, urlparse

parser = argparse.ArgumentParser()
parser.add_argument("--healthcheck", action="store_true")
parser.add_argument("--context", type=Path)
args = parser.parse_args()
if args.healthcheck:
    print(json.dumps({"protocol_version": "1.0", "healthy": True}))
    raise SystemExit(0)
task = json.load(sys.stdin)
context = json.loads(args.context.read_text())
request = {"task_id": task["task_id"], "capability": task["execution"]["master_capability"],
           "workspace": task["project"]["workspace_uri"], "prompt_or_instruction": task["user_request"],
           "artifact_refs": []}
if context.get("resume_handoff_uri"):
    # Test-only assertion surface: the bridge receives the URI as an opaque
    # prompt value; it never opens the referenced handoff.
    request["prompt_or_instruction"] = context["resume_handoff_uri"]
reply = subprocess.run([*context["channel_bridge"], "--context", str(args.context)],
                       input=json.dumps(request), capture_output=True, text=True, timeout=20)
if reply.returncode:
    raise SystemExit(3)
response = json.loads(reply.stdout)
outputs = []
status = "FAILED"
if response["output_ref"]:
    value = unquote(urlparse(response["output_ref"]).path)
    if len(value) > 2 and value[0] == "/" and value[2] == ":":
        value = value[1:]
    content = Path(value).read_bytes()
    payload = json.loads(content)
    if (response["success"] and payload.get("outcome") == "completed" and
        payload.get("deliverable") and payload.get("evidence") and not payload.get("blockers")):
        status = "COMPLETED"
    outputs = [{"artifact_type": "generic-result", "uri": response["output_ref"],
                "sha256": sha256(content).hexdigest()}]
result = {"task_id": task["task_id"], "status": status, "outputs": outputs,
                  "execution_summary": {"elapsed_seconds": 0.1, "subscription_calls": 1},
                  "global_learning": {}}
mutation = task["user_request"]
if mutation == "wrong-result-task":
    result["task_id"] = "OTHER"
elif mutation == "invented-usage":
    result["execution_summary"]["subscription_calls"] = 99
elif mutation == "invented-artifact":
    result["outputs"][0]["uri"] = "file:///unknown"
elif mutation == "domain-learning":
    result["global_learning"] = {"legal_rule": "SECRET-SENTINEL"}
print(json.dumps(result))

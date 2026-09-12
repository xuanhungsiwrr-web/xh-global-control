from xh_control.channels import ClaudeCodeAdapter, CodexAdapter
from xh_control.channels import ChannelRequest
from xh_control.channels._cli_health import CommandResult


def run_immediate(coroutine):
    try:
        coroutine.send(None)
    except StopIteration as exc:
        return exc.value
    raise AssertionError("healthcheck unexpectedly suspended")


def test_claude_healthcheck_uses_supported_auth_status_without_quota_claims():
    seen = []

    def runner(command, timeout):
        seen.append((command, timeout))
        return CommandResult(0, '{"loggedIn": true, "email": "not-returned"}')

    result = run_immediate(ClaudeCodeAdapter(command_runner=runner).healthcheck())

    assert seen == [(('claude', 'auth', 'status', '--json'), 5.0)]
    assert result == {
        "channel_id": "claude-code-subscription",
        "surface": "claude_code",
        "model": None,
        "health": "AVAILABLE",
        "reason": "CLI_AUTHENTICATED",
        "mechanism": "cli_auth_status",
        "quota_checked": False,
    }


def test_codex_healthcheck_is_per_channel_and_nonzero_is_unavailable():
    result = run_immediate(
        CodexAdapter(
            channel_id="codex-model-a",
            model="model-a",
            command_runner=lambda command, timeout: 1,
        ).healthcheck()
    )

    assert result["channel_id"] == "codex-model-a"
    assert result["model"] == "model-a"
    assert result["health"] == "UNAVAILABLE"
    assert result["quota_checked"] is False


def test_claude_exit_zero_without_logged_in_true_is_not_available():
    result = run_immediate(
        ClaudeCodeAdapter(
            command_runner=lambda command, timeout: CommandResult(
                0, '{"loggedIn": false, "email": "not-returned"}'
            )
        ).healthcheck()
    )

    assert result["health"] == "UNAVAILABLE"
    assert "email" not in result


def test_missing_cli_is_unavailable_without_exposing_process_output():
    def missing(command, timeout):
        raise FileNotFoundError

    result = run_immediate(ClaudeCodeAdapter(command_runner=missing).healthcheck())

    assert result["health"] == "UNAVAILABLE"
    assert result["reason"] == "CLI_NOT_FOUND"
    assert set(result) == {
        "channel_id", "surface", "model", "health", "reason", "mechanism",
        "quota_checked",
    }


def test_codex_execute_uses_stdin_ephemeral_sandbox_and_returns_artifact(tmp_path):
    seen = []

    async def runner(command, instruction, workspace, timeout):
        seen.append((command, instruction, workspace, timeout))
        output_path = command[command.index("--output-last-message") + 1]
        from pathlib import Path
        Path(output_path).write_text("channel output", encoding="utf-8")
        return CommandResult(
            0,
            '{"type":"turn.completed","usage":{"input_tokens":11,"output_tokens":3}}',
        )

    adapter = CodexAdapter(
        sandbox="workspace-write",
        output_root=tmp_path / "results",
        execution_runner=runner,
        output_id_factory=lambda: "one",
    )
    request = ChannelRequest(
        task_id="T-CHANNEL-1",
        capability="MASTER",
        prompt_or_instruction="Do the opaque task",
        workspace=str(tmp_path),
        artifact_refs=["artifact://input-one"],
    )

    response = run_immediate(adapter.execute(request))

    command, instruction, workspace, timeout = seen[0]
    assert command[:2] == ("codex", "exec")
    assert "--ephemeral" in command
    assert command[command.index("--sandbox") + 1] == "workspace-write"
    assert command[-1] == "-"
    assert "artifact://input-one" in instruction
    assert workspace == tmp_path.resolve()
    assert timeout == 900.0
    assert response.success is True
    assert response.output_ref is not None
    assert response.usage == {"input_tokens": 11, "output_tokens": 3}


def test_claude_execute_extracts_result_and_only_reported_token_usage(tmp_path):
    seen = []

    async def runner(command, instruction, workspace, timeout):
        seen.append(command)
        return CommandResult(
            0,
            '{"result":"claude output","usage":{"input_tokens":5,"output_tokens":2},'
            '"total_cost_usd":99.0}',
        )

    adapter = ClaudeCodeAdapter(
        output_root=tmp_path / "results",
        execution_runner=runner,
        output_id_factory=lambda: "one",
    )
    response = run_immediate(
        adapter.execute(
            ChannelRequest(
                task_id="T-CHANNEL-2",
                capability="MASTER",
                prompt_or_instruction="Read only",
                workspace=str(tmp_path),
            )
        )
    )

    assert response.success is True
    assert "--restricted" in seen[0]
    assert seen[0][seen[0].index("--permission-mode") + 1] == "dontAsk"
    assert seen[0][seen[0].index("--permission-prompts") + 1] == "none"
    assert response.usage == {"input_tokens": 5, "output_tokens": 2}
    assert "cost" not in response.usage


def test_execute_rejects_missing_workspace_without_invoking_runner(tmp_path):
    async def runner(*args):
        raise AssertionError("runner should not be invoked")

    response = run_immediate(
        CodexAdapter(execution_runner=runner).execute(
            ChannelRequest(
                task_id="T-MISSING",
                capability="MASTER",
                prompt_or_instruction="noop",
                workspace=str(tmp_path / "missing"),
            )
        )
    )

    assert response.success is False
    assert response.error_type == "WORKSPACE_NOT_FOUND"
    assert response.output_ref is None


def test_task_id_cannot_escape_channel_output_root(tmp_path):
    seen = []

    async def runner(command, instruction, workspace, timeout):
        output_path = command[command.index("--output-last-message") + 1]
        seen.append(output_path)
        from pathlib import Path
        Path(output_path).write_text("safe", encoding="utf-8")
        return CommandResult(0)

    adapter = CodexAdapter(
        output_root=tmp_path / "results",
        execution_runner=runner,
        output_id_factory=lambda: "one",
    )
    response = run_immediate(
        adapter.execute(
            ChannelRequest(
                task_id="../../escape",
                capability="MASTER",
                prompt_or_instruction="noop",
                workspace=str(tmp_path),
            )
        )
    )

    assert response.success is True
    assert str((tmp_path / "results").resolve()) in seen[0]
    assert ".." not in str(seen[0]).replace(str((tmp_path / "results").resolve()), "")

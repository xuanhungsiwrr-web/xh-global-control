from pathlib import Path

import pytest
import yaml

from xh_control.config import load_config
from xh_control.constants import EXPECTED_CONFIG_ROOTS
from xh_control.exceptions import ConfigurationError


def test_configuration_loads(config_root, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    config = load_config(config_root)
    assert config.system.default_cost_mode == "BALANCED"
    assert config.database_path == tmp_path / "runtime/control.db"
    assert load_config().channels["codex-subscription"].provider == "openai"
    assert not config.database_path.exists()


@pytest.mark.parametrize("filename", EXPECTED_CONFIG_ROOTS)
def test_missing_file(config_root, filename):
    (config_root / filename).unlink()
    with pytest.raises(ConfigurationError, match=filename):
        load_config(config_root)


@pytest.mark.parametrize("text", ["system: [", "- system", "null", "system: []", "wrong: {}", "system: {}\nsystem: {}", "system: {}\nextra: {}"])
def test_invalid_yaml_or_structure(config_root, text):
    (config_root / "system.yaml").write_text(text)
    with pytest.raises(ConfigurationError):
        load_config(config_root)


@pytest.mark.parametrize("filename,path,value", [
    ("system.yaml", ["system", "state_backend"], "redis"),
    ("system.yaml", ["system", "default_cost_mode"], "unknown"),
    ("system.yaml", ["system", "subscription_first"], "yes"),
    ("routing.yaml", ["routing", "modes"], {}),
    ("routing.yaml", ["routing", "weights", "latency"], float("nan")),
    ("subscriptions.yaml", ["subscriptions", "claude", "preferred_channel"], "absent"),
    ("budgets.yaml", ["budgets", "defaults", "task_api_soft_usd"], 100),
    ("plugins.yaml", ["plugins", "xh-tuvan", "plugin_id"], "mismatch"),
    ("workers.yaml", ["workers", "pc-main", "paths"], {}),
    ("permissions.yaml", ["permissions", "levels", "SYSTEM_WRITE", "approval_required"], False),
    ("channels.yaml", ["channels", "codex-subscription", "capabilities"], []),
])
def test_invalid_config_values(config_root, filename, path, value):
    file = config_root / filename
    document = yaml.safe_load(file.read_text())
    target = document
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    file.write_text(yaml.safe_dump(document))
    with pytest.raises(ConfigurationError):
        load_config(config_root)


def test_diagnostics_do_not_echo_values(config_root):
    secret = "private-test-value-do-not-print"
    (config_root / "system.yaml").write_text(f"system:\n  api_key: {secret}\n")
    with pytest.raises(ConfigurationError) as error:
        load_config(config_root)
    assert secret not in str(error.value)


@pytest.mark.parametrize("filename,key", EXPECTED_CONFIG_ROOTS.items())
def test_required_nested_configuration(config_root, filename, key):
    (config_root / filename).write_text(f"{key}: {{}}")
    if key == "subscriptions":
        assert load_config(config_root).subscriptions == {}
    else:
        with pytest.raises(ConfigurationError):
            load_config(config_root)

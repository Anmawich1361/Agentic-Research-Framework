from agentic_research.settings import load_yaml_config


def test_load_yaml_config_from_configs_directory() -> None:
    config = load_yaml_config("workflow.yaml")

    assert config["workflow"]["artifact_dir"] == "runs"
    assert "checkpoint" in config["workflow"]["default_sequence"]

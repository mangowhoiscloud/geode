from core.scheduler.predefined import (
    PipelineConfig,
)


def test_pipeline_config_defaults_are_generic() -> None:
    config = PipelineConfig()

    assert config.mode == "pipeline"
    assert config.batch_size == 1
    assert config.extra == {}

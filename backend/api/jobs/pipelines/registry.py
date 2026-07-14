from __future__ import annotations

from .base import PipelineDefinition


class PipelineRegistry:
    """Validated mapping from stable pipeline keys to implementations."""

    def __init__(self) -> None:
        self._pipelines: dict[str, PipelineDefinition] = {}

    def register(self, pipeline: PipelineDefinition) -> None:
        key = str(pipeline.pipeline_key).strip().lower()
        if not key:
            raise ValueError('Pipeline key cannot be empty')
        if key in self._pipelines:
            raise ValueError(f"Pipeline already registered: '{key}'")
        self._pipelines[key] = pipeline

    def get(self, pipeline_key: str) -> PipelineDefinition:
        key = str(pipeline_key).strip().lower()
        try:
            return self._pipelines[key]
        except KeyError as exc:
            raise KeyError(f"Unsupported pipeline_key: '{key}'") from exc

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(self._pipelines)
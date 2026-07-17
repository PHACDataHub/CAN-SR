"""Public request/response models for selective citation exports."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ExportDimension(BaseModel):
    id: str
    label: str
    default_selected: bool = False


class ExportItem(BaseModel):
    id: str
    label: str
    default_selected: bool = False
    category: str | None = None
    available_dimensions: list[str] | None = None


class ExportGroup(BaseModel):
    id: Literal['citation', 'l1', 'l2', 'parameters']
    label: str
    items: list[ExportItem]
    dimensions: list[ExportDimension] = Field(default_factory=list)


class CitationExportSchema(BaseModel):
    schema_version: Literal[1] = 1
    format: Literal['csv'] = 'csv'
    row_scopes: list[str] = Field(
        default_factory=lambda: ['all', 'l1_included', 'l2_included', 'citation_ids'],
    )
    groups: list[ExportGroup]


class ExportRowScope(BaseModel):
    kind: Literal['all', 'l1_included', 'l2_included', 'citation_ids'] = 'all'
    citation_ids: list[int] | None = None

    @model_validator(mode='after')
    def validate_ids(self):
        if self.kind == 'citation_ids' and not self.citation_ids:
            raise ValueError('citation_ids is required for citation_ids scope')
        if self.kind != 'citation_ids' and self.citation_ids is not None:
            raise ValueError('citation_ids is only valid for citation_ids scope')
        if self.citation_ids and len(self.citation_ids) > 500:
            raise ValueError('citation_ids cannot contain more than 500 entries')
        return self


class ExportSelection(BaseModel):
    group: Literal['citation', 'l1', 'l2', 'parameters']
    items: list[str] = Field(default_factory=list, max_length=500)
    dimensions: list[str] = Field(default_factory=list, max_length=10)


class CitationExportRequest(BaseModel):
    schema_version: Literal[1] = 1
    format: Literal['csv'] = 'csv'
    row_scope: ExportRowScope = Field(default_factory=ExportRowScope)
    selections: list[ExportSelection] = Field(min_length=1, max_length=4)

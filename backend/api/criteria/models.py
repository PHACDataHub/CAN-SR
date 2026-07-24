"""Strict version 2 criteria configuration models and domain validation."""
from __future__ import annotations

from enum import Enum
from typing import Annotated
from typing import Literal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import model_validator
from pydantic import StringConstraints

CriteriaId = Annotated[
    str, StringConstraints(
        pattern=r'^[a-z][a-z0-9_-]{2,63}$',
    ),
]
NonEmptyText = Annotated[
    str, StringConstraints(
        strip_whitespace=True, min_length=1, max_length=10000,
    ),
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Decision(str, Enum):
    INCLUDE = 'include'
    EXCLUDE = 'exclude'


class TriggerCondition(StrictModel):
    source_item_id: CriteriaId
    option_id: CriteriaId


class Trigger(StrictModel):
    all: list[TriggerCondition] = Field(default_factory=list, max_length=20)

    @model_validator(mode='after')
    def conditions_are_unique(self) -> Trigger:
        pairs = [
            (condition.source_item_id, condition.option_id)
            for condition in self.all
        ]
        if len(pairs) != len(set(pairs)):
            raise ValueError('duplicate trigger conditions are not allowed')
        return self


class CitationFields(StrictModel):
    l1_include: list[NonEmptyText] = Field(
        default_factory=list, max_length=100,
    )
    doi: NonEmptyText | None = None

    @model_validator(mode='after')
    def include_fields_are_unique(self) -> CitationFields:
        if len(self.l1_include) != len(set(self.l1_include)):
            raise ValueError(
                'citation_fields.l1_include must not contain duplicates',
            )
        return self


class ScreeningAnswer(StrictModel):
    id: CriteriaId
    label: NonEmptyText
    context: str | None = Field(default=None, max_length=10000)
    decision: Decision


class ScreeningQuestion(StrictModel):
    id: CriteriaId
    question: NonEmptyText
    context: str | None = Field(default=None, max_length=10000)
    answers: list[ScreeningAnswer] = Field(min_length=2, max_length=50)
    trigger: Trigger = Field(default_factory=Trigger)

    @model_validator(mode='after')
    def answer_ids_are_unique(self) -> ScreeningQuestion:
        ids = [answer.id for answer in self.answers]
        if len(ids) != len(set(ids)):
            raise ValueError('answer IDs must be unique within a question')
        return self


class ParameterOption(StrictModel):
    id: CriteriaId
    label: NonEmptyText
    context: str | None = Field(default=None, max_length=10000)


class TextParameter(StrictModel):
    id: CriteriaId
    name: NonEmptyText
    description: NonEmptyText
    type: Literal['text']
    unit_instructions: str | None = Field(default=None, max_length=10000)
    calculation: str | None = Field(default=None, max_length=10000)
    trigger: Trigger = Field(default_factory=Trigger)
    legacy_category: str | None = Field(default=None, max_length=1000)


class SelectionParameter(StrictModel):
    id: CriteriaId
    name: NonEmptyText
    description: NonEmptyText
    type: Literal['selection']
    selection_mode: Literal['single', 'multiple']
    options: list[ParameterOption] = Field(min_length=1, max_length=100)
    unit_instructions: str | None = Field(default=None, max_length=10000)
    calculation: str | None = Field(default=None, max_length=10000)
    trigger: Trigger = Field(default_factory=Trigger)
    legacy_category: str | None = Field(default=None, max_length=1000)

    @model_validator(mode='after')
    def option_ids_are_unique(self) -> SelectionParameter:
        ids = [option.id for option in self.options]
        if len(ids) != len(set(ids)):
            raise ValueError('option IDs must be unique within a parameter')
        return self


Parameter = Annotated[
    TextParameter |
    SelectionParameter, Field(discriminator='type'),
]


class CriteriaConfigV2(StrictModel):
    schema_version: Literal[2] = 2
    citation_fields: CitationFields = Field(default_factory=CitationFields)
    l1: list[ScreeningQuestion] = Field(default_factory=list, max_length=100)
    l2: list[ScreeningQuestion] = Field(default_factory=list, max_length=100)
    parameters: list[Parameter] = Field(default_factory=list, max_length=200)

    @model_validator(mode='after')
    def validate_global_identity_and_triggers(self) -> CriteriaConfigV2:
        items = [*self.l1, *self.l2, *self.parameters]
        ids = [item.id for item in items]
        if len(ids) != len(set(ids)):
            raise ValueError('item IDs must be unique across the review')

        seen: dict[str, set[str] | None] = {}
        for item in items:
            for condition in item.trigger.all:
                if condition.source_item_id not in seen:
                    raise ValueError(
                        f'trigger source {condition.source_item_id!r} must reference an earlier item',
                    )
                options = seen[condition.source_item_id]
                if options is None:
                    raise ValueError(
                        'text parameters cannot be trigger sources',
                    )
                if condition.option_id not in options:
                    raise ValueError(
                        f'option {condition.option_id!r} does not belong to trigger source '
                        f'{condition.source_item_id!r}',
                    )

            if isinstance(item, ScreeningQuestion):
                seen[item.id] = {answer.id for answer in item.answers}
            elif isinstance(item, SelectionParameter):
                seen[item.id] = {option.id for option in item.options}
            else:
                seen[item.id] = None
        return self

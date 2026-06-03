"""
输出模板 API Schema
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, ConfigDict, model_validator


class TemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    schema_def: dict = Field(default_factory=dict, alias="schema_json")
    rules_md: str | None = None
    generator_code: str | None = None
    sample_output: str | None = None

    model_config = ConfigDict(populate_by_name=True)


class TemplateUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    schema_def: dict | None = Field(default=None, alias="schema_json")
    rules_md: str | None = None
    generator_code: str | None = None
    sample_output: str | None = None

    model_config = ConfigDict(populate_by_name=True)


class TemplateResponse(BaseModel):
    id: UUID
    name: str
    description: str | None
    schema_def: dict = Field(alias="schema_json")
    rules_md: str | None
    generator_code: str | None
    sample_output: str | None
    has_reference_doc: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    @model_validator(mode="before")
    @classmethod
    def _compute_has_reference_doc(cls, values):
        if isinstance(values, dict):
            if values.get("reference_doc") is not None:
                values["has_reference_doc"] = True
            return values
        if hasattr(values, "reference_doc") and values.reference_doc is not None:
            data = {c.name: getattr(values, c.name) for c in values.__table__.columns}
            data["has_reference_doc"] = True
            return data
        return values


class TemplateListItem(BaseModel):
    id: UUID
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TemplateExportRequest(BaseModel):
    template_id: UUID

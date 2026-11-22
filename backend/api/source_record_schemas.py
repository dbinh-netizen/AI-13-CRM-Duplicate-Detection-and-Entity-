
from typing import Any
from pydantic import BaseModel, Field


class SourceRecordResponse(BaseModel):
    id: str
    source_system_id: str
    entity_type: str
    source_key: str
    import_batch_id: str
    entity_subtype: str | None = None
    status: str
    record_payload: dict[str, Any]
    created_at: str | None = None
    updated_at: str | None = None


class SourceRecordListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    records: list[SourceRecordResponse]


class SourceSystemResponse(BaseModel):
    source_code: str
    source_name: str | None = None


class ImportBatchResponse(BaseModel):
    id: str
    batch_code: str
    file_name: str | None = None
    status: str


class SourceRecordVersionResponse(BaseModel):
    id: str
    version_number: int
    is_current: bool
    raw_payload: dict[str, Any]


class NormalizedFieldResponse(BaseModel):
    feature_name: str
    raw_value: Any = None
    normalized_value: Any = None
    policy_id: str


class SourceRecordDetailResponse(BaseModel):
    record: SourceRecordResponse
    source_system: SourceSystemResponse | None = None
    import_batch: ImportBatchResponse | None = None
    version: SourceRecordVersionResponse | None = None
    normalized_fields: list[NormalizedFieldResponse] = Field(
        default_factory=list
    )

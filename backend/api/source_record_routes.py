from backend.api.source_record_schemas import (
    SourceRecordListResponse,
    SourceRecordDetailResponse,
)
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from backend.database import get_db
from backend.models.intake import (
    SourceRecord,
    SourceRecordVersion,
    SourceSystem,
    ImportBatch,
)
from backend.models.matching import NormalizedFeature


router = APIRouter(
    prefix="/api/v1/source-records",
    tags=["Source Records API"],
)


def serialize_record(record):
    return {
        "id": str(record.id),
        "source_system_id": str(record.source_system_id),
        "entity_type": record.entity_type,
        "source_key": record.source_key,
        "import_batch_id": str(record.import_batch_id),
        "entity_subtype": record.entity_subtype,
        "status": record.status,
        "record_payload": record.record_payload,
        "created_at": (
            record.created_at.isoformat()
            if record.created_at else None
        ),
        "updated_at": (
            record.updated_at.isoformat()
            if record.updated_at else None
        ),
    }


@router.get(
    "",
    response_model=SourceRecordListResponse,
    summary="List source records",
    description="Query imported source records from the database with pagination and optional entity type filtering.",
)
def list_source_records(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    entity_type: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    query = db.query(SourceRecord)

    if entity_type:
        entity_type = entity_type.upper()

        if entity_type not in ("ACCOUNT", "CONTACT"):
            raise HTTPException(
                status_code=400,
                detail="entity_type must be ACCOUNT or CONTACT",
            )

        query = query.filter(
            SourceRecord.entity_type == entity_type
        )

    total = query.count()

    records = (
        query.order_by(SourceRecord.created_at, SourceRecord.id)
        .offset(offset)
        .limit(limit)
        .all()
    )

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "records": [
            serialize_record(record)
            for record in records
        ],
    }


@router.get(
    "/{record_id}",
    response_model=SourceRecordDetailResponse,
    summary="Get source record details",
    description="Retrieve source record metadata, raw payload, latest version and available normalized fields from the database.",
    responses={
        404: {
            "description": "Source record not found",
            "content": {
                "application/json": {
                    "example": {
                        "detail": {
                            "code": "SOURCE_RECORD_NOT_FOUND",
                            "message": "Source record not found",
                        }
                    }
                }
            },
        }
    },
)
def get_source_record(
    record_id: UUID,
    db: Session = Depends(get_db),
):
    record = (
        db.query(SourceRecord)
        .filter(SourceRecord.id == record_id)
        .first()
    )

    if record is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "SOURCE_RECORD_NOT_FOUND",
                "message": "Source record not found",
            },
        )

    version = (
        db.query(SourceRecordVersion)
        .filter(
            SourceRecordVersion.source_record_id == record.id
        )
        .order_by(
            SourceRecordVersion.version_number.desc()
        )
        .first()
    )

    normalized_fields = []

    if version is not None:
        features = (
            db.query(NormalizedFeature)
            .filter(
                NormalizedFeature.source_record_version_id
                == version.id
            )
            .order_by(NormalizedFeature.feature_name)
            .all()
        )

        normalized_fields = [
            {
                "feature_name": feature.feature_name,
                "raw_value": feature.raw_value,
                "normalized_value": feature.normalized_value,
                "policy_id": str(feature.policy_id),
            }
            for feature in features
        ]

    source_system = (
        db.query(SourceSystem)
        .filter(SourceSystem.id == record.source_system_id)
        .first()
    )

    import_batch = (
        db.query(ImportBatch)
        .filter(ImportBatch.id == record.import_batch_id)
        .first()
    )

    return {
        "record": serialize_record(record),
        "source_system": {
            "source_code": source_system.source_code,
            "source_name": source_system.source_name,
        } if source_system else None,
        "import_batch": {
            "id": str(import_batch.id),
            "batch_code": import_batch.batch_code,
            "file_name": import_batch.file_name,
            "status": import_batch.status,
        } if import_batch else None,
        "version": {
            "id": str(version.id),
            "version_number": version.version_number,
            "is_current": version.is_current,
            "raw_payload": version.raw_payload,
        } if version else None,
        "normalized_fields": normalized_fields,
    }

import uuid
from datetime import datetime, timezone
import sqlalchemy as sa
from sqlalchemy.orm import declarative_base
from sqlalchemy.types import TypeDecorator, CHAR, String, DateTime
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB

Base = declarative_base()

class GUIDType(TypeDecorator):
    """Platform-independent GUID/UUID type.
    Uses PostgreSQL's native UUID type, otherwise uses CHAR(36) storing as string.
    """
    impl = CHAR(36)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        else:
            return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if dialect.name == "postgresql":
            if isinstance(value, uuid.UUID):
                return value
            return uuid.UUID(str(value))
        else:
            if isinstance(value, uuid.UUID):
                return str(value)
            return str(uuid.UUID(str(value)))

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(str(value))


class ISOUtcDateTime(TypeDecorator):
    """Timezone-aware DateTime stored as UTC timestamp or ISO-8601 string."""
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc)
        return value

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        if isinstance(value, datetime) and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

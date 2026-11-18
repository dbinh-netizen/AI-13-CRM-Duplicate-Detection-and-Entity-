import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# Đưa root repository vào sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from backend.config import DATABASE_URL
from backend.models import Base

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

def get_effective_url() -> str:
    """Xác định URL kết nối tối ưu:
    1. Nếu DATABASE_URL là PostgreSQL, ưu tiên dùng PostgreSQL (hỗ trợ docker-compose up -d).
    2. Nếu config có sqlalchemy.url do test fixture gán, sử dụng config.
    3. Mặc định fallback về SQLite (code hàng ngày không cần cài thêm DB).
    """
    env_url = os.getenv("DATABASE_URL")
    cfg_url = config.get_main_option("sqlalchemy.url")

    if env_url and ("postgres" in env_url):
        url = env_url
    elif cfg_url:
        url = cfg_url
    else:
        url = DATABASE_URL or "sqlite:///./data/songnhat_crm.db"

    # Tự động chuẩn hóa driver psycopg2 cho PostgreSQL nếu cần
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = get_effective_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=url.startswith("sqlite"),
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    url = get_effective_url()
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = url

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        is_sqlite = connection.dialect.name == "sqlite"
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=is_sqlite,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

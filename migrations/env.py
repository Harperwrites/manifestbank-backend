import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context
from dotenv import load_dotenv

# ----------------------------------------
# Add backend folder to sys.path so Alembic can import app modules
# ----------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(__file__))  # backend folder
sys.path.append(BASE_DIR)

# ----------------------------------------
# Load environment variables
# ----------------------------------------
load_dotenv(os.path.join(BASE_DIR, ".env"))
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL is not set in the .env file")

# ----------------------------------------
# Alembic Config
# ----------------------------------------
config = context.config
fileConfig(config.config_file_name)  # read logging config from alembic.ini

# Override the sqlalchemy.url from .env
config.set_main_option("sqlalchemy.url", DATABASE_URL)

# ----------------------------------------
# Import your models for 'autogenerate' support
# ----------------------------------------
from app.db.session import Base  # now this works
# Import models so Alembic can detect them
import app.models.user  # or from app.models.user import User
target_metadata = Base.metadata



# ----------------------------------------
# Run migrations
# ----------------------------------------
def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

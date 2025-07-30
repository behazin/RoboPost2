import sys
import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# جدید: افزودن مسیر روت پروژه به Python Path
# این کار برای این است که alembic بتواند ماژول‌های پروژه ما (مانند core) را پیدا کند.
sys.path.insert(0, os.path.realpath(os.path.join(os.path.dirname(__file__), '..')))

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# --- بخش اصلی تغییرات ما ---

# جدید: وارد کردن Base از مدل‌های دیتابیس و تنظیمات پروژه
from core.database import Base
from core.db_models import * # وارد کردن تمام مدل‌ها برای شناسایی خودکار
from core.config import settings

# تغییر: به جای target_metadata = None، آن را به Base.metadata مدل‌های خودمان متصل می‌کنیم.
# این خط به Alembic می‌گوید که برای مقایسه و ساخت خودکار، به کدام جداول نگاه کند.
target_metadata = Base.metadata

# جدید: به صورت برنامه‌نویسی، آدرس دیتابیس را از تنظیمات پروژه خودمان می‌خوانیم.
# این کار تضمین می‌کند که Alembic همیشه از همان دیتابیس اصلی برنامه استفاده کند.
config.set_main_option('sqlalchemy.url', settings.DATABASE_URL)

# --- پایان بخش تغییرات ---


# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
    
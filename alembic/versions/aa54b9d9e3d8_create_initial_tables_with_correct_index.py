"""Create initial project tables

Revision ID: aa54b9d9e3d8
Revises: 
Create Date: 2025-07-06 22:18:18.232184

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'aa54b9d9e3d8' # این شناسه را با شناسه فایل خودتان یکی کنید
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### کد اصلاح شده و کامل برای ساخت تمام جداول و ایندکس‌ها ###

    # --- مرحله ۱: ساخت تمام جداول ---
    op.create_table('channels',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('telegram_channel_id', sa.String(length=255), nullable=False),
        sa.Column('target_language_code', sa.String(length=10), nullable=True),
        sa.Column('admin_group_id', sa.BigInteger(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
        sa.UniqueConstraint('telegram_channel_id')
    )
    op.create_table('sources',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('rss_url', sa.String(length=2048), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )
    op.create_table('articles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('source_name', sa.String(length=255), nullable=False),
        sa.Column('original_url', sa.String(length=2048), nullable=False),
        sa.Column('original_title', sa.Text(), nullable=False),
        sa.Column('original_content', sa.Text(), nullable=True),
        sa.Column('image_url', sa.String(length=2048), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=True),
        sa.Column('translated_title', sa.Text(), nullable=True),
        sa.Column('translated_content', sa.Text(), nullable=True),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table('source_channel_map',
        sa.Column('source_id', sa.Integer(), nullable=False),
        sa.Column('channel_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['channel_id'], ['channels.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['source_id'], ['sources.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('source_id', 'channel_id')
    )

    # --- مرحله ۲: ساخت تمام ایندکس‌ها پس از ایجاد جداول ---
    op.create_index(op.f('ix_channels_id'), 'channels', ['id'], unique=False)
    op.create_index(op.f('ix_sources_id'), 'sources', ['id'], unique=False)
    op.create_index(op.f('ix_articles_id'), 'articles', ['id'], unique=False)
    op.create_index('ix_articles_original_url', 'articles', ['original_url'], unique=True, mysql_length=255)
    op.create_index(op.f('ix_articles_status'), 'articles', ['status'], unique=False)
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### کد اصلاح شده برای حذف تمام جداول و ایندکس‌ها ###
    op.drop_index(op.f('ix_articles_status'), table_name='articles')
    op.drop_index('ix_articles_original_url', table_name='articles')
    op.drop_index(op.f('ix_articles_id'), table_name='articles')
    op.drop_index(op.f('ix_sources_id'), table_name='sources')
    op.drop_index(op.f('ix_channels_id'), table_name='channels')
    op.drop_table('source_channel_map')
    op.drop_table('sources')
    op.drop_table('channels')
    op.drop_table('articles')
    # ### end Alembic commands ###
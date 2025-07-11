"""Add news_value_score to articles table

Revision ID: 5fe88c006a51
Revises: c517e9f6d003
Create Date: 2025-07-11 13:30:20.897721

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5fe88c006a51'
down_revision: Union[str, Sequence[str], None] = 'c517e9f6d003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('articles', sa.Column('news_value_score', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_articles_news_value_score'), 'articles', ['news_value_score'], unique=False)
    # ### end Alembic commands ###


def downgrade() -> None:
    """Downgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f('ix_articles_news_value_score'), table_name='articles')
    op.drop_column('articles', 'news_value_score')
    # ### end Alembic commands ###

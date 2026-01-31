"""Add pricing and channel integration tables

Revision ID: 534290364619
Revises: e08b884d0015
Create Date: 2026-01-16 03:16:14.654613

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '534290364619'
down_revision: Union[str, None] = 'e08b884d0015'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Upgrade database schema.
    
    Safety Guidelines:
    - New columns should be nullable or have server_default
    - Avoid dropping columns with existing data
    - For column type changes, use gradual migration (new column -> copy data -> drop old)
    """
    pass


def downgrade() -> None:
    """
    Downgrade database schema.
    
    Note: Downgrades may not always be possible or safe.
    Test thoroughly before using in production.
    """
    pass

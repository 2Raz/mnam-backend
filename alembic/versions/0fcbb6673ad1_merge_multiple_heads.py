"""merge_multiple_heads

Revision ID: 0fcbb6673ad1
Revises: 002_soft_delete_notifications, 004_add_employee_sessions, 6dd3c0ebcacc
Create Date: 2026-01-23 02:59:49.803406

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0fcbb6673ad1'
down_revision: Union[str, None] = ('002_soft_delete_notifications', '004_add_employee_sessions', '6dd3c0ebcacc')
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

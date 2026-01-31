"""merge_heads

Revision ID: c32fcf42fb3b
Revises: 009_webhook_idempotency, ed606cebb0b3
Create Date: 2026-01-20 16:18:23.293253

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c32fcf42fb3b'
down_revision: Union[str, None] = ('009_webhook_idempotency', 'ed606cebb0b3')
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

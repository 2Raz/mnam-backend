"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

# revision identifiers, used by Alembic.
revision: str = ${repr(up_revision)}
down_revision: Union[str, None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    """
    Upgrade database schema.
    
    Safety Guidelines:
    - New columns should be nullable or have server_default
    - Avoid dropping columns with existing data
    - For column type changes, use gradual migration (new column -> copy data -> drop old)
    """
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    """
    Downgrade database schema.
    
    Note: Downgrades may not always be possible or safe.
    Test thoroughly before using in production.
    """
    ${downgrades if downgrades else "pass"}

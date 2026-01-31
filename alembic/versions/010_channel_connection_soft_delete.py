"""010 Add deleted_at to channel_connections for soft delete

Revision ID: 010_channel_connection_soft_delete
Revises: 009_webhook_idempotency
Create Date: 2026-01-29

Adds soft delete support for channel connections.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '010_channel_connection_soft_delete'
down_revision = ('009_webhook_idempotency', '0fcbb6673ad1')
branch_labels = None
depends_on = None


def upgrade():
    # Add deleted_at column to channel_connections for soft delete
    op.add_column(
        'channel_connections',
        sa.Column('deleted_at', sa.DateTime(), nullable=True)
    )
    
    # Create index for faster queries on non-deleted connections
    op.create_index(
        'ix_channel_connections_deleted_at',
        'channel_connections',
        ['deleted_at']
    )


def downgrade():
    # Drop the index first
    op.drop_index('ix_channel_connections_deleted_at', 'channel_connections')
    
    # Drop the column
    op.drop_column('channel_connections', 'deleted_at')

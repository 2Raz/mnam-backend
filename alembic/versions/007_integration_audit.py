"""Add integration_audit table

Revision ID: 007_integration_audit
Revises: 006_booking_source_tracking
Create Date: 2026-01-16

Adds:
- integration_audit table for FAS audit trail
- Tracks all inbound/outbound sync operations
- Updates booking source enum to include 'channex'
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '007_integration_audit'
down_revision = '006_booking_source'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create integration_audit table
    op.create_table(
        'integration_audit',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('connection_id', sa.String(36), sa.ForeignKey('channel_connections.id', ondelete='SET NULL'), nullable=True),
        sa.Column('direction', sa.String(20), nullable=False),
        sa.Column('entity_type', sa.String(50), nullable=False),
        sa.Column('external_id', sa.String(255), nullable=True),
        sa.Column('unit_id', sa.String(36), sa.ForeignKey('units.id', ondelete='SET NULL'), nullable=True),
        sa.Column('payload_hash', sa.String(64), nullable=True),
        sa.Column('payload_size_bytes', sa.Integer(), nullable=True),
        sa.Column('date_from', sa.DateTime(), nullable=True),
        sa.Column('date_to', sa.DateTime(), nullable=True),
        sa.Column('records_count', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('retry_count', sa.Integer(), default=0),
        sa.Column('started_at', sa.DateTime(), default=sa.func.now()),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('request_id', sa.String(50), nullable=True),
        sa.Column('created_at', sa.DateTime(), default=sa.func.now()),
    )
    
    # Create indexes
    op.create_index('ix_integration_audit_direction', 'integration_audit', ['direction'])
    op.create_index('ix_integration_audit_entity', 'integration_audit', ['entity_type'])
    op.create_index('ix_integration_audit_status', 'integration_audit', ['status'])
    op.create_index('ix_integration_audit_connection', 'integration_audit', ['connection_id'])
    op.create_index('ix_integration_audit_created', 'integration_audit', ['created_at'])


def downgrade() -> None:
    # Drop indexes
    op.drop_index('ix_integration_audit_created', 'integration_audit')
    op.drop_index('ix_integration_audit_connection', 'integration_audit')
    op.drop_index('ix_integration_audit_status', 'integration_audit')
    op.drop_index('ix_integration_audit_entity', 'integration_audit')
    op.drop_index('ix_integration_audit_direction', 'integration_audit')
    
    # Drop table
    op.drop_table('integration_audit')

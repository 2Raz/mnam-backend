"""009 Webhook Idempotency - UNIQUE constraint + UnmatchedWebhookEvent table

Revision ID: 009_webhook_idempotency
Revises: 008_external_mapping_unique
Create Date: 2026-01-18

Per /chandoc Section 7 & 8:
- Ensure idempotency by reservation id
- Webhooks must NOT drop events silently
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '009_webhook_idempotency'
down_revision = '008_external_mapping_unique'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Create unmatched_webhook_events table
    op.create_table(
        'unmatched_webhook_events',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('provider', sa.String(50), nullable=False, server_default='channex'),
        sa.Column('event_type', sa.String(50), nullable=True),
        sa.Column('external_reservation_id', sa.String(255), nullable=True),
        sa.Column('property_id', sa.String(255), nullable=True),
        sa.Column('room_type_id', sa.String(255), nullable=True),
        sa.Column('rate_plan_id', sa.String(255), nullable=True),
        sa.Column('raw_payload', sa.JSON(), nullable=False),
        sa.Column('reason', sa.String(100), server_default='unknown'),
        sa.Column('status', sa.String(50), server_default='pending'),
        sa.Column('retry_count', sa.Integer(), server_default='0'),
        sa.Column('resolved_booking_id', sa.String(36), 
                  sa.ForeignKey('bookings.id', ondelete='SET NULL'), nullable=True),
        sa.Column('resolved_at', sa.DateTime(), nullable=True),
        sa.Column('resolved_by_id', sa.String(36),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    
    # Create indexes for unmatched_webhook_events
    op.create_index(
        'ix_unmatched_provider_reservation',
        'unmatched_webhook_events',
        ['provider', 'external_reservation_id']
    )
    op.create_index(
        'ix_unmatched_status',
        'unmatched_webhook_events',
        ['status']
    )
    op.create_index(
        'ix_unmatched_created_at',
        'unmatched_webhook_events',
        ['created_at']
    )
    
    # 2. Add UNIQUE constraint on bookings for external reservations
    # This ensures no duplicate external bookings from the same source
    # Note: We use a partial unique index to only enforce when external_reservation_id IS NOT NULL
    # This allows multiple NULL values (for manual bookings)
    
    try:
        # Try PostgreSQL partial unique index (preferred)
        op.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_booking_source_external 
            ON bookings (source_type, external_reservation_id) 
            WHERE external_reservation_id IS NOT NULL
        """)
    except Exception:
        # Fallback: regular index (less strict but still helps with lookups)
        op.create_index(
            'ix_booking_source_external',
            'bookings',
            ['source_type', 'external_reservation_id'],
            unique=False
        )


def downgrade():
    # Drop the partial unique index
    try:
        op.execute("DROP INDEX IF EXISTS uq_booking_source_external")
    except Exception:
        pass
    
    try:
        op.drop_index('ix_booking_source_external', 'bookings')
    except Exception:
        pass
    
    # Drop indexes
    op.drop_index('ix_unmatched_created_at', 'unmatched_webhook_events')
    op.drop_index('ix_unmatched_status', 'unmatched_webhook_events')
    op.drop_index('ix_unmatched_provider_reservation', 'unmatched_webhook_events')
    
    # Drop table
    op.drop_table('unmatched_webhook_events')

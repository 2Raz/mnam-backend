"""Add webhook event logs and rate state tables

Revision ID: 005_channex_enhancements
Revises: 004_pricing_integration
Create Date: 2026-01-15

This migration adds:
- webhook_event_logs: Raw webhook storage for async processing
- property_rate_states: Token bucket rate limiting per Channex property
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '005_channex_enhancements'
down_revision = '004_pricing_integration'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Check if we're on PostgreSQL or SQLite
    bind = op.get_bind()
    is_postgres = bind.dialect.name == 'postgresql'
    
    # ==================
    # webhook_event_logs table
    # ==================
    op.create_table(
        'webhook_event_logs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('provider', sa.String(50), nullable=False, server_default='channex'),
        sa.Column('event_id', sa.String(255), nullable=True),
        sa.Column('event_type', sa.String(100), nullable=True),
        sa.Column('external_id', sa.String(255), nullable=True),
        sa.Column('revision_id', sa.String(255), nullable=True),
        sa.Column('payload_json', sa.Text, nullable=False),
        sa.Column('request_headers', sa.Text, nullable=True),
        sa.Column('status', sa.String(20), server_default='received'),
        sa.Column('processed_at', sa.DateTime, nullable=True),
        sa.Column('result_action', sa.String(50), nullable=True),
        sa.Column('result_booking_id', sa.String(36), nullable=True),
        sa.Column('error_message', sa.Text, nullable=True),
        sa.Column('received_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
    )
    
    # Indexes for webhook_event_logs
    op.create_index('ix_webhook_event_provider_event_id', 'webhook_event_logs', ['provider', 'event_id'])
    op.create_index('ix_webhook_event_status', 'webhook_event_logs', ['status', 'received_at'])
    op.create_index('ix_webhook_event_external', 'webhook_event_logs', ['provider', 'external_id', 'revision_id'])
    
    # ==================
    # property_rate_states table
    # ==================
    op.create_table(
        'property_rate_states',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('channex_property_id', sa.String(100), unique=True, nullable=False),
        # Price token bucket
        sa.Column('price_tokens', sa.Float, server_default='10.0'),
        sa.Column('price_last_refill_at', sa.DateTime, server_default=sa.func.now()),
        # Availability token bucket
        sa.Column('avail_tokens', sa.Float, server_default='10.0'),
        sa.Column('avail_last_refill_at', sa.DateTime, server_default=sa.func.now()),
        # Pause state (on 429)
        sa.Column('paused_until', sa.DateTime, nullable=True),
        sa.Column('pause_count', sa.Integer, server_default='0'),
        sa.Column('last_429_at', sa.DateTime, nullable=True),
        # Stats
        sa.Column('total_requests', sa.Integer, server_default='0'),
        sa.Column('total_429s', sa.Integer, server_default='0'),
        # Timestamps
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    
    # Index for property_rate_states
    op.create_index('ix_property_rate_state_property', 'property_rate_states', ['channex_property_id'])


def downgrade() -> None:
    # Drop indexes
    try:
        op.drop_index('ix_property_rate_state_property', 'property_rate_states')
    except:
        pass
    
    try:
        op.drop_index('ix_webhook_event_external', 'webhook_event_logs')
    except:
        pass
    
    try:
        op.drop_index('ix_webhook_event_status', 'webhook_event_logs')
    except:
        pass
    
    try:
        op.drop_index('ix_webhook_event_provider_event_id', 'webhook_event_logs')
    except:
        pass
    
    # Drop tables
    op.drop_table('property_rate_states')
    op.drop_table('webhook_event_logs')

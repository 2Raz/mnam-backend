"""Add pricing and channel integration tables

Revision ID: 004_pricing_integration
Revises: 003_add_missing_columns
Create Date: 2026-01-13

This migration adds:
- pricing_policies: Pricing configuration per unit
- channel_connections: Channex API credentials and status
- external_mappings: Unit to Channex room type mappings
- integration_outbox: Outbound event queue
- integration_logs: Observability logs
- inbound_idempotency: Prevent duplicate webhook processing
- New columns on bookings for external reservation tracking
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '004_pricing_integration'
down_revision = '003_add_missing_columns'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Check if we're on PostgreSQL or SQLite
    bind = op.get_bind()
    is_postgres = bind.dialect.name == 'postgresql'
    
    # ==================
    # pricing_policies table
    # ==================
    op.create_table(
        'pricing_policies',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('unit_id', sa.String(36), sa.ForeignKey('units.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('base_weekday_price', sa.Numeric(10, 2), nullable=False, server_default='100'),
        sa.Column('currency', sa.String(3), server_default='SAR'),
        sa.Column('weekend_markup_percent', sa.Numeric(5, 2), server_default='0'),
        sa.Column('discount_16_percent', sa.Numeric(5, 2), server_default='0'),
        sa.Column('discount_21_percent', sa.Numeric(5, 2), server_default='0'),
        sa.Column('discount_23_percent', sa.Numeric(5, 2), server_default='0'),
        sa.Column('timezone', sa.String(50), server_default='Asia/Riyadh'),
        sa.Column('weekend_days', sa.String(20), server_default='4,5'),
        sa.Column('created_by_id', sa.String(36), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('updated_by_id', sa.String(36), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    
    # ==================
    # channel_connections table
    # ==================
    op.create_table(
        'channel_connections',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('project_id', sa.String(36), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('provider', sa.String(50), nullable=False, server_default='channex'),
        sa.Column('api_key', sa.Text, nullable=False),
        sa.Column('channex_property_id', sa.String(100), nullable=True),
        sa.Column('channex_group_id', sa.String(100), nullable=True),
        sa.Column('webhook_secret', sa.String(255), nullable=True),
        sa.Column('webhook_url', sa.String(500), nullable=True),
        sa.Column('status', sa.String(20), server_default='pending'),
        sa.Column('last_sync_at', sa.DateTime, nullable=True),
        sa.Column('last_error', sa.Text, nullable=True),
        sa.Column('error_count', sa.Integer, server_default='0'),
        sa.Column('requests_today', sa.Integer, server_default='0'),
        sa.Column('rate_limit_reset_at', sa.DateTime, nullable=True),
        sa.Column('created_by_id', sa.String(36), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    
    # ==================
    # external_mappings table
    # ==================
    op.create_table(
        'external_mappings',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('connection_id', sa.String(36), sa.ForeignKey('channel_connections.id', ondelete='CASCADE'), nullable=False),
        sa.Column('unit_id', sa.String(36), sa.ForeignKey('units.id', ondelete='CASCADE'), nullable=True),
        sa.Column('channex_room_type_id', sa.String(100), nullable=True),
        sa.Column('channex_rate_plan_id', sa.String(100), nullable=True),
        sa.Column('mapping_type', sa.String(50), server_default='unit_to_room'),
        sa.Column('is_active', sa.Boolean, server_default='1'),
        sa.Column('last_price_sync_at', sa.DateTime, nullable=True),
        sa.Column('last_avail_sync_at', sa.DateTime, nullable=True),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_external_mapping_unit', 'external_mappings', ['unit_id'])
    op.create_index('ix_external_mapping_connection', 'external_mappings', ['connection_id'])
    
    # ==================
    # integration_outbox table
    # ==================
    json_type = postgresql.JSON if is_postgres else sa.Text
    
    op.create_table(
        'integration_outbox',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('connection_id', sa.String(36), sa.ForeignKey('channel_connections.id', ondelete='CASCADE'), nullable=False),
        sa.Column('event_type', sa.String(50), nullable=False),
        sa.Column('payload', json_type, nullable=False),
        sa.Column('unit_id', sa.String(36), sa.ForeignKey('units.id', ondelete='SET NULL'), nullable=True),
        sa.Column('date_from', sa.DateTime, nullable=True),
        sa.Column('date_to', sa.DateTime, nullable=True),
        sa.Column('status', sa.String(20), server_default='pending'),
        sa.Column('attempts', sa.Integer, server_default='0'),
        sa.Column('max_attempts', sa.Integer, server_default='5'),
        sa.Column('next_attempt_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('last_error', sa.Text, nullable=True),
        sa.Column('response_data', json_type, nullable=True),
        sa.Column('completed_at', sa.DateTime, nullable=True),
        sa.Column('idempotency_key', sa.String(255), nullable=True, unique=True),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_outbox_status_next', 'integration_outbox', ['status', 'next_attempt_at'])
    op.create_index('ix_outbox_connection', 'integration_outbox', ['connection_id'])
    
    # ==================
    # integration_logs table
    # ==================
    op.create_table(
        'integration_logs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('connection_id', sa.String(36), sa.ForeignKey('channel_connections.id', ondelete='SET NULL'), nullable=True),
        sa.Column('outbox_id', sa.String(36), sa.ForeignKey('integration_outbox.id', ondelete='SET NULL'), nullable=True),
        sa.Column('log_type', sa.String(50), nullable=False),
        sa.Column('direction', sa.String(20), nullable=False),
        sa.Column('event_type', sa.String(50), nullable=True),
        sa.Column('request_method', sa.String(10), nullable=True),
        sa.Column('request_url', sa.String(500), nullable=True),
        sa.Column('request_payload', json_type, nullable=True),
        sa.Column('response_status', sa.Integer, nullable=True),
        sa.Column('response_body', json_type, nullable=True),
        sa.Column('success', sa.Boolean, server_default='1'),
        sa.Column('error_message', sa.Text, nullable=True),
        sa.Column('duration_ms', sa.Integer, nullable=True),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index('ix_integration_log_connection', 'integration_logs', ['connection_id'])
    op.create_index('ix_integration_log_created', 'integration_logs', ['created_at'])
    op.create_index('ix_integration_log_type', 'integration_logs', ['log_type', 'direction'])
    
    # ==================
    # inbound_idempotency table
    # ==================
    op.create_table(
        'inbound_idempotency',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('provider', sa.String(50), nullable=False),
        sa.Column('external_event_id', sa.String(255), nullable=False),
        sa.Column('external_reservation_id', sa.String(255), nullable=True),
        sa.Column('revision_id', sa.String(255), nullable=True),
        sa.Column('processed_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('result_action', sa.String(50), nullable=True),
        sa.Column('internal_booking_id', sa.String(36), sa.ForeignKey('bookings.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index('ix_inbound_idempotency_external', 'inbound_idempotency', ['provider', 'external_event_id'], unique=True)
    op.create_index('ix_inbound_idempotency_reservation', 'inbound_idempotency', ['provider', 'external_reservation_id'])
    
    # ==================
    # Add columns to bookings table
    # ==================
    # Use IF NOT EXISTS for PostgreSQL, try/except for SQLite
    if is_postgres:
        op.execute("ALTER TABLE bookings ADD COLUMN IF NOT EXISTS guest_email VARCHAR(255)")
        op.execute("ALTER TABLE bookings ADD COLUMN IF NOT EXISTS channel_source VARCHAR(50) DEFAULT 'direct'")
        op.execute("ALTER TABLE bookings ADD COLUMN IF NOT EXISTS external_reservation_id VARCHAR(255)")
        op.execute("ALTER TABLE bookings ADD COLUMN IF NOT EXISTS external_revision_id VARCHAR(255)")
        op.execute("ALTER TABLE bookings ADD COLUMN IF NOT EXISTS channel_data TEXT")
    else:
        # SQLite - columns will be added by model sync
        try:
            op.add_column('bookings', sa.Column('guest_email', sa.String(255), nullable=True))
        except:
            pass
        try:
            op.add_column('bookings', sa.Column('channel_source', sa.String(50), server_default='direct'))
        except:
            pass
        try:
            op.add_column('bookings', sa.Column('external_reservation_id', sa.String(255), nullable=True))
        except:
            pass
        try:
            op.add_column('bookings', sa.Column('external_revision_id', sa.String(255), nullable=True))
        except:
            pass
        try:
            op.add_column('bookings', sa.Column('channel_data', sa.Text, nullable=True))
        except:
            pass
    
    # Create indexes for booking external fields
    try:
        op.create_index('ix_booking_external_reservation', 'bookings', ['external_reservation_id'])
    except:
        pass
    try:
        op.create_index('ix_booking_channel_source', 'bookings', ['channel_source'])
    except:
        pass


def downgrade() -> None:
    # Drop indexes
    try:
        op.drop_index('ix_booking_channel_source', 'bookings')
    except:
        pass
    try:
        op.drop_index('ix_booking_external_reservation', 'bookings')
    except:
        pass
    
    # Drop columns from bookings (PostgreSQL only supports this easily)
    bind = op.get_bind()
    if bind.dialect.name == 'postgresql':
        op.execute("ALTER TABLE bookings DROP COLUMN IF EXISTS channel_data")
        op.execute("ALTER TABLE bookings DROP COLUMN IF EXISTS external_revision_id")
        op.execute("ALTER TABLE bookings DROP COLUMN IF EXISTS external_reservation_id")
        op.execute("ALTER TABLE bookings DROP COLUMN IF EXISTS channel_source")
        op.execute("ALTER TABLE bookings DROP COLUMN IF EXISTS guest_email")
    
    # Drop tables in reverse order of dependencies
    op.drop_table('inbound_idempotency')
    op.drop_table('integration_logs')
    op.drop_table('integration_outbox')
    op.drop_table('external_mappings')
    op.drop_table('channel_connections')
    op.drop_table('pricing_policies')

"""Webhook Infrastructure Enhancements

Revision ID: 002_webhook_enhancements
Revises: 001_full_schema
Create Date: 2026-02-03

This migration adds:
1. booking_revisions table - For revision tracking and idempotency
2. inventory_calendar table - Daily availability cache
3. integration_alerts table - Health webhook alerts
4. New columns in webhook_event_logs - Operational fields
5. New columns in bookings - customer_snapshot, currency, revision tracking
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '002_webhook_enhancements'
down_revision: Union[str, None] = '001_full_schema'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply webhook infrastructure enhancements."""
    bind = op.get_bind()
    is_postgres = bind.dialect.name == 'postgresql'
    
    # Use appropriate JSON type
    json_type = postgresql.JSON if is_postgres else sa.Text
    
    # ===========================================
    # 1. BOOKING REVISIONS TABLE
    # ===========================================
    op.create_table(
        'booking_revisions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('booking_id', sa.String(36), sa.ForeignKey('bookings.id', ondelete='CASCADE'), nullable=True),
        sa.Column('external_booking_id', sa.String(255), nullable=False),
        sa.Column('revision_id', sa.String(255), nullable=False),
        sa.Column('event_type', sa.String(50), nullable=True),
        sa.Column('payload', json_type, nullable=True),
        sa.Column('applied', sa.Boolean, server_default='1'),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
    )
    op.create_unique_constraint('uq_booking_revision', 'booking_revisions', ['external_booking_id', 'revision_id'])
    op.create_index('ix_booking_revision_booking', 'booking_revisions', ['booking_id'])
    op.create_index('ix_booking_revision_external', 'booking_revisions', ['external_booking_id'])
    
    # ===========================================
    # 2. INVENTORY CALENDAR TABLE
    # ===========================================
    op.create_table(
        'inventory_calendar',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('unit_id', sa.String(36), sa.ForeignKey('units.id', ondelete='CASCADE'), nullable=False),
        sa.Column('date', sa.Date, nullable=False),
        sa.Column('is_available', sa.Boolean, server_default='1'),
        sa.Column('is_blocked', sa.Boolean, server_default='0'),
        sa.Column('block_reason', sa.String(100), nullable=True),
        sa.Column('booking_id', sa.String(36), sa.ForeignKey('bookings.id', ondelete='SET NULL'), nullable=True),
        sa.Column('stop_sell', sa.Boolean, server_default='0'),
        sa.Column('min_stay', sa.Integer, nullable=True),
        sa.Column('max_stay', sa.Integer, nullable=True),
        sa.Column('closed_to_arrival', sa.Boolean, server_default='0'),
        sa.Column('closed_to_departure', sa.Boolean, server_default='0'),
        sa.Column('last_synced_at', sa.DateTime, nullable=True),
        sa.Column('sync_pending', sa.Boolean, server_default='0'),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_unique_constraint('uq_inventory_unit_date', 'inventory_calendar', ['unit_id', 'date'])
    op.create_index('ix_inventory_unit_date', 'inventory_calendar', ['unit_id', 'date'])
    op.create_index('ix_inventory_available', 'inventory_calendar', ['unit_id', 'is_available', 'date'])
    op.create_index('ix_inventory_sync_pending', 'inventory_calendar', ['sync_pending', 'updated_at'])
    
    # ===========================================
    # 3. INTEGRATION ALERTS TABLE
    # ===========================================
    op.create_table(
        'integration_alerts',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('provider', sa.String(50), nullable=False, server_default='channex'),
        sa.Column('property_id', sa.String(255), nullable=True),
        sa.Column('connection_id', sa.String(36), nullable=True),
        sa.Column('alert_type', sa.String(50), nullable=False),
        sa.Column('severity', sa.String(20), server_default='medium'),
        sa.Column('message', sa.Text, nullable=True),
        sa.Column('payload_raw', json_type, nullable=True),
        sa.Column('status', sa.String(20), server_default='open'),
        sa.Column('acknowledged_at', sa.DateTime, nullable=True),
        sa.Column('acknowledged_by_id', sa.String(36), nullable=True),
        sa.Column('resolved_at', sa.DateTime, nullable=True),
        sa.Column('resolved_by_id', sa.String(36), nullable=True),
        sa.Column('resolution_notes', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_alert_status', 'integration_alerts', ['status', 'created_at'])
    op.create_index('ix_alert_type', 'integration_alerts', ['alert_type', 'severity'])
    op.create_index('ix_alert_property', 'integration_alerts', ['property_id', 'status'])
    
    # ===========================================
    # 4. WEBHOOK EVENT LOGS - NEW COLUMNS
    # ===========================================
    op.add_column('webhook_event_logs', sa.Column('endpoint_type', sa.String(50), nullable=True))
    op.add_column('webhook_event_logs', sa.Column('property_id', sa.String(255), nullable=True))
    op.add_column('webhook_event_logs', sa.Column('payload_hash', sa.String(64), nullable=True))
    op.add_column('webhook_event_logs', sa.Column('attempts', sa.Integer, server_default='0'))
    op.add_column('webhook_event_logs', sa.Column('max_attempts', sa.Integer, server_default='5'))
    op.add_column('webhook_event_logs', sa.Column('next_retry_at', sa.DateTime, nullable=True))
    op.add_column('webhook_event_logs', sa.Column('error_code', sa.String(20), nullable=True))
    op.add_column('webhook_event_logs', sa.Column('locked_at', sa.DateTime, nullable=True))
    op.add_column('webhook_event_logs', sa.Column('locked_by', sa.String(100), nullable=True))
    op.add_column('webhook_event_logs', sa.Column('processing_started_at', sa.DateTime, nullable=True))
    op.add_column('webhook_event_logs', sa.Column('processing_finished_at', sa.DateTime, nullable=True))
    
    op.create_index('ix_webhook_event_provider_hash', 'webhook_event_logs', ['provider', 'payload_hash'])
    op.create_index('ix_webhook_event_property', 'webhook_event_logs', ['property_id', 'event_type', 'received_at'])
    op.create_index('ix_webhook_event_retry', 'webhook_event_logs', ['status', 'next_retry_at'])
    
    # ===========================================
    # 5. BOOKINGS - NEW COLUMNS
    # ===========================================
    op.add_column('bookings', sa.Column('customer_snapshot', json_type, nullable=True))
    op.add_column('bookings', sa.Column('currency', sa.String(3), server_default='SAR'))
    op.add_column('bookings', sa.Column('last_applied_revision_id', sa.String(255), nullable=True))
    op.add_column('bookings', sa.Column('last_applied_revision_at', sa.DateTime, nullable=True))


def downgrade() -> None:
    """Rollback webhook infrastructure enhancements."""
    # Drop booking columns
    op.drop_column('bookings', 'last_applied_revision_at')
    op.drop_column('bookings', 'last_applied_revision_id')
    op.drop_column('bookings', 'currency')
    op.drop_column('bookings', 'customer_snapshot')
    
    # Drop webhook_event_logs indexes and columns
    op.drop_index('ix_webhook_event_retry', table_name='webhook_event_logs')
    op.drop_index('ix_webhook_event_property', table_name='webhook_event_logs')
    op.drop_index('ix_webhook_event_provider_hash', table_name='webhook_event_logs')
    
    op.drop_column('webhook_event_logs', 'processing_finished_at')
    op.drop_column('webhook_event_logs', 'processing_started_at')
    op.drop_column('webhook_event_logs', 'locked_by')
    op.drop_column('webhook_event_logs', 'locked_at')
    op.drop_column('webhook_event_logs', 'error_code')
    op.drop_column('webhook_event_logs', 'next_retry_at')
    op.drop_column('webhook_event_logs', 'max_attempts')
    op.drop_column('webhook_event_logs', 'attempts')
    op.drop_column('webhook_event_logs', 'payload_hash')
    op.drop_column('webhook_event_logs', 'property_id')
    op.drop_column('webhook_event_logs', 'endpoint_type')
    
    # Drop tables
    op.drop_table('integration_alerts')
    op.drop_table('inventory_calendar')
    op.drop_table('booking_revisions')

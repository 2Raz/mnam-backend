"""Full Database Schema - Consolidated Migration

Revision ID: 001_full_schema
Revises: 
Create Date: 2026-01-31

This is a clean, consolidated migration that creates all tables.
It replaces all previous migrations with a single, complete schema.

Tables:
- Core: users, refresh_tokens, owners, projects, units, customers, bookings, transactions
- Employee: employee_activity_logs, employee_targets, employee_performance_summaries, employee_tasks, employee_sessions, employee_attendance
- Notifications: notifications
- Pricing: pricing_policies
- Channel Integration: channel_connections, external_mappings, integration_outbox, integration_logs, inbound_idempotency, integration_audit, webhook_event_logs, property_rate_states, unmatched_webhook_events
- System: audit_logs
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '001_full_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create all database tables."""
    bind = op.get_bind()
    is_postgres = bind.dialect.name == 'postgresql'
    
    # Use appropriate JSON type
    json_type = postgresql.JSON if is_postgres else sa.Text
    
    # ===========================================
    # 1. USERS TABLE (Core - No Dependencies)
    # ===========================================
    op.create_table(
        'users',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('username', sa.String(50), unique=True, nullable=False),
        sa.Column('email', sa.String(100), unique=True, nullable=False),
        sa.Column('hashed_password', sa.String(255), nullable=False),
        sa.Column('first_name', sa.String(50), nullable=False),
        sa.Column('last_name', sa.String(50), default=""),
        sa.Column('phone', sa.String(20), nullable=True),
        sa.Column('role', sa.String(20), default='customers_agent'),
        sa.Column('is_active', sa.Boolean, default=True),
        sa.Column('is_system_owner', sa.Boolean, default=False),
        sa.Column('last_login', sa.DateTime, nullable=True),
        # Soft Delete
        sa.Column('is_deleted', sa.Boolean, default=False),
        sa.Column('deleted_at', sa.DateTime, nullable=True),
        sa.Column('deleted_by_id', sa.String(36), nullable=True),
        # Timestamps
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_users_username', 'users', ['username'])
    op.create_index('ix_users_email', 'users', ['email'])
    op.create_index('ix_users_is_deleted', 'users', ['is_deleted'])
    
    # Add self-referencing FK for deleted_by_id
    op.create_foreign_key('fk_users_deleted_by', 'users', 'users', ['deleted_by_id'], ['id'], ondelete='SET NULL')
    
    # ===========================================
    # 2. REFRESH TOKENS TABLE
    # ===========================================
    op.create_table(
        'refresh_tokens',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('token_hash', sa.String(64), nullable=False, unique=True),
        sa.Column('device_info', sa.String(255), nullable=True),
        sa.Column('ip_address', sa.String(45), nullable=True),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('expires_at', sa.DateTime, nullable=False),
        sa.Column('last_used_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('is_revoked', sa.Boolean, default=False),
        sa.Column('revoked_at', sa.DateTime, nullable=True),
    )
    op.create_index('ix_refresh_tokens_user_id', 'refresh_tokens', ['user_id'])
    op.create_index('ix_refresh_tokens_token_hash', 'refresh_tokens', ['token_hash'])
    op.create_index('ix_refresh_tokens_user_active', 'refresh_tokens', ['user_id', 'is_revoked'])
    
    # ===========================================
    # 3. OWNERS TABLE
    # ===========================================
    op.create_table(
        'owners',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('owner_name', sa.String(100), nullable=False),
        sa.Column('owner_mobile_phone', sa.String(20), nullable=False),
        sa.Column('paypal_email', sa.String(100), nullable=True),
        sa.Column('note', sa.Text, nullable=True),
        # Tracking
        sa.Column('created_by_id', sa.String(36), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('updated_by_id', sa.String(36), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        # Soft Delete
        sa.Column('is_deleted', sa.Boolean, default=False),
        sa.Column('deleted_at', sa.DateTime, nullable=True),
        sa.Column('deleted_by_id', sa.String(36), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        # Timestamps
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_owners_is_deleted', 'owners', ['is_deleted'])
    
    # ===========================================
    # 4. PROJECTS TABLE
    # ===========================================
    op.create_table(
        'projects',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('owner_id', sa.String(36), sa.ForeignKey('owners.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('city', sa.String(50), nullable=True),
        sa.Column('district', sa.String(50), nullable=True),
        sa.Column('security_guard_phone', sa.String(20), nullable=True),
        sa.Column('property_manager_phone', sa.String(20), nullable=True),
        sa.Column('map_url', sa.String(500), nullable=True),
        # Contract fields
        sa.Column('contract_no', sa.String(50), nullable=True),
        sa.Column('contract_status', sa.String(20), default='ساري'),
        sa.Column('contract_duration', sa.Integer, nullable=True),
        sa.Column('commission_percent', sa.Numeric(5, 2), default=0),
        sa.Column('bank_name', sa.String(100), nullable=True),
        sa.Column('bank_iban', sa.String(50), nullable=True),
        # Tracking
        sa.Column('created_by_id', sa.String(36), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('updated_by_id', sa.String(36), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        # Soft Delete
        sa.Column('is_deleted', sa.Boolean, default=False),
        sa.Column('deleted_at', sa.DateTime, nullable=True),
        sa.Column('deleted_by_id', sa.String(36), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        # Timestamps
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_projects_owner_id', 'projects', ['owner_id'])
    op.create_index('ix_projects_is_deleted', 'projects', ['is_deleted'])
    
    # ===========================================
    # 5. UNITS TABLE
    # ===========================================
    op.create_table(
        'units',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('project_id', sa.String(36), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('unit_name', sa.String(100), nullable=False),
        sa.Column('unit_type', sa.String(30), default='شقة'),
        sa.Column('rooms', sa.Integer, default=1),
        sa.Column('floor_number', sa.Integer, default=0),
        sa.Column('unit_area', sa.Float, default=0),
        sa.Column('status', sa.String(30), default='متاحة'),
        sa.Column('price_days_of_week', sa.Numeric(10, 2), default=0),
        sa.Column('price_in_weekends', sa.Numeric(10, 2), default=0),
        sa.Column('amenities', json_type, nullable=True),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('permit_no', sa.String(50), nullable=True),
        sa.Column('access_info', sa.Text, nullable=True),
        sa.Column('booking_links', json_type, nullable=True),
        # Tracking
        sa.Column('created_by_id', sa.String(36), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('updated_by_id', sa.String(36), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        # Soft Delete
        sa.Column('is_deleted', sa.Boolean, default=False),
        sa.Column('deleted_at', sa.DateTime, nullable=True),
        sa.Column('deleted_by_id', sa.String(36), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        # Timestamps
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_units_project_id', 'units', ['project_id'])
    op.create_index('ix_units_is_deleted', 'units', ['is_deleted'])
    
    # ===========================================
    # 6. CUSTOMERS TABLE
    # ===========================================
    op.create_table(
        'customers',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('phone', sa.String(20), nullable=False, unique=True),
        sa.Column('email', sa.String(255), nullable=True),
        sa.Column('gender', sa.String(20), nullable=True),
        # Stats
        sa.Column('booking_count', sa.Integer, default=0),
        sa.Column('completed_booking_count', sa.Integer, default=0),
        sa.Column('total_revenue', sa.Float, default=0.0),
        # Status
        sa.Column('is_banned', sa.Boolean, default=False),
        sa.Column('ban_reason', sa.Text, nullable=True),
        sa.Column('is_profile_complete', sa.Boolean, default=False),
        sa.Column('notes', sa.Text, nullable=True),
        # Soft Delete
        sa.Column('is_deleted', sa.Boolean, default=False),
        sa.Column('deleted_at', sa.DateTime, nullable=True),
        sa.Column('deleted_by_id', sa.String(36), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        # Timestamps
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_customers_phone', 'customers', ['phone'])
    op.create_index('ix_customers_is_deleted', 'customers', ['is_deleted'])
    
    # ===========================================
    # 7. BOOKINGS TABLE
    # ===========================================
    op.create_table(
        'bookings',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('unit_id', sa.String(36), sa.ForeignKey('units.id', ondelete='CASCADE'), nullable=False),
        sa.Column('customer_id', sa.String(36), sa.ForeignKey('customers.id', ondelete='SET NULL'), nullable=True),
        sa.Column('guest_name', sa.String(100), nullable=False),
        sa.Column('guest_phone', sa.String(20), nullable=True),
        sa.Column('guest_email', sa.String(255), nullable=True),
        sa.Column('check_in_date', sa.Date, nullable=False),
        sa.Column('check_out_date', sa.Date, nullable=False),
        sa.Column('total_price', sa.Numeric(10, 2), default=0),
        sa.Column('status', sa.String(30), default='مؤكد'),
        sa.Column('notes', sa.Text, nullable=True),
        # Channel Integration
        sa.Column('source_type', sa.String(50), default='manual'),
        sa.Column('channel_source', sa.String(50), default='direct'),
        sa.Column('external_reservation_id', sa.String(255), nullable=True),
        sa.Column('external_revision_id', sa.String(255), nullable=True),
        sa.Column('channel_data', sa.Text, nullable=True),
        # Tracking
        sa.Column('created_by_id', sa.String(36), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('updated_by_id', sa.String(36), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        # Soft Delete
        sa.Column('is_deleted', sa.Boolean, default=False),
        sa.Column('deleted_at', sa.DateTime, nullable=True),
        sa.Column('deleted_by_id', sa.String(36), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        # Timestamps
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_bookings_unit_id', 'bookings', ['unit_id'])
    op.create_index('ix_bookings_customer_id', 'bookings', ['customer_id'])
    op.create_index('ix_bookings_dates', 'bookings', ['check_in_date', 'check_out_date'])
    op.create_index('ix_bookings_external_reservation', 'bookings', ['external_reservation_id'])
    op.create_index('ix_bookings_channel_source', 'bookings', ['channel_source'])
    op.create_index('ix_bookings_source_type', 'bookings', ['source_type'])
    op.create_index('ix_bookings_is_deleted', 'bookings', ['is_deleted'])
    
    # ===========================================
    # 8. TRANSACTIONS TABLE
    # ===========================================
    op.create_table(
        'transactions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('project_id', sa.String(36), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('unit_id', sa.String(36), sa.ForeignKey('units.id', ondelete='SET NULL'), nullable=True),
        sa.Column('description', sa.String(255), nullable=False),
        sa.Column('date', sa.Date, nullable=False),
        sa.Column('amount', sa.Numeric(10, 2), nullable=False),
        sa.Column('type', sa.String(20), nullable=False),
        sa.Column('category', sa.String(50), nullable=True),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index('ix_transactions_project_id', 'transactions', ['project_id'])
    
    # ===========================================
    # 9. NOTIFICATIONS TABLE
    # ===========================================
    op.create_table(
        'notifications',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=True),
        sa.Column('type', sa.String(50), nullable=False),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('message', sa.Text, nullable=True),
        sa.Column('entity_type', sa.String(50), nullable=True),
        sa.Column('entity_id', sa.String(36), nullable=True),
        sa.Column('is_read', sa.Boolean, default=False),
        sa.Column('read_at', sa.DateTime, nullable=True),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index('ix_notifications_user_id', 'notifications', ['user_id'])
    op.create_index('ix_notifications_is_read', 'notifications', ['is_read'])
    op.create_index('ix_notifications_type', 'notifications', ['type'])
    op.create_index('ix_notifications_created_at', 'notifications', ['created_at'])
    
    # ===========================================
    # 10. EMPLOYEE ACTIVITY LOGS TABLE
    # ===========================================
    op.create_table(
        'employee_activity_logs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('employee_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('activity_type', sa.String(50), nullable=False),
        sa.Column('entity_type', sa.String(50), nullable=True),
        sa.Column('entity_id', sa.String(36), nullable=True),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('amount', sa.Float, default=0),
        sa.Column('metadata_json', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index('ix_employee_activity_logs_employee_id', 'employee_activity_logs', ['employee_id'])
    op.create_index('ix_employee_activity_logs_type', 'employee_activity_logs', ['activity_type'])
    op.create_index('ix_employee_activity_logs_created_at', 'employee_activity_logs', ['created_at'])
    
    # ===========================================
    # 11. EMPLOYEE TARGETS TABLE
    # ===========================================
    op.create_table(
        'employee_targets',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('employee_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('period', sa.String(20), default='monthly'),
        sa.Column('start_date', sa.Date, nullable=False),
        sa.Column('end_date', sa.Date, nullable=False),
        # Customers Agent targets
        sa.Column('target_bookings', sa.Integer, default=0),
        sa.Column('target_booking_revenue', sa.Float, default=0),
        sa.Column('target_new_customers', sa.Integer, default=0),
        sa.Column('target_completion_rate', sa.Float, default=0),
        # Owners Agent targets
        sa.Column('target_new_owners', sa.Integer, default=0),
        sa.Column('target_new_projects', sa.Integer, default=0),
        sa.Column('target_new_units', sa.Integer, default=0),
        # General
        sa.Column('notes', sa.Text, nullable=True),
        sa.Column('set_by_id', sa.String(36), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('is_active', sa.Boolean, default=True),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_employee_targets_employee_id', 'employee_targets', ['employee_id'])
    
    # ===========================================
    # 12. EMPLOYEE PERFORMANCE SUMMARIES TABLE
    # ===========================================
    op.create_table(
        'employee_performance_summaries',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('employee_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('period_type', sa.String(20), nullable=False),
        sa.Column('period_start', sa.Date, nullable=False),
        sa.Column('period_end', sa.Date, nullable=False),
        # Booking stats
        sa.Column('total_bookings_created', sa.Integer, default=0),
        sa.Column('total_bookings_completed', sa.Integer, default=0),
        sa.Column('total_bookings_cancelled', sa.Integer, default=0),
        sa.Column('total_booking_revenue', sa.Float, default=0),
        sa.Column('completion_rate', sa.Float, default=0),
        # Customer stats
        sa.Column('new_customers_added', sa.Integer, default=0),
        sa.Column('customers_banned', sa.Integer, default=0),
        # Owner stats
        sa.Column('new_owners_added', sa.Integer, default=0),
        sa.Column('new_projects_created', sa.Integer, default=0),
        sa.Column('new_units_added', sa.Integer, default=0),
        # General stats
        sa.Column('total_activities', sa.Integer, default=0),
        sa.Column('average_response_time', sa.Float, default=0),
        sa.Column('target_achievement_rate', sa.Float, default=0),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_employee_performance_employee_id', 'employee_performance_summaries', ['employee_id'])
    op.create_index('ix_employee_performance_period_start', 'employee_performance_summaries', ['period_start'])
    
    # ===========================================
    # 13. EMPLOYEE TASKS TABLE
    # ===========================================
    op.create_table(
        'employee_tasks',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('due_date', sa.Date, nullable=True),
        sa.Column('status', sa.String(20), default='todo'),
        sa.Column('assigned_to_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_by_id', sa.String(36), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_employee_tasks_assigned_to_id', 'employee_tasks', ['assigned_to_id'])
    
    # ===========================================
    # 14. EMPLOYEE SESSIONS TABLE
    # ===========================================
    op.create_table(
        'employee_sessions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('employee_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('login_at', sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column('logout_at', sa.DateTime, nullable=True),
        sa.Column('last_heartbeat', sa.DateTime, server_default=sa.func.now()),
        sa.Column('duration_minutes', sa.Integer, default=0),
        sa.Column('is_active', sa.Boolean, default=True),
        sa.Column('ip_address', sa.String(50), nullable=True),
        sa.Column('user_agent', sa.String(500), nullable=True),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index('ix_employee_sessions_employee_id', 'employee_sessions', ['employee_id'])
    op.create_index('ix_employee_sessions_is_active', 'employee_sessions', ['is_active'])
    
    # ===========================================
    # 15. EMPLOYEE ATTENDANCE TABLE
    # ===========================================
    op.create_table(
        'employee_attendance',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('employee_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('date', sa.Date, nullable=False),
        sa.Column('first_login', sa.DateTime, nullable=True),
        sa.Column('last_logout', sa.DateTime, nullable=True),
        sa.Column('last_activity', sa.DateTime, nullable=True),
        sa.Column('total_sessions', sa.Integer, default=0),
        sa.Column('total_duration_minutes', sa.Integer, default=0),
        sa.Column('activities_count', sa.Integer, default=0),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.UniqueConstraint('employee_id', 'date', name='uq_employee_date'),
    )
    op.create_index('ix_employee_attendance_employee_id', 'employee_attendance', ['employee_id'])
    op.create_index('ix_employee_attendance_date', 'employee_attendance', ['date'])
    
    # ===========================================
    # 16. PRICING POLICIES TABLE
    # ===========================================
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
    
    # ===========================================
    # 17. CHANNEL CONNECTIONS TABLE
    # ===========================================
    op.create_table(
        'channel_connections',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('project_id', sa.String(36), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('provider', sa.String(50), default='channex', nullable=False),
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
        sa.Column('deleted_at', sa.DateTime, nullable=True),
    )
    op.create_index('ix_channel_connections_project_id', 'channel_connections', ['project_id'])
    op.create_index('ix_channel_connections_deleted_at', 'channel_connections', ['deleted_at'])
    
    # ===========================================
    # 18. EXTERNAL MAPPINGS TABLE
    # ===========================================
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
        sa.UniqueConstraint('connection_id', 'unit_id', name='uq_external_mapping_connection_unit'),
    )
    op.create_index('ix_external_mapping_unit', 'external_mappings', ['unit_id'])
    op.create_index('ix_external_mapping_connection', 'external_mappings', ['connection_id'])
    
    # ===========================================
    # 19. INTEGRATION OUTBOX TABLE
    # ===========================================
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
    
    # ===========================================
    # 20. INTEGRATION LOGS TABLE
    # ===========================================
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
    
    # ===========================================
    # 21. INBOUND IDEMPOTENCY TABLE
    # ===========================================
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
    
    # ===========================================
    # 22. INTEGRATION AUDIT TABLE
    # ===========================================
    op.create_table(
        'integration_audit',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('connection_id', sa.String(36), sa.ForeignKey('channel_connections.id', ondelete='SET NULL'), nullable=True),
        sa.Column('direction', sa.String(20), nullable=False),
        sa.Column('entity_type', sa.String(50), nullable=False),
        sa.Column('external_id', sa.String(255), nullable=True),
        sa.Column('unit_id', sa.String(36), sa.ForeignKey('units.id', ondelete='SET NULL'), nullable=True),
        sa.Column('payload_hash', sa.String(64), nullable=True),
        sa.Column('payload_size_bytes', sa.Integer, nullable=True),
        sa.Column('date_from', sa.DateTime, nullable=True),
        sa.Column('date_to', sa.DateTime, nullable=True),
        sa.Column('records_count', sa.Integer, nullable=True),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('error_message', sa.Text, nullable=True),
        sa.Column('retry_count', sa.Integer, default=0),
        sa.Column('started_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('completed_at', sa.DateTime, nullable=True),
        sa.Column('duration_ms', sa.Integer, nullable=True),
        sa.Column('request_id', sa.String(50), nullable=True),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index('ix_integration_audit_direction', 'integration_audit', ['direction'])
    op.create_index('ix_integration_audit_entity', 'integration_audit', ['entity_type'])
    op.create_index('ix_integration_audit_status', 'integration_audit', ['status'])
    op.create_index('ix_integration_audit_connection', 'integration_audit', ['connection_id'])
    op.create_index('ix_integration_audit_created', 'integration_audit', ['created_at'])
    
    # ===========================================
    # 23. WEBHOOK EVENT LOGS TABLE
    # ===========================================
    op.create_table(
        'webhook_event_logs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('provider', sa.String(50), server_default='channex', nullable=False),
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
    op.create_index('ix_webhook_event_provider_event_id', 'webhook_event_logs', ['provider', 'event_id'])
    op.create_index('ix_webhook_event_status', 'webhook_event_logs', ['status', 'received_at'])
    op.create_index('ix_webhook_event_external', 'webhook_event_logs', ['provider', 'external_id', 'revision_id'])
    
    # ===========================================
    # 24. PROPERTY RATE STATES TABLE
    # ===========================================
    op.create_table(
        'property_rate_states',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('channex_property_id', sa.String(100), unique=True, nullable=False),
        sa.Column('price_tokens', sa.Float, server_default='10.0'),
        sa.Column('price_last_refill_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('avail_tokens', sa.Float, server_default='10.0'),
        sa.Column('avail_last_refill_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('paused_until', sa.DateTime, nullable=True),
        sa.Column('pause_count', sa.Integer, server_default='0'),
        sa.Column('last_429_at', sa.DateTime, nullable=True),
        sa.Column('total_requests', sa.Integer, server_default='0'),
        sa.Column('total_429s', sa.Integer, server_default='0'),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_property_rate_state_property', 'property_rate_states', ['channex_property_id'])
    
    # ===========================================
    # 25. UNMATCHED WEBHOOK EVENTS TABLE
    # ===========================================
    op.create_table(
        'unmatched_webhook_events',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('provider', sa.String(50), nullable=False, server_default='channex'),
        sa.Column('event_type', sa.String(50), nullable=True),
        sa.Column('external_reservation_id', sa.String(255), nullable=True),
        sa.Column('property_id', sa.String(255), nullable=True),
        sa.Column('room_type_id', sa.String(255), nullable=True),
        sa.Column('rate_plan_id', sa.String(255), nullable=True),
        sa.Column('raw_payload', json_type, nullable=False),
        sa.Column('reason', sa.String(100), server_default='unknown'),
        sa.Column('status', sa.String(50), server_default='pending'),
        sa.Column('retry_count', sa.Integer, server_default='0'),
        sa.Column('resolved_booking_id', sa.String(36), sa.ForeignKey('bookings.id', ondelete='SET NULL'), nullable=True),
        sa.Column('resolved_at', sa.DateTime, nullable=True),
        sa.Column('resolved_by_id', sa.String(36), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_unmatched_provider_reservation', 'unmatched_webhook_events', ['provider', 'external_reservation_id'])
    op.create_index('ix_unmatched_status', 'unmatched_webhook_events', ['status'])
    op.create_index('ix_unmatched_created_at', 'unmatched_webhook_events', ['created_at'])
    
    # ===========================================
    # 26. AUDIT LOGS TABLE
    # ===========================================
    op.create_table(
        'audit_logs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('user_name', sa.String(100), nullable=True),
        sa.Column('activity_type', sa.String(50), nullable=False),
        sa.Column('entity_type', sa.String(50), nullable=False),
        sa.Column('entity_id', sa.String(36), nullable=True),
        sa.Column('entity_name', sa.String(200), nullable=True),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('old_values', json_type, nullable=True),
        sa.Column('new_values', json_type, nullable=True),
        sa.Column('ip_address', sa.String(45), nullable=True),
        sa.Column('user_agent', sa.String(500), nullable=True),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index('ix_audit_logs_user_id', 'audit_logs', ['user_id'])
    op.create_index('ix_audit_logs_activity_type', 'audit_logs', ['activity_type'])
    op.create_index('ix_audit_logs_entity_type', 'audit_logs', ['entity_type'])
    op.create_index('ix_audit_logs_entity_id', 'audit_logs', ['entity_id'])
    op.create_index('ix_audit_logs_created_at', 'audit_logs', ['created_at'])


def downgrade() -> None:
    """Drop all tables in reverse dependency order."""
    # Drop tables in reverse order
    tables = [
        'audit_logs',
        'unmatched_webhook_events',
        'property_rate_states',
        'webhook_event_logs',
        'integration_audit',
        'inbound_idempotency',
        'integration_logs',
        'integration_outbox',
        'external_mappings',
        'channel_connections',
        'pricing_policies',
        'employee_attendance',
        'employee_sessions',
        'employee_tasks',
        'employee_performance_summaries',
        'employee_targets',
        'employee_activity_logs',
        'notifications',
        'transactions',
        'bookings',
        'customers',
        'units',
        'projects',
        'owners',
        'refresh_tokens',
        'users',
    ]
    
    for table in tables:
        try:
            op.drop_table(table)
        except Exception:
            pass

"""
Add soft delete columns and notifications table

Revision ID: 002_soft_delete_notifications
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '002_soft_delete_notifications'
down_revision = '001_initial'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """إضافة أعمدة الحذف الناعم وجدول الإشعارات"""
    
    # ========== Soft Delete للكيانات ==========
    
    # Users
    op.add_column('users', sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('users', sa.Column('deleted_at', sa.DateTime(), nullable=True))
    op.add_column('users', sa.Column('deleted_by_id', sa.String(36), nullable=True))
    
    # Owners
    op.add_column('owners', sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('owners', sa.Column('deleted_at', sa.DateTime(), nullable=True))
    op.add_column('owners', sa.Column('deleted_by_id', sa.String(36), nullable=True))
    
    # Projects
    op.add_column('projects', sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('projects', sa.Column('deleted_at', sa.DateTime(), nullable=True))
    op.add_column('projects', sa.Column('deleted_by_id', sa.String(36), nullable=True))
    
    # Units
    op.add_column('units', sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('units', sa.Column('deleted_at', sa.DateTime(), nullable=True))
    op.add_column('units', sa.Column('deleted_by_id', sa.String(36), nullable=True))
    
    # Customers
    op.add_column('customers', sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('customers', sa.Column('deleted_at', sa.DateTime(), nullable=True))
    op.add_column('customers', sa.Column('deleted_by_id', sa.String(36), nullable=True))
    
    # Bookings
    op.add_column('bookings', sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('bookings', sa.Column('deleted_at', sa.DateTime(), nullable=True))
    op.add_column('bookings', sa.Column('deleted_by_id', sa.String(36), nullable=True))
    
    # ========== جدول الإشعارات ==========
    op.create_table(
        'notifications',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=True),  # Null = broadcast
        sa.Column('type', sa.String(50), nullable=False),  # booking_new, booking_cancelled, checkout, etc.
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('message', sa.Text(), nullable=True),
        sa.Column('entity_type', sa.String(50), nullable=True),  # booking, unit, customer, etc.
        sa.Column('entity_id', sa.String(36), nullable=True),
        sa.Column('is_read', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('read_at', sa.DateTime(), nullable=True),
    )
    
    # Indexes
    op.create_index('ix_notifications_user_id', 'notifications', ['user_id'])
    op.create_index('ix_notifications_is_read', 'notifications', ['is_read'])
    op.create_index('ix_notifications_type', 'notifications', ['type'])
    op.create_index('ix_notifications_created_at', 'notifications', ['created_at'])


def downgrade() -> None:
    """التراجع عن التغييرات"""
    
    # حذف جدول الإشعارات
    op.drop_index('ix_notifications_created_at', table_name='notifications')
    op.drop_index('ix_notifications_type', table_name='notifications')
    op.drop_index('ix_notifications_is_read', table_name='notifications')
    op.drop_index('ix_notifications_user_id', table_name='notifications')
    op.drop_table('notifications')
    
    # حذف أعمدة Soft Delete
    op.drop_column('bookings', 'deleted_by_id')
    op.drop_column('bookings', 'deleted_at')
    op.drop_column('bookings', 'is_deleted')
    
    op.drop_column('customers', 'deleted_by_id')
    op.drop_column('customers', 'deleted_at')
    op.drop_column('customers', 'is_deleted')
    
    op.drop_column('units', 'deleted_by_id')
    op.drop_column('units', 'deleted_at')
    op.drop_column('units', 'is_deleted')
    
    op.drop_column('projects', 'deleted_by_id')
    op.drop_column('projects', 'deleted_at')
    op.drop_column('projects', 'is_deleted')
    
    op.drop_column('owners', 'deleted_by_id')
    op.drop_column('owners', 'deleted_at')
    op.drop_column('owners', 'is_deleted')
    
    op.drop_column('users', 'deleted_by_id')
    op.drop_column('users', 'deleted_at')
    op.drop_column('users', 'is_deleted')

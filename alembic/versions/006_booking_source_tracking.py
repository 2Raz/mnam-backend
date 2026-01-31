"""Add source_type to bookings for channel integration tracking

Revision ID: 006_booking_source
Revises: 005_channex_enhancements
Create Date: 2026-01-15

This migration adds the source_type column to track HOW bookings arrive:
- 'manual': Created in MNAM dashboard
- 'channex': Received via Channex webhook
- 'direct_api': Imported via direct API

Also adds the corresponding index for filtering performance.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '006_booking_source'
down_revision = '005_channex_enhancements'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add source_type column with default 'manual' for existing bookings
    # Using try/except to handle case where column already exists
    try:
        op.add_column('bookings', sa.Column('source_type', sa.String(50), nullable=True))
        
        # Set default value for existing rows
        op.execute("UPDATE bookings SET source_type = 'manual' WHERE source_type IS NULL")
        
        # Add index for filtering
        op.create_index('ix_booking_source_type', 'bookings', ['source_type'])
        
        print("✅ Added source_type column to bookings")
    except Exception as e:
        print(f"⚠️ source_type column may already exist: {e}")
    
    # Ensure channel_source has 'gathern' and 'unknown' values by updating any old data
    # (No schema change needed, just data migration)
    try:
        # Update any 'channex' channel_source to 'unknown' if external_reservation_id is set
        # (These were from Channex but actual OTA was not tracked)
        op.execute("""
            UPDATE bookings 
            SET channel_source = CASE 
                WHEN channel_source = 'channex' AND external_reservation_id IS NOT NULL 
                THEN 'unknown'
                ELSE channel_source
            END
            WHERE channel_source = 'channex'
        """)
        print("✅ Updated legacy channel_source values")
    except Exception as e:
        print(f"⚠️ Could not update legacy channel_source: {e}")


def downgrade() -> None:
    try:
        op.drop_index('ix_booking_source_type', table_name='bookings')
    except:
        pass
    
    try:
        op.drop_column('bookings', 'source_type')
    except:
        pass

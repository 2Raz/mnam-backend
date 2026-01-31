"""Add UNIQUE constraint on external_mappings (connection_id, unit_id)

Revision ID: 008_external_mapping_unique
Revises: 007_integration_audit
Create Date: 2026-01-18

This migration adds a UNIQUE constraint to prevent duplicate mappings
for the same unit within a connection, as required by /chandoc Section 5.3.

The migration will fail if duplicates already exist in the database.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text

# revision identifiers, used by Alembic.
revision = '008_external_mapping_unique'
down_revision = '007_integration_audit'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add UNIQUE(connection_id, unit_id) constraint to external_mappings."""
    bind = op.get_bind()
    
    # Pre-check: Find any existing duplicates
    result = bind.execute(text("""
        SELECT connection_id, unit_id, COUNT(*) as cnt
        FROM external_mappings
        WHERE unit_id IS NOT NULL
        GROUP BY connection_id, unit_id
        HAVING COUNT(*) > 1
    """))
    
    duplicates = result.fetchall()
    
    if duplicates:
        # Format duplicate info for error message
        dup_info = "\n".join([
            f"  - connection_id={d[0]}, unit_id={d[1]}, count={d[2]}"
            for d in duplicates
        ])
        raise Exception(
            f"Cannot add UNIQUE constraint: Duplicate mappings found!\n"
            f"Please resolve these duplicates before applying migration:\n"
            f"{dup_info}\n\n"
            f"Resolution: Delete duplicate rows from external_mappings table, "
            f"keeping only one mapping per (connection_id, unit_id) pair."
        )
    
    # Add the unique constraint
    op.create_unique_constraint(
        'uq_external_mapping_connection_unit',
        'external_mappings',
        ['connection_id', 'unit_id']
    )


def downgrade() -> None:
    """Remove UNIQUE constraint from external_mappings."""
    op.drop_constraint(
        'uq_external_mapping_connection_unit',
        'external_mappings',
        type_='unique'
    )

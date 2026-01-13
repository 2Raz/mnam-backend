"""Add refresh_tokens table and last_login column

This migration adds:
1. refresh_tokens table for multi-session token management
2. last_login column to users table

Run with: python -m migrations.add_refresh_tokens
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.database import engine, SessionLocal


def upgrade():
    """Apply migration"""
    with engine.connect() as conn:
        # Create refresh_tokens table
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS refresh_tokens (
                id VARCHAR(36) PRIMARY KEY,
                user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                token_hash VARCHAR(64) NOT NULL UNIQUE,
                device_info VARCHAR(255),
                ip_address VARCHAR(45),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NOT NULL,
                last_used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_revoked BOOLEAN DEFAULT FALSE,
                revoked_at TIMESTAMP
            )
        """))
        
        # Create indexes
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_refresh_tokens_token_hash 
            ON refresh_tokens(token_hash)
        """))
        
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_refresh_tokens_user_id 
            ON refresh_tokens(user_id)
        """))
        
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_refresh_tokens_user_active 
            ON refresh_tokens(user_id, is_revoked)
        """))
        
        # Add last_login column to users if not exists
        try:
            conn.execute(text("""
                ALTER TABLE users ADD COLUMN last_login TIMESTAMP
            """))
        except Exception:
            # Column already exists
            pass
        
        conn.commit()
        print("✅ Migration applied: refresh_tokens table created")


def downgrade():
    """Revert migration"""
    with engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS refresh_tokens"))
        
        try:
            conn.execute(text("ALTER TABLE users DROP COLUMN last_login"))
        except Exception:
            pass
        
        conn.commit()
        print("✅ Migration reverted: refresh_tokens table dropped")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--downgrade", action="store_true", help="Revert migration")
    args = parser.parse_args()
    
    if args.downgrade:
        downgrade()
    else:
        upgrade()

"""
Password Reset Utility for mnam-backend
Run this script to reset a user's password.

Usage:
    python reset_password.py <username> <new_password>
    
Example:
    python reset_password.py admin NewPassword123!
    python reset_password.py Head_Admin MySecurePass!
"""

import sys
import os

# Add app to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import SessionLocal
from app.models.user import User
from app.utils.security import hash_password, validate_password_strength


def reset_password(username: str, new_password: str) -> bool:
    """Reset a user's password"""
    
    # Validate password strength
    is_valid, error_msg = validate_password_strength(new_password)
    if not is_valid:
        print(f"❌ Password error: {error_msg}")
        return False
    
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        
        if not user:
            print(f"❌ User '{username}' not found in database")
            # List existing users
            all_users = db.query(User).all()
            print("\n📋 Existing users:")
            for u in all_users:
                print(f"   - {u.username} ({u.email})")
            return False
        
        # Hash and update password
        user.hashed_password = hash_password(new_password)
        db.commit()
        
        print(f"✅ Password reset successfully for user: {username}")
        return True
        
    finally:
        db.close()


def list_users():
    """List all users in database"""
    db = SessionLocal()
    try:
        users = db.query(User).all()
        print("\n📋 All users in database:")
        print("-" * 60)
        for u in users:
            status = "🟢 Active" if u.is_active else "🔴 Inactive"
            owner = "👑" if u.is_system_owner else "  "
            print(f"{owner} {u.username:20} | {u.email:30} | {u.role:15} | {status}")
        print("-" * 60)
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) == 1:
        # No args - just list users
        list_users()
        print("\n💡 To reset a password, run:")
        print("   python reset_password.py <username> <new_password>")
        
    elif len(sys.argv) == 3:
        username = sys.argv[1]
        new_password = sys.argv[2]
        reset_password(username, new_password)
        
    else:
        print("Usage: python reset_password.py <username> <new_password>")
        print("   or: python reset_password.py  (to list users)")

from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
import bcrypt
import hashlib
import secrets
import re
from ..config import settings


def hash_password(password: str) -> str:
    """Hash a password using bcrypt"""
    password_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash"""
    password_bytes = plain_password.encode('utf-8')
    hashed_bytes = hashed_password.encode('utf-8')
    return bcrypt.checkpw(password_bytes, hashed_bytes)


def validate_password_strength(password: str) -> tuple[bool, str]:
    """
    Validate password meets security requirements.
    Returns (is_valid, error_message)
    """
    if len(password) < settings.min_password_length:
        return False, f"كلمة المرور يجب أن تكون {settings.min_password_length} أحرف على الأقل"
    
    if settings.require_password_uppercase and not re.search(r'[A-Z]', password):
        return False, "كلمة المرور يجب أن تحتوي على حرف كبير واحد على الأقل"
    
    if settings.require_password_digit and not re.search(r'\d', password):
        return False, "كلمة المرور يجب أن تحتوي على رقم واحد على الأقل"
    
    return True, ""


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.access_token_expire_minutes)
    to_encode.update({"exp": expire, "type": "access"})
    encoded_jwt = jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)
    return encoded_jwt


def create_refresh_token(data: dict) -> str:
    """Create a JWT refresh token"""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=settings.refresh_token_expire_days)
    # Add unique jti (JWT ID) for token identification
    to_encode.update({
        "exp": expire,
        "type": "refresh",
        "jti": secrets.token_urlsafe(16)
    })
    encoded_jwt = jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)
    return encoded_jwt


def decode_token(token: str) -> Optional[dict]:
    """Decode and verify a JWT token"""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        return payload
    except JWTError:
        return None


def verify_access_token(token: str) -> Optional[dict]:
    """Verify an access token and return payload"""
    payload = decode_token(token)
    if payload and payload.get("type") == "access":
        return payload
    return None


def verify_refresh_token(token: str) -> Optional[dict]:
    """Verify a refresh token and return payload"""
    payload = decode_token(token)
    if payload and payload.get("type") == "refresh":
        return payload
    return None


def hash_token(token: str) -> str:
    """
    Create SHA-256 hash of a token for secure DB storage.
    Never store raw tokens in database.
    """
    return hashlib.sha256(token.encode()).hexdigest()


def generate_csrf_token() -> str:
    """Generate a cryptographically secure CSRF token"""
    return secrets.token_urlsafe(32)


def get_token_expiry(days: int = None, minutes: int = None) -> datetime:
    """Calculate token expiry datetime"""
    if days:
        return datetime.utcnow() + timedelta(days=days)
    if minutes:
        return datetime.utcnow() + timedelta(minutes=minutes)
    return datetime.utcnow() + timedelta(days=settings.refresh_token_expire_days)

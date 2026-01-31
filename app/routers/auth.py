from fastapi import APIRouter, Depends, HTTPException, status, Response, Request, Cookie
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from datetime import datetime
from typing import Optional

from ..database import get_db
from ..config import settings
from ..models.user import User, UserRole
from ..models.refresh_token import RefreshToken
from ..schemas.auth import Token, RegisterRequest, RefreshTokenRequest, MessageResponse
from ..schemas.user import UserResponse
from ..utils.security import (
    hash_password, verify_password, validate_password_strength,
    create_access_token, create_refresh_token, 
    verify_refresh_token, hash_token, generate_csrf_token,
    get_token_expiry
)
from ..utils.rate_limiter import limiter
from ..utils.audit_logger import log_auth_event, get_request_id
from ..utils.dependencies import get_current_user
from ..services.session_tracking_service import SessionTrackingService
from ..models.audit_log import AuditLog, ActivityType as AuditActivityType, EntityType as AuditEntityType

router = APIRouter(prefix="/api/auth", tags=["المصادقة"])


def set_auth_cookies(response: Response, access_token: str, refresh_token: str):
    """Set HttpOnly cookies for cross-domain authentication"""
    # Access token cookie
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=True,  # Always true for cross-domain
        samesite="none",  # Required for cross-domain
        max_age=settings.access_token_expire_minutes * 60,
        path="/"
    )
    
    # Refresh token cookie - restricted path
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=True,
        samesite="none",
        max_age=settings.refresh_token_expire_days * 86400,
        path="/api/auth"  # Only sent to auth endpoints
    )
    
    # CSRF token cookie - NOT HttpOnly so JS can read it
    csrf_token = generate_csrf_token()
    response.set_cookie(
        key="csrf_token",
        value=csrf_token,
        httponly=False,  # JS must read this
        secure=True,
        samesite="none",
        max_age=settings.access_token_expire_minutes * 60,
        path="/"
    )


def clear_auth_cookies(response: Response):
    """Clear all auth cookies on logout"""
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/api/auth")
    response.delete_cookie("csrf_token", path="/")


def get_client_ip(request: Request) -> str:
    """Get real client IP from request"""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@router.post("/login")
@router.post("/login/")
@limiter.limit("5/minute")
async def login(
    request: Request,
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    """تسجيل الدخول والحصول على cookies للمصادقة"""
    request_id = get_request_id(request)
    client_ip = get_client_ip(request)
    
    # Trim whitespace that mobile keyboards may add
    username = form_data.username.strip()
    password = form_data.password.strip() if form_data.password else ""
    
    # Find user by username
    user = db.query(User).filter(User.username == username).first()
    
    if not user or not verify_password(password, user.hashed_password):
        log_auth_event(
            "LOGIN",
            username=username,
            success=False,
            details="Invalid credentials",
            ip_address=client_ip,
            request_id=request_id
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="اسم المستخدم أو كلمة المرور غير صحيحة",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not user.is_active:
        log_auth_event(
            "LOGIN",
            username=username,
            user_id=user.id,
            success=False,
            details="Account disabled",
            ip_address=client_ip,
            request_id=request_id
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="الحساب معطل"
        )
    
    # Create tokens
    access_token = create_access_token(data={"sub": user.id})
    refresh_token = create_refresh_token(data={"sub": user.id})
    
    # Store refresh token hash in DB (for revocation)
    refresh_token_record = RefreshToken(
        user_id=user.id,
        token_hash=hash_token(refresh_token),
        device_info=request.headers.get("User-Agent", "")[:255],
        ip_address=client_ip,
        expires_at=get_token_expiry(days=settings.refresh_token_expire_days)
    )
    db.add(refresh_token_record)
    
    # Update last login
    user.last_login = datetime.utcnow()
    db.commit()
    
    # Start session tracking
    session_service = SessionTrackingService(db)
    session_service.start_session(
        employee_id=user.id,
        ip_address=client_ip,
        user_agent=request.headers.get("User-Agent", "")[:500]
    )
    
    # Set cookies
    set_auth_cookies(response, access_token, refresh_token)
    
    log_auth_event(
        "LOGIN",
        username=user.username,
        user_id=user.id,
        success=True,
        ip_address=client_ip,
        request_id=request_id
    )
    
    # تسجيل في سجل الأنشطة (AuditLog)
    AuditLog.log(
        db=db,
        user=user,
        activity_type=AuditActivityType.LOGIN,
        entity_type=AuditEntityType.USER,
        entity_id=user.id,
        entity_name=f"{user.first_name} {user.last_name}",
        description=f"تسجيل دخول: {user.username}",
        ip_address=client_ip,
        user_agent=request.headers.get("User-Agent", "")[:500]
    )
    
    # Return user info (tokens are in cookies)
    return {
        "message": "تم تسجيل الدخول بنجاح",
        "user": {
            "id": user.id,
            "username": user.username,
            "name": f"{user.first_name} {user.last_name}",
            "role": user.role,
            "email": user.email
        }
    }


@router.post("/register")
@router.post("/register/")
@limiter.limit("3/hour")
async def register(
    request: Request,
    user_data: RegisterRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)  # Require admin to register
):
    """
    تسجيل مستخدم جديد (للمدير فقط).
    Public registration is disabled for security.
    """
    request_id = get_request_id(request)
    
    # Only admins can create users
    if current_user.role not in [UserRole.ADMIN.value, UserRole.SYSTEM_OWNER.value]:
        log_auth_event(
            "REGISTER",
            user_id=current_user.id,
            success=False,
            details="Unauthorized registration attempt",
            request_id=request_id
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="صلاحيات المدير مطلوبة لإنشاء مستخدمين"
        )
    
    # Validate password strength
    is_valid, error_msg = validate_password_strength(user_data.password)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_msg
        )
    
    # Check if username exists
    if db.query(User).filter(User.username == user_data.username).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="اسم المستخدم مستخدم بالفعل"
        )
    
    # Check if email exists
    if db.query(User).filter(User.email == user_data.email).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="البريد الإلكتروني مستخدم بالفعل"
        )
    
    # Create new user
    new_user = User(
        username=user_data.username,
        email=user_data.email,
        hashed_password=hash_password(user_data.password),
        first_name=user_data.first_name,
        last_name=user_data.last_name,
        phone=user_data.phone,
        role=UserRole.CUSTOMERS_AGENT.value,  # Default to lowest role
        is_active=True
    )
    
    db.add(new_user)
    db.commit()
    
    log_auth_event(
        "REGISTER",
        username=user_data.username,
        user_id=new_user.id,
        success=True,
        details=f"Created by {current_user.username}",
        request_id=request_id
    )
    
    return MessageResponse(
        message=f"تم إنشاء المستخدم {user_data.username} بنجاح!",
        success=True
    )


@router.post("/refresh")
@router.post("/refresh/")
@limiter.limit("10/minute")
async def refresh_tokens(
    request: Request,
    response: Response,
    refresh_token: Optional[str] = Cookie(None, alias="refresh_token"),
    db: Session = Depends(get_db)
):
    """تجديد access token باستخدام refresh token مع rotation"""
    request_id = get_request_id(request)
    client_ip = get_client_ip(request)
    
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token مطلوب"
        )
    
    # Verify refresh token JWT
    payload = verify_refresh_token(refresh_token)
    if not payload:
        log_auth_event(
            "REFRESH",
            success=False,
            details="Invalid refresh token",
            ip_address=client_ip,
            request_id=request_id
        )
        clear_auth_cookies(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token غير صالح أو منتهي الصلاحية"
        )
    
    user_id = payload.get("sub")
    token_hash = hash_token(refresh_token)
    
    # ====== Race Condition Prevention ======
    # Use with_for_update to lock the token row during rotation
    # This prevents the same token from being used twice in parallel requests
    from ..utils.db_helpers import is_postgres
    
    query = db.query(RefreshToken).filter(
        RefreshToken.token_hash == token_hash,
        RefreshToken.user_id == user_id,
        RefreshToken.is_revoked == False
    )
    
    # Apply row-level locking on PostgreSQL
    if is_postgres(db):
        query = query.with_for_update(nowait=True)
    
    try:
        stored_token = query.first()
    except Exception as e:
        # Token is locked by another request - this means concurrent refresh attempt
        log_auth_event(
            "REFRESH",
            user_id=user_id,
            success=False,
            details=f"Token locked by concurrent request: {e}",
            ip_address=client_ip,
            request_id=request_id
        )
        clear_auth_cookies(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="يتم تجديد الجلسة من جهاز آخر، يرجى المحاولة لاحقاً"
        )
    
    if not stored_token or not stored_token.is_valid:
        log_auth_event(
            "REFRESH",
            user_id=user_id,
            success=False,
            details="Refresh token not found or revoked",
            ip_address=client_ip,
            request_id=request_id
        )
        clear_auth_cookies(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token غير صالح"
        )
    
    # Get user
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active:
        clear_auth_cookies(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="المستخدم غير موجود أو معطل"
        )
    
    # Rotate refresh token: revoke old, create new
    stored_token.is_revoked = True
    stored_token.revoked_at = datetime.utcnow()
    
    # Create new tokens
    new_access_token = create_access_token(data={"sub": user.id})
    new_refresh_token = create_refresh_token(data={"sub": user.id})
    
    # Store new refresh token
    new_token_record = RefreshToken(
        user_id=user.id,
        token_hash=hash_token(new_refresh_token),
        device_info=stored_token.device_info,  # Keep device info
        ip_address=client_ip,
        expires_at=get_token_expiry(days=settings.refresh_token_expire_days)
    )
    db.add(new_token_record)
    db.commit()
    
    # Set new cookies
    set_auth_cookies(response, new_access_token, new_refresh_token)
    
    log_auth_event(
        "REFRESH",
        user_id=user.id,
        success=True,
        ip_address=client_ip,
        request_id=request_id
    )
    
    return {"message": "تم تجديد الجلسة بنجاح"}


@router.post("/logout")
@router.post("/logout/")
async def logout(
    request: Request,
    response: Response,
    refresh_token: Optional[str] = Cookie(None, alias="refresh_token"),
    access_token: Optional[str] = Cookie(None, alias="access_token"),
    db: Session = Depends(get_db)
):
    """تسجيل الخروج وإلغاء صلاحية الجلسة"""
    request_id = get_request_id(request)
    user_id = None
    
    # Try to get user from access token for logging
    if access_token:
        from ..utils.security import verify_access_token
        payload = verify_access_token(access_token)
        if payload:
            user_id = payload.get("sub")
    
    # Revoke refresh token if exists
    if refresh_token:
        token_hash = hash_token(refresh_token)
        stored_token = db.query(RefreshToken).filter(
            RefreshToken.token_hash == token_hash
        ).first()
        
        if stored_token:
            stored_token.is_revoked = True
            stored_token.revoked_at = datetime.utcnow()
            db.commit()
    
    # End session tracking
    if user_id:
        session_service = SessionTrackingService(db)
        session_service.end_session(user_id)
    
    # Clear all auth cookies
    clear_auth_cookies(response)
    
    log_auth_event(
        "LOGOUT",
        user_id=user_id,
        success=True,
        request_id=request_id
    )
    
    # تسجيل في سجل الأنشطة (AuditLog) - إذا كان المستخدم معروف
    if user_id:
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            AuditLog.log(
                db=db,
                user=user,
                activity_type=AuditActivityType.LOGOUT,
                entity_type=AuditEntityType.USER,
                entity_id=user.id,
                entity_name=f"{user.first_name} {user.last_name}",
                description=f"تسجيل خروج: {user.username}",
                ip_address=get_client_ip(request),
                user_agent=request.headers.get("User-Agent", "")[:500]
            )
    
    return MessageResponse(
        message="تم تسجيل الخروج بنجاح",
        success=True
    )


@router.get("/me")
@router.get("/me/")
async def get_current_user_info(
    current_user: User = Depends(get_current_user)
):
    """الحصول على بيانات المستخدم الحالي"""
    return {
        "id": current_user.id,
        "username": current_user.username,
        "email": current_user.email,
        "first_name": current_user.first_name,
        "last_name": current_user.last_name,
        "name": f"{current_user.first_name} {current_user.last_name}",
        "role": current_user.role,
        "is_active": current_user.is_active,
        "is_system_owner": current_user.is_system_owner
    }


@router.post("/logout-all")
@router.post("/logout-all/")
async def logout_all_sessions(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """تسجيل الخروج من جميع الجلسات"""
    request_id = get_request_id(request)
    
    # Revoke all refresh tokens for this user
    db.query(RefreshToken).filter(
        RefreshToken.user_id == current_user.id,
        RefreshToken.is_revoked == False
    ).update({
        "is_revoked": True,
        "revoked_at": datetime.utcnow()
    })
    db.commit()
    
    # Clear current session cookies
    clear_auth_cookies(response)
    
    log_auth_event(
        "LOGOUT_ALL",
        user_id=current_user.id,
        success=True,
        request_id=request_id
    )
    
    return MessageResponse(
        message="تم تسجيل الخروج من جميع الأجهزة",
        success=True
    )

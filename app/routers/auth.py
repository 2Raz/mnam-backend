from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from datetime import datetime

from ..database import get_db
from ..models.user import User, UserRole
from ..schemas.auth import (
    Token, LoginRequest, RegisterRequest, 
    RefreshTokenRequest, MessageResponse
)
from ..schemas.user import UserResponse, UserCreate
from ..utils.security import (
    hash_password, verify_password, 
    create_access_token, create_refresh_token,
    verify_refresh_token
)

router = APIRouter(prefix="/api/auth", tags=["المصادقة"])


@router.post("/login")
@router.post("/login/", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    """تسجيل الدخول والحصول على JWT tokens"""
    # Find user by username
    user = db.query(User).filter(User.username == form_data.username).first()
    
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="اسم المستخدم أو كلمة المرور غير صحيحة",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="الحساب معطل"
        )
    
    # Update last login
    user.last_login = datetime.utcnow()
    db.commit()
    
    # Create tokens
    access_token = create_access_token(data={"sub": user.id, "username": user.username})
    refresh_token = create_refresh_token(data={"sub": user.id})
    
    return Token(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer"
    )


@router.post("/register")
@router.post("/register/", response_model=MessageResponse)
async def register(
    user_data: RegisterRequest,
    db: Session = Depends(get_db)
):
    """تسجيل مستخدم جديد (Agent)"""
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
        role=UserRole.AGENT.value,
        is_active=True
    )
    
    db.add(new_user)
    db.commit()
    
    return MessageResponse(
        message=f"تم تسجيل المستخدم {user_data.username} بنجاح!",
        success=True
    )


@router.post("/refresh")
@router.post("/refresh/", response_model=Token)
async def refresh_token(
    request: RefreshTokenRequest,
    db: Session = Depends(get_db)
):
    """تجديد access token باستخدام refresh token"""
    payload = verify_refresh_token(request.refresh_token)
    
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token غير صالح أو منتهي الصلاحية"
        )
    
    user_id = payload.get("sub")
    user = db.query(User).filter(User.id == user_id).first()
    
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="المستخدم غير موجود أو معطل"
        )
    
    # Create new tokens
    access_token = create_access_token(data={"sub": user.id, "username": user.username})
    new_refresh_token = create_refresh_token(data={"sub": user.id})
    
    return Token(
        access_token=access_token,
        refresh_token=new_refresh_token,
        token_type="bearer"
    )


@router.post("/logout")
@router.post("/logout/", response_model=MessageResponse)
async def logout():
    """تسجيل الخروج"""
    # In a stateless JWT setup, logout is handled client-side
    # For added security, you could implement token blacklisting here
    return MessageResponse(
        message="تم تسجيل الخروج بنجاح",
        success=True
    )

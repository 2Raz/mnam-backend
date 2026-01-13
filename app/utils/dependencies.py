from fastapi import Depends, HTTPException, status, Request, Cookie
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from typing import Optional
from ..database import get_db
from ..models.user import User, UserRole, ROLE_HIERARCHY
from ..utils.security import verify_access_token

# OAuth2 scheme for documentation (not used for actual auth with cookies)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


async def get_current_user(
    request: Request,
    access_token: Optional[str] = Cookie(None, alias="access_token"),
    db: Session = Depends(get_db)
) -> User:
    """
    Get the current authenticated user from HttpOnly cookie.
    This is the primary authentication method for cross-domain setup.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="لم يتم التحقق من الهوية",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    if not access_token:
        raise credentials_exception
    
    payload = verify_access_token(access_token)
    if payload is None:
        raise credentials_exception
    
    user_id: str = payload.get("sub")
    if user_id is None:
        raise credentials_exception
    
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise credentials_exception
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="الحساب معطل"
        )
    
    # Store user in request state for audit logging
    request.state.current_user = user
    
    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """Ensure the user is active"""
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="الحساب معطل"
        )
    return current_user


async def require_system_owner(
    current_user: User = Depends(get_current_user)
) -> User:
    """Require System Owner role - highest privilege (Head_Admin)"""
    if not current_user.is_system_owner or current_user.role != UserRole.SYSTEM_OWNER.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="صلاحيات مالك النظام مطلوبة"
        )
    return current_user


async def require_admin(
    current_user: User = Depends(get_current_user)
) -> User:
    """Require Admin or System Owner role"""
    allowed_roles = [UserRole.ADMIN.value, UserRole.SYSTEM_OWNER.value]
    if current_user.role not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="صلاحيات المدير مطلوبة"
        )
    return current_user


async def require_owners_agent(
    current_user: User = Depends(get_current_user)
) -> User:
    """Require Owners Agent, Admin or System Owner role"""
    allowed_roles = [UserRole.OWNERS_AGENT.value, UserRole.ADMIN.value, UserRole.SYSTEM_OWNER.value]
    if current_user.role not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="صلاحيات وكيل الملاك أو أعلى مطلوبة"
        )
    return current_user


async def require_customers_agent(
    current_user: User = Depends(get_current_user)
) -> User:
    """Require any authenticated user (Customers Agent or higher)"""
    return current_user


def get_optional_user(
    access_token: Optional[str] = Cookie(None, alias="access_token"),
    db: Session = Depends(get_db)
) -> Optional[User]:
    """Get user if authenticated, None otherwise"""
    if not access_token:
        return None
    
    payload = verify_access_token(access_token)
    if payload is None:
        return None
    
    user_id: str = payload.get("sub")
    if user_id is None:
        return None
    
    return db.query(User).filter(User.id == user_id).first()


def is_admin_or_owner(user: User, resource_created_by_id: str) -> bool:
    """
    Check if user is admin/system_owner OR the creator of the resource.
    Used for ownership checks to prevent IDOR.
    """
    admin_roles = [UserRole.ADMIN.value, UserRole.SYSTEM_OWNER.value]
    if user.role in admin_roles:
        return True
    return user.id == resource_created_by_id


def can_access_page(user: User, page: str) -> bool:
    """التحقق من صلاحية الوصول لصفحة معينة"""
    page_permissions = {
        UserRole.SYSTEM_OWNER.value: ["all"],
        UserRole.ADMIN.value: ["all"],
        UserRole.OWNERS_AGENT.value: ["home", "owners", "units", "projects"],
        UserRole.CUSTOMERS_AGENT.value: ["units", "bookings"],
    }
    
    user_pages = page_permissions.get(user.role, [])
    return "all" in user_pages or page in user_pages


def can_edit_on_page(user: User, page: str) -> bool:
    """التحقق من صلاحية التعديل في صفحة معينة"""
    edit_permissions = {
        UserRole.SYSTEM_OWNER.value: ["all"],
        UserRole.ADMIN.value: ["all"],
        UserRole.OWNERS_AGENT.value: ["owners", "units", "projects"],
        UserRole.CUSTOMERS_AGENT.value: ["bookings"],
    }
    
    user_edit_pages = edit_permissions.get(user.role, [])
    return "all" in user_edit_pages or page in user_edit_pages

"""
Router للإشعارات - Notifications Router
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc, or_
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel

from ..database import get_db
from ..utils.dependencies import get_current_user
from ..models import User, Notification, NotificationType


router = APIRouter(prefix="/api/notifications", tags=["Notifications"])


# ============ Schemas ============

class NotificationResponse(BaseModel):
    id: str
    type: str
    title: str
    message: Optional[str]
    entity_type: Optional[str]
    entity_id: Optional[str]
    is_read: bool
    created_at: datetime
    read_at: Optional[datetime]
    icon: str
    type_label: str

    class Config:
        from_attributes = True


class NotificationListResponse(BaseModel):
    notifications: List[NotificationResponse]
    total: int
    unread_count: int


class UnreadCountResponse(BaseModel):
    count: int


class CreateNotificationRequest(BaseModel):
    user_id: Optional[str] = None  # Null = broadcast
    type: str
    title: str
    message: Optional[str] = None
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None


# ============ Helper Functions ============

def create_notification(
    db: Session,
    notification_type: NotificationType,
    title: str,
    message: str = None,
    entity_type: str = None,
    entity_id: str = None,
    user_id: str = None  # Null = broadcast to all
) -> Notification:
    """إنشاء إشعار جديد"""
    notification = Notification(
        user_id=user_id,
        type=notification_type.value,
        title=title,
        message=message,
        entity_type=entity_type,
        entity_id=entity_id,
        is_read=False
    )
    db.add(notification)
    db.commit()
    db.refresh(notification)
    return notification


def broadcast_notification(
    db: Session,
    notification_type: NotificationType,
    title: str,
    message: str = None,
    entity_type: str = None,
    entity_id: str = None,
    exclude_user_id: str = None  # استبعاد مستخدم معين
) -> List[Notification]:
    """إرسال إشعار لجميع المستخدمين النشطين"""
    users = db.query(User).filter(
        User.is_active == True,
        User.is_deleted == False
    )
    if exclude_user_id:
        users = users.filter(User.id != exclude_user_id)
    
    notifications = []
    for user in users.all():
        notification = Notification(
            user_id=user.id,
            type=notification_type.value,
            title=title,
            message=message,
            entity_type=entity_type,
            entity_id=entity_id,
            is_read=False
        )
        db.add(notification)
        notifications.append(notification)
    
    db.commit()
    return notifications


# ============ Endpoints ============

@router.get("", response_model=NotificationListResponse)
@router.get("/", response_model=NotificationListResponse)
async def get_notifications(
    limit: int = Query(50, le=100, ge=1),
    offset: int = Query(0, ge=0),
    unread_only: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """الحصول على قائمة الإشعارات للمستخدم الحالي"""
    
    # الإشعارات الخاصة بالمستخدم + الإشعارات العامة (broadcast)
    query = db.query(Notification).filter(
        or_(
            Notification.user_id == current_user.id,
            Notification.user_id == None  # Broadcast
        )
    )
    
    if unread_only:
        query = query.filter(Notification.is_read == False)
    
    total = query.count()
    unread_count = query.filter(Notification.is_read == False).count() if not unread_only else total
    
    notifications = query.order_by(desc(Notification.created_at)).offset(offset).limit(limit).all()
    
    return {
        "notifications": [
            {
                "id": n.id,
                "type": n.type,
                "title": n.title,
                "message": n.message,
                "entity_type": n.entity_type,
                "entity_id": n.entity_id,
                "is_read": n.is_read,
                "created_at": n.created_at,
                "read_at": n.read_at,
                "icon": n.icon,
                "type_label": n.type_label
            }
            for n in notifications
        ],
        "total": total,
        "unread_count": unread_count
    }


@router.get("/unread-count", response_model=UnreadCountResponse)
@router.get("/unread-count/", response_model=UnreadCountResponse)
async def get_unread_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """الحصول على عدد الإشعارات غير المقروءة"""
    count = db.query(Notification).filter(
        or_(
            Notification.user_id == current_user.id,
            Notification.user_id == None
        ),
        Notification.is_read == False
    ).count()
    
    return {"count": count}


@router.put("/{notification_id}/read")
@router.put("/{notification_id}/read/")
async def mark_as_read(
    notification_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """تحديد إشعار كمقروء"""
    notification = db.query(Notification).filter(
        Notification.id == notification_id,
        or_(
            Notification.user_id == current_user.id,
            Notification.user_id == None
        )
    ).first()
    
    if not notification:
        raise HTTPException(status_code=404, detail="الإشعار غير موجود")
    
    notification.is_read = True
    notification.read_at = datetime.utcnow()
    db.commit()
    
    return {"message": "تم تحديد الإشعار كمقروء"}


@router.put("/read-all")
@router.put("/read-all/")
async def mark_all_as_read(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """تحديد جميع الإشعارات كمقروءة"""
    db.query(Notification).filter(
        or_(
            Notification.user_id == current_user.id,
            Notification.user_id == None
        ),
        Notification.is_read == False
    ).update({
        "is_read": True,
        "read_at": datetime.utcnow()
    }, synchronize_session=False)
    
    db.commit()
    
    return {"message": "تم تحديد جميع الإشعارات كمقروءة"}


@router.delete("/{notification_id}")
@router.delete("/{notification_id}/")
async def delete_notification(
    notification_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """حذف إشعار"""
    notification = db.query(Notification).filter(
        Notification.id == notification_id,
        or_(
            Notification.user_id == current_user.id,
            Notification.user_id == None
        )
    ).first()
    
    if not notification:
        raise HTTPException(status_code=404, detail="الإشعار غير موجود")
    
    db.delete(notification)
    db.commit()
    
    return {"message": "تم حذف الإشعار"}


@router.delete("/clear-all")
@router.delete("/clear-all/")
async def clear_all_notifications(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """حذف جميع الإشعارات المقروءة"""
    db.query(Notification).filter(
        or_(
            Notification.user_id == current_user.id,
            Notification.user_id == None
        ),
        Notification.is_read == True
    ).delete(synchronize_session=False)
    
    db.commit()
    
    return {"message": "تم حذف جميع الإشعارات المقروءة"}

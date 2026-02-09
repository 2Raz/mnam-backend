"""
Pagination Schemas - NFR Implementation

Provides reusable pagination models for all list endpoints.
"""

from typing import TypeVar, Generic, List, Optional
from pydantic import BaseModel, Field
from math import ceil

T = TypeVar('T')


class PaginationParams(BaseModel):
    """Query parameters for pagination"""
    page: int = Field(default=1, ge=1, description="رقم الصفحة")
    page_size: int = Field(default=20, ge=1, le=100, description="عدد العناصر في الصفحة")
    
    @property
    def offset(self) -> int:
        """Calculate offset for database query"""
        return (self.page - 1) * self.page_size


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated response wrapper"""
    items: List[T]
    total: int = Field(description="إجمالي العناصر")
    page: int = Field(description="الصفحة الحالية")
    page_size: int = Field(description="حجم الصفحة")
    total_pages: int = Field(description="إجمالي الصفحات")
    has_next: bool = Field(description="هل يوجد صفحة تالية")
    has_previous: bool = Field(description="هل يوجد صفحة سابقة")
    
    @classmethod
    def create(
        cls,
        items: List[T],
        total: int,
        page: int,
        page_size: int
    ) -> "PaginatedResponse[T]":
        """Factory method to create paginated response"""
        total_pages = ceil(total / page_size) if page_size > 0 else 0
        return cls(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
            has_next=page < total_pages,
            has_previous=page > 1
        )


def paginate_query(query, page: int, page_size: int):
    """
    Helper function to apply pagination to SQLAlchemy query.
    
    Returns:
        Tuple of (paginated_items, total_count)
    """
    total = query.count()
    offset = (page - 1) * page_size
    items = query.offset(offset).limit(page_size).all()
    return items, total

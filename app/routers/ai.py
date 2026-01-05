from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Optional

# Try to import google generativeai, handle if not installed
try:
    import google.generativeai as genai
    GENAI_AVAILABLE = True
except ImportError:
    genai = None
    GENAI_AVAILABLE = False

from ..config import settings
from ..utils.dependencies import get_current_user
from ..models.user import User

router = APIRouter(prefix="/api/ai", tags=["الذكاء الاصطناعي"])


class GenerateDescriptionRequest(BaseModel):
    unit_type: str
    amenities: List[str]
    project_name: str
    rooms: Optional[int] = None
    area: Optional[float] = None


class GenerateDescriptionResponse(BaseModel):
    description: str


class ChatRequest(BaseModel):
    message: str
    context: Optional[str] = None


class ChatResponse(BaseModel):
    response: str


def get_gemini_model():
    """Get configured Gemini model"""
    if not GENAI_AVAILABLE or genai is None:
        return None
    if not settings.gemini_api_key:
        return None
    
    genai.configure(api_key=settings.gemini_api_key)
    return genai.GenerativeModel('gemini-1.5-flash')


@router.post("/generate-description")
@router.post("/generate-description/", response_model=GenerateDescriptionResponse)
async def generate_unit_description(
    request: GenerateDescriptionRequest,
    current_user: User = Depends(get_current_user)
):
    """توليد وصف تسويقي للوحدة باستخدام AI"""
    model = get_gemini_model()
    
    if not model:
        raise HTTPException(
            status_code=503,
            detail="خدمة الذكاء الاصطناعي غير متوفرة. يرجى إضافة GEMINI_API_KEY."
        )
    
    amenities_text = "، ".join(request.amenities) if request.amenities else "لا توجد مرافق محددة"
    
    prompt = f"""
أنت كاتب محتوى عقاري محترف. اكتب وصفاً تسويقياً جذاباً وموجزاً (3-4 جمل) لوحدة سكنية بالمواصفات التالية:

- نوع الوحدة: {request.unit_type}
- اسم المشروع: {request.project_name}
- عدد الغرف: {request.rooms or "غير محدد"}
- المساحة: {f"{request.area} متر مربع" if request.area else "غير محددة"}
- المرافق: {amenities_text}

اكتب الوصف باللغة العربية الفصحى بأسلوب تسويقي جذاب يبرز مميزات الوحدة.
"""
    
    try:
        response = model.generate_content(prompt)
        return GenerateDescriptionResponse(description=response.text)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"خطأ في توليد الوصف: {str(e)}"
        )


@router.post("/chat")
@router.post("/chat/", response_model=ChatResponse)
async def ai_chat(
    request: ChatRequest,
    current_user: User = Depends(get_current_user)
):
    """مساعد الذكاء الاصطناعي"""
    model = get_gemini_model()
    
    if not model:
        raise HTTPException(
            status_code=503,
            detail="خدمة الذكاء الاصطناعي غير متوفرة. يرجى إضافة GEMINI_API_KEY."
        )
    
    system_prompt = """
أنت مساعد ذكي لنظام إدارة العقارات "منام". مهمتك مساعدة المستخدمين في:
- إدارة الحجوزات والوحدات
- فهم التقارير المالية
- تقديم نصائح لتحسين الإشغال
- الإجابة على الأسئلة العامة حول إدارة العقارات

أجب بأسلوب مهني وودود باللغة العربية.
"""
    
    full_prompt = f"{system_prompt}\n\nسؤال المستخدم: {request.message}"
    
    if request.context:
        full_prompt += f"\n\nسياق إضافي: {request.context}"
    
    try:
        response = model.generate_content(full_prompt)
        return ChatResponse(response=response.text)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"خطأ في الدردشة: {str(e)}"
        )

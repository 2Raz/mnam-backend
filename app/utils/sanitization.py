"""
وظائف الأمان والتعقيم
Security & Sanitization Utilities

هذا الملف يحتوي على وظائف مساعدة للأمان:
1. تعقيم المدخلات من XSS
2. التحقق من الصيغ الخطيرة
3. تنظيف البيانات قبل العرض

Author: MNAM Security Team
Date: 2026-01-28
"""

import re
import html
from typing import Optional, Any
import unicodedata


# ============================================================================
# XSS SANITIZATION
# ============================================================================

def sanitize_html(content: Optional[str]) -> Optional[str]:
    """
    تعقيم محتوى HTML لمنع XSS
    
    يستبدل الأحرف الخاصة بـ HTML entities:
    - < → &lt;
    - > → &gt;
    - & → &amp;
    - " → &quot;
    - ' → &#x27;
    
    Args:
        content: النص الذي يحتاج لتعقيم
        
    Returns:
        النص المعقم أو None إذا كان الإدخال فارغًا
    """
    if content is None:
        return None
    
    if not isinstance(content, str):
        content = str(content)
    
    return html.escape(content, quote=True)


def sanitize_for_json(data: Any) -> Any:
    """
    تعقيم البيانات قبل إرجاعها كـ JSON
    
    يعالج القيم النصية بشكل متكرر في القواميس والقوائم
    
    Args:
        data: البيانات للتعقيم (dict, list, str, etc.)
        
    Returns:
        البيانات المعقمة
    """
    if isinstance(data, dict):
        return {k: sanitize_for_json(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [sanitize_for_json(item) for item in data]
    elif isinstance(data, str):
        return sanitize_html(data)
    else:
        return data


def strip_dangerous_tags(content: str) -> str:
    """
    إزالة العلامات الخطيرة من HTML
    
    يزيل:
    - <script> tags
    - Event handlers (onclick, onerror, etc.)
    - javascript: URLs
    - data: URLs
    
    Args:
        content: محتوى HTML
        
    Returns:
        المحتوى المنظف
    """
    if not content:
        return content
    
    # إزالة script tags
    content = re.sub(r'<script[^>]*>.*?</script>', '', content, flags=re.IGNORECASE | re.DOTALL)
    
    # إزالة style tags
    content = re.sub(r'<style[^>]*>.*?</style>', '', content, flags=re.IGNORECASE | re.DOTALL)
    
    # إزالة event handlers
    event_handlers = [
        'onclick', 'ondblclick', 'onmousedown', 'onmouseup', 'onmouseover',
        'onmousemove', 'onmouseout', 'onkeypress', 'onkeydown', 'onkeyup',
        'onload', 'onerror', 'onunload', 'onabort', 'onreset', 'onsubmit',
        'onblur', 'onchange', 'onfocus', 'onselect', 'onstart', 'onfinish',
        'onbeforeunload', 'onbeforeprint', 'onafterprint', 'onanimationstart',
        'onanimationend', 'onauxclick', 'onbeforeinput', 'oncanplay',
        'oncanplaythrough', 'oncopy', 'oncut', 'ondrag', 'ondragend',
        'ondragenter', 'ondragleave', 'ondragover', 'ondragstart', 'ondrop',
        'oninput', 'oninvalid', 'onpaste', 'onscroll', 'ontouchstart',
        'ontouchmove', 'ontouchend', 'ontouchcancel', 'onwheel',
    ]
    
    for handler in event_handlers:
        content = re.sub(
            rf'{handler}\s*=\s*["\'][^"\']*["\']',
            '',
            content,
            flags=re.IGNORECASE
        )
        content = re.sub(
            rf'{handler}\s*=\s*[^\s>]+',
            '',
            content,
            flags=re.IGNORECASE
        )
    
    # إزالة javascript: URLs
    content = re.sub(r'javascript\s*:', '', content, flags=re.IGNORECASE)
    
    # إزالة data: URLs (في بعض السياقات)
    content = re.sub(r'data\s*:\s*text/html', '', content, flags=re.IGNORECASE)
    
    # إزالة vbscript: URLs
    content = re.sub(r'vbscript\s*:', '', content, flags=re.IGNORECASE)
    
    return content


# ============================================================================
# INPUT VALIDATION
# ============================================================================

def is_valid_uuid(value: str) -> bool:
    """
    التحقق من صيغة UUID
    
    Args:
        value: القيمة للتحقق
        
    Returns:
        True إذا كانت UUID صالحة
    """
    if not value or not isinstance(value, str):
        return False
    
    uuid_pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
    return bool(re.match(uuid_pattern, value.lower()))


def is_valid_email(email: str) -> bool:
    """
    التحقق من صيغة البريد الإلكتروني
    
    Args:
        email: البريد للتحقق
        
    Returns:
        True إذا كان البريد صالحًا
    """
    if not email or not isinstance(email, str):
        return False
    
    # صيغة بريد إلكتروني بسيطة وآمنة
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(email_pattern, email))


def is_valid_phone_sa(phone: str) -> bool:
    """
    التحقق من صيغة رقم الهاتف السعودي
    
    يقبل:
    - +966XXXXXXXXX
    - 966XXXXXXXXX
    - 05XXXXXXXX
    
    Args:
        phone: رقم الهاتف
        
    Returns:
        True إذا كان الرقم صالحًا
    """
    if not phone or not isinstance(phone, str):
        return False
    
    # إزالة المسافات والشرطات
    clean_phone = re.sub(r'[\s\-\(\)]', '', phone)
    
    # صيغ الهاتف السعودي
    patterns = [
        r'^\+966[0-9]{9}$',  # +966 format
        r'^966[0-9]{9}$',    # 966 format
        r'^05[0-9]{8}$',     # 05 format
    ]
    
    return any(re.match(pattern, clean_phone) for pattern in patterns)


def validate_positive_decimal(value: Any) -> bool:
    """
    التحقق من أن القيمة عدد عشري موجب
    
    Args:
        value: القيمة للتحقق
        
    Returns:
        True إذا كانت القيمة عشرية موجبة
    """
    try:
        from decimal import Decimal
        decimal_value = Decimal(str(value))
        return decimal_value >= 0
    except:
        return False


# ============================================================================
# INJECTION DETECTION
# ============================================================================

def contains_sql_injection_patterns(value: str) -> bool:
    """
    الكشف عن أنماط SQL Injection
    
    تحذير: هذا للكشف فقط! الحماية الفعلية تكون عبر ORM/Prepared Statements
    
    Args:
        value: النص للفحص
        
    Returns:
        True إذا تم الكشف عن أنماط مشبوهة
    """
    if not value or not isinstance(value, str):
        return False
    
    lower_value = value.lower()
    
    # أنماط SQL الخطيرة
    sql_patterns = [
        r"'\s*or\s*'",
        r"'\s*and\s*'",
        r"--\s*$",
        r";\s*drop\s+",
        r";\s*delete\s+",
        r";\s*update\s+",
        r";\s*insert\s+",
        r"union\s+select",
        r"union\s+all\s+select",
        r"waitfor\s+delay",
        r"sleep\s*\(",
        r"benchmark\s*\(",
    ]
    
    return any(re.search(pattern, lower_value) for pattern in sql_patterns)


def contains_xss_patterns(value: str) -> bool:
    """
    الكشف عن أنماط XSS
    
    Args:
        value: النص للفحص
        
    Returns:
        True إذا تم الكشف عن أنماط XSS
    """
    if not value or not isinstance(value, str):
        return False
    
    lower_value = value.lower()
    
    # أنماط XSS
    xss_patterns = [
        r'<\s*script',
        r'javascript\s*:',
        r'on\w+\s*=',
        r'<\s*iframe',
        r'<\s*object',
        r'<\s*embed',
        r'<\s*svg.*onload',
        r'<\s*img.*onerror',
    ]
    
    return any(re.search(pattern, lower_value) for pattern in xss_patterns)


def contains_command_injection_patterns(value: str) -> bool:
    """
    الكشف عن أنماط Command Injection
    
    Args:
        value: النص للفحص
        
    Returns:
        True إذا تم الكشف عن أنماط Command Injection
    """
    if not value or not isinstance(value, str):
        return False
    
    # أنماط Command Injection
    cmd_patterns = [
        r';\s*\w+\s',  # ; command
        r'\|\s*\w+',   # | command
        r'&&\s*\w+',   # && command
        r'\|\|\s*\w+', # || command
        r'\$\([^)]+\)', # $(command)
        r'`[^`]+`',     # `command`
        r'>\s*/[a-z]',  # > /path
        r'<\s*/[a-z]',  # < /path
    ]
    
    return any(re.search(pattern, value) for pattern in cmd_patterns)


def contains_path_traversal(value: str) -> bool:
    """
    الكشف عن محاولات Path Traversal
    
    Args:
        value: النص للفحص
        
    Returns:
        True إذا تم الكشف عن Path Traversal
    """
    if not value or not isinstance(value, str):
        return False
    
    # أنماط Path Traversal
    traversal_patterns = [
        r'\.\.',           # ..
        r'%2e%2e',         # URL encoded ..
        r'%252e%252e',     # Double URL encoded
        r'\.\.[\\/]',      # ../  or ..\
        r'^[a-zA-Z]:[\\/]', # C:\  or D:/
        r'^[\\/]',          # /path (absolute)
    ]
    
    return any(re.search(pattern, value, re.IGNORECASE) for pattern in traversal_patterns)


# ============================================================================
# UNICODE NORMALIZATION
# ============================================================================

def normalize_unicode(value: str) -> str:
    """
    تطبيع Unicode لمنع هجمات التحايل
    
    يحول أحرف Unicode المتشابهة إلى شكل موحد:
    - Fullwidth ＡＢＣ → ABC
    - Unicode quotes → ASCII quotes
    
    Args:
        value: النص للتطبيع
        
    Returns:
        النص المطبع
    """
    if not value:
        return value
    
    # تطبيع NFKC
    normalized = unicodedata.normalize('NFKC', value)
    
    # إزالة الأحرف غير المرئية (Zero-width characters)
    invisible_chars = [
        '\u200b',  # Zero Width Space
        '\u200c',  # Zero Width Non-Joiner
        '\u200d',  # Zero Width Joiner
        '\u200e',  # Left-to-Right Mark
        '\u200f',  # Right-to-Left Mark
        '\u202a',  # Left-to-Right Embedding
        '\u202b',  # Right-to-Left Embedding
        '\u202c',  # Pop Directional Formatting
        '\u202d',  # Left-to-Right Override
        '\u202e',  # Right-to-Left Override (خطير!)
        '\ufeff',  # BOM
    ]
    
    for char in invisible_chars:
        normalized = normalized.replace(char, '')
    
    return normalized


# ============================================================================
# SAFE STRING TRUNCATION
# ============================================================================

def safe_truncate(value: str, max_length: int, suffix: str = "...") -> str:
    """
    اقتطاع نص بشكل آمن مع المحافظة على Unicode
    
    Args:
        value: النص للاقتطاع
        max_length: الحد الأقصى للطول
        suffix: النص المضاف في النهاية
        
    Returns:
        النص المقتطع
    """
    if not value or len(value) <= max_length:
        return value
    
    # اقتطاع مع مراعاة طول suffix
    truncate_at = max_length - len(suffix)
    if truncate_at <= 0:
        return suffix[:max_length]
    
    return value[:truncate_at] + suffix


# ============================================================================
# LOGGING SANITIZATION
# ============================================================================

def sanitize_for_log(value: Any, max_length: int = 200) -> str:
    """
    تعقيم القيمة للتسجيل في logs
    
    يزيل:
    - كلمات المرور
    - أرقام البطاقات
    - معلومات حساسة أخرى
    
    Args:
        value: القيمة للتعقيم
        max_length: الحد الأقصى للطول
        
    Returns:
        النص المعقم والآمن للتسجيل
    """
    if value is None:
        return "null"
    
    str_value = str(value)
    
    # إخفاء البيانات الحساسة
    # إخفاء كلمات المرور
    str_value = re.sub(
        r'(password|passwd|pwd|secret|token|api_key)[\"\']?\s*[:=]\s*[\"\']?[^\s\"\']+',
        r'\1: [REDACTED]',
        str_value,
        flags=re.IGNORECASE
    )
    
    # إخفاء أرقام البطاقات (16 رقم)
    str_value = re.sub(r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b', '[CARD_REDACTED]', str_value)
    
    # اقتطاع إذا كان طويلاً
    return safe_truncate(str_value, max_length)


# ============================================================================
# EXPORT ALL UTILITIES
# ============================================================================

__all__ = [
    # XSS Sanitization
    'sanitize_html',
    'sanitize_for_json',
    'strip_dangerous_tags',
    
    # Input Validation
    'is_valid_uuid',
    'is_valid_email',
    'is_valid_phone_sa',
    'validate_positive_decimal',
    
    # Injection Detection
    'contains_sql_injection_patterns',
    'contains_xss_patterns',
    'contains_command_injection_patterns',
    'contains_path_traversal',
    
    # Unicode
    'normalize_unicode',
    
    # Utilities
    'safe_truncate',
    'sanitize_for_log',
]

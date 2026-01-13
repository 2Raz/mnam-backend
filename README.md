<div align="center">

# 🔌 MNAM Backend API | خادم مِنَام

[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?style=flat-square&logo=fastapi)](https://fastapi.tiangolo.com/)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0+-red?style=flat-square)](https://www.sqlalchemy.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-13+-336791?style=flat-square&logo=postgresql)](https://www.postgresql.org/)

</div>

---

## 📖 نظرة عامة

خادم REST API لنظام إدارة العقارات والحجوزات، مبني بـ FastAPI مع PostgreSQL.

---

## 🏗️ هيكل المشروع

```
mnam-backend/
├── app/
│   ├── __init__.py
│   ├── main.py              # نقطة الدخول
│   ├── config.py            # إعدادات التطبيق
│   ├── database.py          # اتصال قاعدة البيانات
│   │
│   ├── models/              # نماذج SQLAlchemy
│   │   ├── user.py          # المستخدمين والصلاحيات
│   │   ├── owner.py         # الملاك
│   │   ├── project.py       # المشاريع
│   │   ├── unit.py          # الوحدات
│   │   ├── booking.py       # الحجوزات
│   │   ├── customer.py      # العملاء
│   │   ├── transaction.py   # المعاملات المالية
│   │   └── employee_performance.py  # أداء الموظفين
│   │
│   ├── routers/             # API Endpoints
│   │   ├── auth.py          # المصادقة
│   │   ├── users.py         # إدارة المستخدمين
│   │   ├── owners.py        # إدارة الملاك
│   │   ├── projects.py      # إدارة المشاريع
│   │   ├── units.py         # إدارة الوحدات
│   │   ├── bookings.py      # إدارة الحجوزات
│   │   ├── customers.py     # إدارة العملاء
│   │   ├── transactions.py  # المعاملات المالية
│   │   ├── dashboard.py     # ملخص لوحة التحكم
│   │   ├── ai.py            # المساعد الذكي
│   │   └── employee_performance.py  # أداء الموظفين
│   │
│   ├── schemas/             # Pydantic Schemas
│   ├── services/            # منطق الأعمال
│   └── utils/               # أدوات مساعدة
│       └── security.py      # تشفير وJWT
│
├── migrations/              # Alembic migrations
├── requirements.txt         # المتطلبات
├── Procfile                 # Railway deployment
└── railway.json             # إعدادات Railway
```

---

## 📊 نماذج البيانات

### User (المستخدم)
```python
- id, username, email, hashed_password
- first_name, last_name, phone
- role: system_owner | admin | owners_agent | customers_agent
- is_active, is_system_owner
```

### Owner (المالك)
```python
- id, owner_name, owner_mobile_phone
- paypal_email, note
- projects (relationship)
```

### Project (المشروع)
```python
- id, owner_id, name
- city, district, map_url
- contract_no, contract_status, contract_duration
- commission_percent, bank_name, bank_iban
- units (relationship)
```

### Unit (الوحدة)
```python
- id, project_id, unit_name, unit_type
- rooms, floor_number, unit_area
- status: متاحة | محجوزة | صيانة | ...
- price_days_of_week, price_in_weekends
- amenities, description, permit_no
```

### Booking (الحجز)
```python
- id, unit_id, customer_id
- guest_name, guest_phone, guest_gender (optional)
- check_in_date, check_out_date
- total_price, status, notes
```

### Customer (العميل)
```python
- id, name, phone (unique - normalized Saudi format)
- email, gender
- booking_count, completed_booking_count, total_revenue
- is_banned, ban_reason
- is_profile_complete  # False if created from booking
```

---

## 🔄 Auto Customer Sync (مزامنة العملاء التلقائية)

عند إنشاء أي حجز جديد، النظام يقوم تلقائياً بـ:

### ✨ التنظيف (Sanitization)
- **الاسم**: إزالة المسافات الزائدة والأحرف الغير مرغوبة
- **الجوال**: توحيد الصيغة السعودية (05xxxxxxxx)
  - Supports: `+966`, `966`, `00966`, `05`, `5`
  - Removes: spaces, dashes, special chars

### 🔀 Upsert Logic
```
إذا العميل موجود (بنفس الجوال):
  ├── تحديث الحقول الناقصة فقط (gender, email)
  ├── زيادة booking_count
  └── إضافة المبلغ لـ total_revenue

إذا العميل جديد:
  ├── إنشاء تلقائي مع is_profile_complete = false
  ├── booking_count = 1
  └── total_revenue = مبلغ الحجز
```

### 📋 API Endpoints
```
GET  /api/customers/stats      - إحصائيات العملاء
GET  /api/customers/incomplete - العملاء ناقصة البيانات
GET  /api/customers/           - قائمة العملاء (الناقصين أولاً)
```

### 🎯 CustomersDashboard Features
- Banner للملفات الناقصة (created from bookings)
- العملاء الناقصين في أعلى الجدول
- زر "إكمال البيانات"

---

## 🔐 نظام الصلاحيات

```
👑 system_owner (4) - كل الصلاحيات
    │
    └── 🔑 admin (3) - كل شي ما عدا System Owner
            │
            └── 👔 owners_agent (2) - الملاك، المشاريع، الوحدات
                    │
                    └── 👤 customers_agent (1) - الوحدات + الحجوزات
```

---

## 🚀 التشغيل

### متطلبات
- Python 3.10+
- PostgreSQL 13+

### التثبيت
```bash
# إنشاء بيئة افتراضية
python -m venv venv
venv\Scripts\activate  # Windows
source venv/bin/activate  # Linux/Mac

# تثبيت المتطلبات
pip install -r requirements.txt
```

### متغيرات البيئة (`.env`)
```env
DATABASE_URL=postgresql://user:password@localhost:5432/mnam_db
SECRET_KEY=your-super-secret-key-here
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440
```

### تشغيل الخادم
```bash
# Development
uvicorn app.main:app --reload --port 8000

# Production
gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker
```

---

## 🌐 API Endpoints

### 🔐 Auth
| Method | Endpoint | الوصف |
|--------|----------|-------|
| POST | `/api/auth/login` | تسجيل الدخول |
| GET | `/api/auth/me` | بيانات المستخدم الحالي |

### 👥 Users
| Method | Endpoint | الوصف |
|--------|----------|-------|
| GET | `/api/users/` | قائمة المستخدمين |
| POST | `/api/users/` | إنشاء مستخدم |
| PUT | `/api/users/{id}` | تعديل مستخدم |
| DELETE | `/api/users/{id}` | حذف مستخدم |

### 🏢 Owners
| Method | Endpoint | الوصف |
|--------|----------|-------|
| GET | `/api/owners/` | قائمة الملاك |
| POST | `/api/owners/` | إضافة مالك |
| PUT | `/api/owners/{id}` | تعديل مالك |
| DELETE | `/api/owners/{id}` | حذف مالك |

### 🏠 Projects / Units / Bookings
مماثل للـ endpoints أعلاه.

### 📊 Dashboard
| Method | Endpoint | الوصف |
|--------|----------|-------|
| GET | `/api/dashboard/summary` | ملخص لوحة التحكم |

---

## 📚 API Documentation

بعد تشغيل الخادم، الوثائق التفاعلية متاحة على:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

---

## 🚀 النشر على Railway

### Procfile
```
web: alembic upgrade head && gunicorn app.main:app -w 2 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT --timeout 120
```

### railway.json
```json
{
  "build": {
    "builder": "NIXPACKS"
  },
  "deploy": {
    "startCommand": "alembic upgrade head && gunicorn app.main:app -w 2 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT --timeout 120",
    "healthcheckPath": "/health",
    "healthcheckTimeout": 60,
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 10
  }
}
```

### متغيرات البيئة على Railway
1. `DATABASE_URL` - من PostgreSQL service
2. `SECRET_KEY` - مفتاح سري قوي
3. `ALGORITHM` - HS256
4. `ACCESS_TOKEN_EXPIRE_MINUTES` - 1440
5. `ENVIRONMENT` - production

---

## 🗄️ DB Migrations on Railway

### كيف تعمل Migrations تلقائياً؟

عند كل **Redeploy** على Railway:
1. ينفذ `alembic upgrade head` أولاً
2. تُطبق كل migrations الجديدة
3. ثم يبدأ السيرفر

### إضافة Migration جديد (محلياً)

```bash
# Windows
migrate.bat new "add_new_column"

# أو مباشرة
alembic revision --autogenerate -m "add_new_column"
```

### أوامر مفيدة

```bash
# تطبيق كل migrations
alembic upgrade head

# التراجع migration واحد
alembic downgrade -1

# عرض الحالة الحالية
alembic current

# عرض التاريخ
alembic history
```

### ⚠️ قواعد الأمان (مهم جداً!)

عند إنشاء migration جديد:

1. **الأعمدة الجديدة** يجب أن تكون:
   - `nullable=True` (اختياري)
   - أو `server_default='value'` (قيمة افتراضية)
   
   ```python
   # ✅ صحيح
   op.add_column('users', sa.Column('avatar', sa.String(), nullable=True))
   op.add_column('users', sa.Column('points', sa.Integer(), server_default='0'))
   
   # ❌ خطأ - سيفشل إذا كانت هناك بيانات
   op.add_column('users', sa.Column('required_field', sa.String(), nullable=False))
   ```

2. **حذف الأعمدة**: لا تحذف مباشرة، استخدم:
   - أولاً: اجعله nullable
   - ثم: بعد فترة، احذفه

3. **تغيير نوع العمود**: استخدم migration تدريجي:
   - أنشئ عمود جديد بالنوع الجديد
   - انقل البيانات
   - احذف القديم
   - أعد تسمية الجديد

### هيكل مجلد alembic
```
alembic/
├── env.py           # إعدادات Environment
├── script.py.mako   # قالب Migration
└── versions/        # ملفات Migration
    ├── 001_initial.py
    └── ...
```

---

## 🧪 اختبار API

```bash
# Health check
curl http://localhost:8000/health

# Login
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=admin"
```

---

## 👤 المستخدمين الافتراضيين

| Username | Password | Role |
|----------|----------|------|
| Head_Admin | H112as112! | system_owner |
| admin | admin | admin |

---

<div align="center">

**جزء من نظام مِنَام العقاري 🏠**

</div>

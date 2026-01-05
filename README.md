# mnam-backend

نظام Backend لإدارة العقارات والحجوزات باستخدام FastAPI + SQLAlchemy

## 🚀 التشغيل المحلي

### 1. إنشاء البيئة الافتراضية
```bash
python -m venv venv
venv\Scripts\activate  # Windows
# أو
source venv/bin/activate  # Linux/Mac
```

### 2. تثبيت المتطلبات
```bash
pip install -r requirements.txt
```

### 3. تشغيل السيرفر
```bash
uvicorn app.main:app --reload
```

### 4. فتح التوثيق
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

---

## 🚂 النشر على Railway

### الخطوة 1: إنشاء مشروع على Railway
1. اذهب إلى [railway.app](https://railway.app)
2. أنشئ مشروع جديد (New Project)
3. اختر "Deploy from GitHub repo"
4. اربط الـ repo الخاص بك

### الخطوة 2: إضافة قاعدة بيانات PostgreSQL
1. في مشروعك على Railway، اضغط "+ New"
2. اختر "Database" → "PostgreSQL"
3. Railway سيُنشئ `DATABASE_URL` تلقائياً

### الخطوة 3: إضافة متغيرات البيئة
في Settings → Variables، أضف:

| Variable | القيمة | ملاحظة |
|----------|--------|--------|
| `SECRET_KEY` | `your-secret-key` | استخدم: `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `ENVIRONMENT` | `production` | مهم! |
| `FRONTEND_URL` | `https://your-frontend.vercel.app` | رابط الفرونت إند |
| `DATABASE_URL` | (يُملأ تلقائياً) | من PostgreSQL |

### الخطوة 4: النشر
Railway سينشر التطبيق تلقائياً عند كل push.

### التحقق من النشر
- Health Check: `https://your-app.railway.app/health`
- API Docs: `https://your-app.railway.app/docs`

---

## 📁 هيكل المشروع
```
mnam-backend/
├── app/
│   ├── main.py           # نقطة الدخول
│   ├── config.py         # الإعدادات
│   ├── database.py       # قاعدة البيانات
│   ├── models/           # نماذج SQLAlchemy
│   ├── schemas/          # Pydantic schemas
│   ├── routers/          # API endpoints
│   └── utils/            # أدوات مساعدة
├── Procfile              # أمر التشغيل
├── railway.json          # إعدادات Railway
├── nixpacks.toml         # إعدادات البناء
├── runtime.txt           # نسخة Python
├── requirements.txt      # المتطلبات
└── .env.example          # مثال متغيرات البيئة
```

## 🔐 المصادقة
- المستخدم الافتراضي: `admin` / `admin`
- JWT tokens للمصادقة
- Role-based access (system_owner/admin/owners_agent/customers_agent)

## 📝 API Endpoints
- `/api/auth` - المصادقة
- `/api/users` - المستخدمين
- `/api/owners` - الملاك
- `/api/projects` - المشاريع
- `/api/units` - الوحدات
- `/api/bookings` - الحجوزات
- `/api/transactions` - المعاملات المالية
- `/api/dashboard` - لوحة التحكم
- `/api/ai` - الذكاء الاصطناعي

## 🔗 ملاحظة حول المسارات (Trailing Slash)
جميع الـ endpoints تدعم الوصول **مع وبدون** trailing slash لمنع الـ 307 Redirects:
```
GET /api/owners   ✅
GET /api/owners/  ✅
POST /api/units   ✅
POST /api/units/  ✅
```
هذا يضمن عمل الـ API بشكل صحيح في بيئات الإنتاج حيث قد يتم حظر HTTP redirects.

## 🐛 استكشاف الأخطاء

### "Application failed to start"
- تأكد من وجود `DATABASE_URL` و `SECRET_KEY` في Variables
- تحقق من Logs في Railway

### "CORS error"
- تأكد من أن `FRONTEND_URL` يحتوي على رابط الفرونت إند الصحيح
- لا تضف `/` في نهاية الرابط

### "Database connection failed"
- تأكد من ربط PostgreSQL بالتطبيق في Railway
- تحقق من أن `DATABASE_URL` موجود في Variables

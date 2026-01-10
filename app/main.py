from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from .config import settings
from .database import create_tables, run_migrations, get_db, SessionLocal
from .models.user import User, UserRole, SYSTEM_OWNER_DATA
from .utils.security import hash_password

# Import all routers
from .routers import auth, users, owners, projects, units, bookings, transactions, dashboard, ai, customers, employee_performance


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    print("🚀 Starting mnam-backend...")
    create_tables()
    run_migrations()
    
    db = SessionLocal()
    try:
        # إنشاء مالك النظام (System Owner) إذا لم يكن موجوداً
        system_owner = db.query(User).filter(User.is_system_owner == True).first()
        if not system_owner:
            owner_user = User(
                username=SYSTEM_OWNER_DATA["username"],
                email=SYSTEM_OWNER_DATA["email"],
                hashed_password=hash_password(SYSTEM_OWNER_DATA["password"]),
                first_name=SYSTEM_OWNER_DATA["first_name"],
                last_name=SYSTEM_OWNER_DATA["last_name"],
                role=SYSTEM_OWNER_DATA["role"],
                is_system_owner=True,
                is_active=True
            )
            db.add(owner_user)
            db.commit()
            print("👑 Created System Owner (Head_Admin)")
        else:
            print("👑 System Owner already exists")
        
        # إنشاء مدير افتراضي إذا لم يكن موجوداً
        admin = db.query(User).filter(User.username == "admin").first()
        if not admin:
            admin_user = User(
                username="admin",
                email="admin@manam.sa",
                hashed_password=hash_password("admin"),
                first_name="مدير",
                last_name="النظام",
                phone="0500000000",
                role=UserRole.ADMIN.value,
                is_active=True,
                is_system_owner=False
            )
            db.add(admin_user)
            db.commit()
            print("✅ Created default admin user (admin/admin)")
    finally:
        db.close()
    
    print("✅ Database tables created")
    print("📝 API Documentation: http://localhost:8000/docs")
    
    yield
    
    # Shutdown
    print("👋 Shutting down mnam-backend...")


# Create FastAPI app
app = FastAPI(
    title="منام - Mnam Backend API",
    description="نظام إدارة العقارات والحجوزات",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://mnam.vercel.app",
        "https://mnam-sys.vercel.app",
        "http://localhost:5173",
    ],
    allow_credentials=False,   # True فقط لو Cookies
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(owners.router)
app.include_router(projects.router)
app.include_router(units.router)
app.include_router(bookings.router)
app.include_router(customers.router)
app.include_router(transactions.router)
app.include_router(dashboard.router)
app.include_router(ai.router)
app.include_router(employee_performance.router)


@app.get("")
@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "مرحباً بك في API منام",
        "version": "1.0.0",
        "docs": "/docs",
        "status": "running"
    }


@app.get("/health")
@app.get("/health/")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}

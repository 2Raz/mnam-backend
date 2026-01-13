from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from contextlib import asynccontextmanager
from slowapi.errors import RateLimitExceeded
import uuid

from .config import settings
from .database import create_tables, run_migrations, SessionLocal
from .models.user import User, UserRole, SYSTEM_OWNER_DATA
from .utils.security import hash_password
from .utils.rate_limiter import limiter

# Import all routers
from .routers import auth, users, owners, projects, units, bookings, transactions, dashboard, ai, customers, employee_performance


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    print("🚀 Starting mnam-backend...")
    print(f"📍 Environment: {settings.environment}")
    print(f"🔐 CORS Origins: {settings.cors_origins}")
    
    create_tables()
    run_migrations()
    
    db = SessionLocal()
    try:
        # Create System Owner if not exists
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
        
        # Create default admin if not exists
        admin = db.query(User).filter(User.username == "admin").first()
        if not admin:
            admin_user = User(
                username="admin",
                email="admin@manam.sa",
                hashed_password=hash_password("Admin123!"),
                first_name="مدير",
                last_name="النظام",
                phone="0500000000",
                role=UserRole.ADMIN.value,
                is_active=True,
                is_system_owner=False
            )
            db.add(admin_user)
            db.commit()
            print("✅ Created default admin user (admin/Admin123!)")
    finally:
        db.close()
    
    print("✅ Database ready")
    print("📝 API Documentation: http://localhost:8000/docs")
    
    yield
    
    print("👋 Shutting down mnam-backend...")


# Create FastAPI app
app = FastAPI(
    title="منام - Mnam Backend API",
    description="نظام إدارة العقارات والحجوزات",
    version="2.0.0",
    lifespan=lifespan
)

# Rate limiter state
app.state.limiter = limiter


# ================================
# CORS MIDDLEWARE - MUST BE FIRST!
# ================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)


# Security Headers Middleware
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        if settings.is_production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


# Request ID Middleware
class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4())[:8])
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


# Add other middleware AFTER CORS
app.add_middleware(RequestIdMiddleware)
app.add_middleware(SecurityHeadersMiddleware)


# Rate limit handler
@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": "كثرة المحاولات، حاول لاحقاً"}
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
    return {
        "message": "مرحباً بك في API منام",
        "version": "2.0.0",
        "docs": "/docs",
        "status": "running",
        "cors_origins": settings.cors_origins
    }


@app.get("/health")
@app.get("/health/")
async def health_check():
    return {"status": "healthy"}

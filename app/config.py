from pydantic_settings import BaseSettings
from pydantic import Field, field_validator
from functools import lru_cache
from typing import List
import os


class Settings(BaseSettings):
    # Environment
    environment: str = Field(default="development", alias="ENVIRONMENT")
    
    # Database - PostgreSQL for production, SQLite for development
    database_url: str = Field(
        default="sqlite:///./mnam.db",
        alias="DATABASE_URL"
    )
    
    # Security - REQUIRED, no defaults
    secret_key: str = Field(default="dev-secret-key-at-least-32-characters-long-for-development", alias="SECRET_KEY")
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    
    # Password policy
    min_password_length: int = 8
    require_password_uppercase: bool = True
    require_password_digit: bool = True
    
    # Cookie settings (cross-domain)
    cookie_secure: bool = Field(default=False, alias="COOKIE_SECURE")  # False for localhost
    cookie_samesite: str = "lax"  # "none" for cross-domain, "lax" for same-origin
    cookie_domain: str = ""
    
    # AI
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    
    # CORS - Frontend URLs from environment (comma-separated)
    allowed_origins: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000,http://localhost:3002,http://127.0.0.1:3002,http://localhost:5173,http://127.0.0.1:5173,https://mnam-sys-dash.vercel.app",
        alias="ALLOWED_ORIGINS"
    )
    
    @field_validator('secret_key')
    @classmethod
    def validate_secret_key(cls, v: str) -> str:
        """Validate SECRET_KEY is strong enough in production"""
        if not v:
            raise ValueError("SECRET_KEY is required and cannot be empty")
        if len(v) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters long")
        return v
    
    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"
    
    @property
    def cors_origins(self) -> List[str]:
        """
        Parse allowed origins from comma-separated string.
        Returns a list suitable for CORSMiddleware.
        """
        if not self.allowed_origins:
            return ["http://localhost:5173"]
        
        origins = []
        for origin in self.allowed_origins.split(","):
            origin = origin.strip().rstrip("/")  # Remove trailing slashes
            if origin:
                origins.append(origin)
        
        # Remove duplicates while preserving order
        seen = set()
        unique_origins = []
        for o in origins:
            if o not in seen:
                seen.add(o)
                unique_origins.append(o)
        
        return unique_origins if unique_origins else ["http://localhost:5173"]
    
    class Config:
        env_file = ".env"
        extra = "ignore"
        populate_by_name = True


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()


# Initialize settings on module load
settings = get_settings()

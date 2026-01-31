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
        default="http://localhost:3000,http://127.0.0.1:3000,http://localhost:3002,http://127.0.0.1:3002,http://localhost:5173,http://127.0.0.1:5173,https://mnam-sys-dash.vercel.app,https://api.usemnam.com",
        alias="ALLOWED_ORIGINS"

    )
    
    # ==============================================
    # Channex Integration Settings (Server-Side Only!)
    # ==============================================
    # Base URL for Channex API (staging vs production)
    channex_base_url: str = Field(
        default="https://app.channex.io/api/v1",
        alias="CHANNEX_BASE_URL"
    )
    
    # Webhook secret for validating incoming webhooks
    channex_webhook_secret: str = Field(default="", alias="CHANNEX_WEBHOOK_SECRET")
    
    # Weekend days for Saudi Arabia (default: Friday=4, Saturday=5)
    # Format: comma-separated weekday numbers (Monday=0, Sunday=6)
    weekend_days: str = Field(default="4,5", alias="WEEKEND_DAYS")
    
    # Rate limits per property per minute
    channex_price_rate_limit: int = Field(default=10, alias="CHANNEX_PRICE_RATE_LIMIT")
    channex_avail_rate_limit: int = Field(default=10, alias="CHANNEX_AVAIL_RATE_LIMIT")
    
    # Sync horizon (days ahead to push)
    channex_sync_days: int = Field(default=365, alias="CHANNEX_SYNC_DAYS")
    
    # Max payload size (bytes) - Channex limit is 10MB
    channex_max_payload_bytes: int = Field(default=10_000_000, alias="CHANNEX_MAX_PAYLOAD_BYTES")
    
    # Enable/Disable Channex integration globally
    channex_enabled: bool = Field(default=True, alias="CHANNEX_ENABLED")
    
    # Webhook security settings
    channex_allowed_ips: str = Field(default="", alias="CHANNEX_ALLOWED_IPS")  # Comma-separated
    channex_webhook_replay_window_seconds: int = Field(default=300, alias="CHANNEX_WEBHOOK_REPLAY_WINDOW")
    
    # Batch control settings for outbox worker
    channex_batch_max_units: int = Field(default=50, alias="CHANNEX_BATCH_MAX_UNITS")
    channex_date_range_compression: bool = Field(default=True, alias="CHANNEX_DATE_RANGE_COMPRESSION")
    
    # Worker settings (runs inside FastAPI process)
    worker_poll_interval: int = Field(default=10, alias="WORKER_POLL_INTERVAL")  # seconds
    worker_batch_size: int = Field(default=50, alias="WORKER_BATCH_SIZE")
    
    @property
    def channex_allowed_ip_list(self) -> List[str]:
        """Parse allowed IPs for webhook validation"""
        if not self.channex_allowed_ips:
            return []
        return [ip.strip() for ip in self.channex_allowed_ips.split(",") if ip.strip()]
    
    # ==============================================
    # Channex LOCAL Testing (Development Only!)
    # ==============================================
    # API Key for local testing - NEVER commit to git
    channex_api_key: str = Field(default="", alias="CHANNEX_API_KEY")
    
    # Staging IDs for local testing
    channex_property_id: str = Field(default="", alias="CHANNEX_PROPERTY_ID")
    channex_room_type_id: str = Field(default="", alias="CHANNEX_ROOM_TYPE_ID")
    channex_rate_plan_id: str = Field(default="", alias="CHANNEX_RATE_PLAN_ID")
    
    # HTTP timeout for Channex requests
    channex_timeout_seconds: int = Field(default=20, alias="CHANNEX_TIMEOUT_SECONDS")
    
    @property
    def has_local_channex_config(self) -> bool:
        """Check if all local Channex config is present"""
        return bool(
            self.channex_api_key and
            self.channex_property_id and
            self.channex_room_type_id and
            self.channex_rate_plan_id
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
    
    @property
    def weekend_day_numbers(self) -> List[int]:
        """
        Parse weekend days into list of weekday numbers.
        Default: [4, 5] (Friday, Saturday - Saudi Arabia)
        """
        try:
            return [int(d.strip()) for d in self.weekend_days.split(",") if d.strip()]
        except ValueError:
            return [4, 5]  # Default to Saudi weekend
    
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

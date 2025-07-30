# core/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    TELEGRAM_BOT_TOKEN: str
    ADMIN_USER_IDS: str
    GOOGLE_PROJECT_ID: str
    GOOGLE_LOCATION: str
    GOOGLE_APPLICATION_CREDENTIALS: str
    GEMINI_MODEL_NAME: str = "gemini-1.5-flash-latest"
    DATABASE_URL: str
    REDIS_URL: str
    
    @property
    def admin_ids_list(self) -> list[int]:
        if not self.ADMIN_USER_IDS: return []
        return [int(admin_id.strip()) for admin_id in self.ADMIN_USER_IDS.split(',') if admin_id.strip()]

    class Config:
        env_file = ".env"
        env_file_encoding = 'utf-8'
        extra = 'ignore'

settings = Settings()

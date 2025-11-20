from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    APP_NAME: str
    SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"

    DB_HOST: str
    DB_PORT: int
    DB_DATABASE_NAME: str
    DB_PASSWORD: str
    DB_USERNAME: str
    
    sms_secrete: str
    client_id: str
    api_key: str
    
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8"
    )
    
settings = Settings()
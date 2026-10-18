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
    # Opens only the /admin page's data (/api/admin/*); unset keeps it locked.
    admin_api_key: str = ""

    # Transflow (mandate / recurring debit order)
    TRANSFLOW_BASE_URL: str = "https://ddv15-debit-order-api.transflowitc.com"
    TRANSFLOW_MERCHANT_ID: str
    TRANSFLOW_PRODUCT_ID: str
    TRANSFLOW_API_KEY: str

    # Uniwallet (one-time mobile-money debit)
    UNIWALLET_BASE_URL: str = "https://uniwallet.itcsrvc.com"
    UNIWALLET_X_KEY: str
    UNIWALLET_X_COUNTRY: str = "GH"
    UNIWALLET_PRODUCT_ID: str
    UNIWALLET_TRANSFLOW_ID: str

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8"
    )
    
settings = Settings()
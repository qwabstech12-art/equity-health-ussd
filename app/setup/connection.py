from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from app.config.service import settings
from urllib.parse import quote_plus



MYSQL_USER = settings.DB_USERNAME
MYSQL_PASSWORD = quote_plus(settings.DB_PASSWORD)
MYSQL_HOST = settings.DB_HOST
MYSQL_PORT = settings.DB_PORT
MYSQL_DB = settings.DB_DATABASE_NAME


DATABASE_URL = f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
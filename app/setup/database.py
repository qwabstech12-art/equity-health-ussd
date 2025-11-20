from app.setup.connection import SessionLocal


def get_db():
   db = SessionLocal()
   try:
       yield db
   finally:
       db.close()
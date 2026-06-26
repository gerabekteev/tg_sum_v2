from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
import config

engine = create_engine(config.DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def init_db():
    """Создает все таблицы в базе данных."""
    import database.models  # Импортируем модели для регистрации в Base
    Base.metadata.create_all(bind=engine)

def get_db():
    """Контекстный менеджер для получения сессии базы данных."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

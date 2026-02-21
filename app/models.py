import hashlib
import os  # <-- Добавьте этот импорт!
from sqlmodel import SQLModel, Field, create_engine, Session, select
from typing import Optional
from datetime import datetime
from uuid import uuid4

# 🔧 ИСПРАВЛЕНИЕ: Получаем базовый URL из переменной окружения и меняем имя базы
# Берём URL из DATABASE_URL, который мы задали в docker-compose.yml
BASE_DATABASE_URL = os.getenv("DATABASE_URL")

if not BASE_DATABASE_URL:
    # Fallback для локальной разработки
    BASE_DATABASE_URL = "postgresql://todouser:securepass123@localhost/todos"

# Заменяем имя базы данных в URL с "todos" на "todo_users_db"
# Разбиваем URL, меняем последний сегмент и собираем обратно
url_parts = BASE_DATABASE_URL.rsplit('/', 1)
USER_DATABASE_URL = f"{url_parts[0]}/todo_users_db"

# Движок для базы пользователей
user_engine = create_engine(USER_DATABASE_URL)
SessionLocal = Session(user_engine)


# Самая простая версия моделей
class User(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    username: str
    email: str  
    hashed_password: str
    role: str = "user"
    created_at: datetime = Field(default_factory=datetime.now)
    is_active: bool = True

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return hash_password(plain_password) == hashed_password

# Настройки базы
#user_engine = create_engine("sqlite:///users.db")
#SessionLocal = Session(user_engine)

def create_user_tables():
    SQLModel.metadata.create_all(user_engine)

def get_user_session():
    return SessionLocal

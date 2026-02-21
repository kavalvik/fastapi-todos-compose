from sqlmodel import SQLModel, Field, create_engine, Session
from typing import Optional
from datetime import datetime
from uuid import uuid4
import os  # <-- Добавьте этот импорт!

# Модель Todo (остаётся без изменений)
class Todo(SQLModel, table=True):
    id: Optional[str] = Field(default=None, primary_key=True)
    title: str
    description: Optional[str] = None
    completed: bool = False
    priority: int = 1
    tags: str = ""
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: Optional[datetime] = None
    deadline: Optional[datetime] = None
    user_id: str

# 🔧 КЛЮЧЕВОЕ ИСПРАВЛЕНИЕ: Получаем URL из переменной окружения
# Если переменной DATABASE_URL нет (например, при локальном запуске), 
# можно вернуться к SQLite или выбросить ошибку.
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    # Запасной вариант или явная ошибка. Можно оставить так для отладки без Docker.
    print("ВНИМАНИЕ: Переменная DATABASE_URL не задана. Использую SQLite.")
    DATABASE_URL = "sqlite:///./todos.db"

# Создаём движок SQLAlchemy для PostgreSQL
engine = create_engine(DATABASE_URL, echo=True)  # echo=True для логирования SQL

def create_db_and_tables():
    """Создаёт все таблицы в базе данных"""
    SQLModel.metadata.create_all(engine)

def get_session():
    """Возвращает сессию для работы с базой данных"""
    return Session(engine)


















































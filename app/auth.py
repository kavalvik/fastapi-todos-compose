from datetime import datetime, timedelta
from fastapi import HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional
from jose import jwt, JWTError
from sqlmodel import select

# Импорты из models
from models import User, hash_password, verify_password, get_user_session, create_user_tables

# 🔐 Настройки JWT
SECRET_KEY = "your-super-secret-jwt-key-change-in-production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

security = HTTPBearer()

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    credentials_exception = HTTPException(
        status_code=401,
        detail="Неверные учетные данные",
    )
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    session = get_user_session()
    user = session.exec(select(User).where(User.username == username)).first()
    session.close()
    
    if user is None or not user.is_active:
        raise credentials_exception
    
    return user

async def get_current_active_user(current_user: User = Depends(get_current_user)):
    return current_user

async def get_admin_user(current_user: User = Depends(get_current_active_user)):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Требуются админские права")
    return current_user

def create_default_admin():
    """Создает администратора по умолчанию если его нет"""
    session = get_user_session()
    admin = session.exec(select(User).where(User.username == "admin")).first()
    if not admin:
        admin_user = User(
            username="admin",
            email="admin@example.com",
            hashed_password=hash_password("admin123"),
            role="admin"
        )
        session.add(admin_user)
        session.commit()
        print("👑 Создан администратор: admin/admin123")
    session.close()

# Создаем таблицы и администратора
create_user_tables()
create_default_admin()

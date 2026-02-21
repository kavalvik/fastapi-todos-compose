from fastapi import FastAPI, HTTPException, Depends, Header, BackgroundTasks, Request, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from typing import List, Optional, Any
from uuid import uuid4
import os
from datetime import datetime, timedelta
import time
import asyncio
from cachetools import TTLCache
import secrets

# Импорты аутентификации
from auth import (
    User, verify_password, hash_password, get_user_session, # <- ДОБАВЛЯЕМ ЗДЕСЬ
    create_access_token, get_current_user, get_current_active_user, get_admin_user,
    SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES
)

# Импорты зависимостей и базы данных
from dependencies import (
    get_todo_by_id, PaginationParams, 
    log_get_request, log_post_request, log_put_request, log_delete_request
)
from database import Todo, create_db_and_tables, get_session
from sqlmodel import Session, select

app = FastAPI(title="Multi-User Todo API", version="2.0.0")

# 🔧 КЭШИРОВАНИЕ
cache = TTLCache(maxsize=1000, ttl=300)

def get_cache_key(request: Request, **kwargs) -> str:
    """Генерирует уникальный ключ для кэша на основе URL и параметров"""
    query_params = str(sorted(request.query_params.items()))
    path = request.url.path
    user_id = kwargs.get('user_id', '')
    return f"{user_id}:{path}:{query_params}"

async def get_cached_data(key: str) -> Optional[Any]:
    return cache.get(key)

async def set_cached_data(key: str, data: Any):
    cache[key] = data

async def invalidate_todos_cache():
    """Очистить кэш связанный с задачами"""
    keys_to_remove = [key for key in cache.keys() if '/todos' in key]
    for key in keys_to_remove:
        cache.pop(key, None)
    print("🧹 Кэш задач очищен")

# 🔧 MIDDLEWARE
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from collections import defaultdict

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Разрешаем все origins для тестирования
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["*"]  # Разрешаем все хосты для тестирования
)

@app.middleware("http")
async def log_requests_middleware(request: Request, call_next):
    start_time = time.time()
    print(f"🌐 ВХОДЯЩИЙ ЗАПРОС: {request.method} {request.url}")
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    print(f"📤 ИСХОДЯЩИЙ ОТВЕТ: {response.status_code}")
    print(f"   ⏱️ Время обработки: {process_time:.4f} сек")
    return response

# Rate Limiting
request_counts = defaultdict(list)

@app.middleware("http") 
async def rate_limiting_middleware(request: Request, call_next):
    client_ip = request.client.host
    now = datetime.now()
    
    request_counts[client_ip] = [
        timestamp for timestamp in request_counts[client_ip] 
        if now - timestamp < timedelta(minutes=1)
    ]
    
    if len(request_counts[client_ip]) >= 200:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=429,
            content={"error": "Too Many Requests", "message": "Превышен лимит запросов"}
        )
    
    request_counts[client_ip].append(now)
    response = await call_next(request)
    response.headers["X-RateLimit-Limit"] = "200"
    response.headers["X-RateLimit-Remaining"] = str(200 - len(request_counts[client_ip]))
    return response

# 🔧 ФОНОВЫЕ ЗАДАЧИ
async def send_notification(email: str, message: str):
    print(f"📧 Отправка уведомления для {email}...")
    await asyncio.sleep(2)
    print(f"✅ Уведомление отправлено: {message}")
    return {"status": "sent", "email": email, "message": message}

async def update_analytics(todo_title: str, action: str):
    print(f"📊 Аналитика: {action} - '{todo_title}'")
    await asyncio.sleep(1)
    return {"action": action, "title": todo_title}

async def cleanup_old_todos():
    print("🧹 Очистка старых задач...")
    await asyncio.sleep(3)
    print("✅ Очистка завершена!")
    return {"cleaned": True}

# Pydantic модели
class UserRegister(BaseModel):
    username: str
    email: str
    password: str

class UserLogin(BaseModel):
    username: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str
    username: str
    role: str

class TodoItem(BaseModel):
    title: str
    description: Optional[str] = None
    completed: bool = False
    priority: int = 1
    tags: List[str] = []
    deadline: Optional[str] = None

class TodoUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    completed: Optional[bool] = None
    priority: Optional[int] = None
    tags: Optional[List[str]] = None
    deadline: Optional[str] = None

class TodoResponse(BaseModel):
    id: str
    title: str
    description: Optional[str]
    completed: bool
    priority: int
    tags: List[str]
    created_at: datetime
    updated_at: Optional[datetime]
    deadline: Optional[datetime]
    user_id: str

def todo_to_response(todo):
    return TodoResponse(
        id=todo.id,
        title=todo.title,
        description=todo.description,
        completed=todo.completed,
        priority=todo.priority,
        tags=todo.tags.split(",") if todo.tags else [],
        created_at=todo.created_at,
        updated_at=todo.updated_at,
        deadline=todo.deadline,
        user_id=todo.user_id
    )

# 🔐 ЭНДПОИНТЫ АУТЕНТИФИКАЦИИ
@app.post("/register", response_model=dict)
async def register(user_data: UserRegister):
    with get_user_session() as session:
        # Проверяем нет ли пользователя с таким именем
        existing_user = session.exec(select(User).where(User.username == user_data.username)).first()
        if existing_user:
            raise HTTPException(status_code=400, detail="Пользователь с таким именем уже существует")
        
        # Проверяем нет ли пользователя с таким email
        existing_email = session.exec(select(User).where(User.email == user_data.email)).first()
        if existing_email:
            raise HTTPException(status_code=400, detail="Пользователь с таким email уже существует")
        
        # Создаем нового пользователя
        hashed_password = hash_password(user_data.password)
        user = User(
            username=user_data.username,
            email=user_data.email,
            hashed_password=hashed_password,
            role="user"  # По умолчанию обычный пользователь
        )
        
        session.add(user)
        session.commit()
        session.refresh(user)
        
        print(f"👤 Зарегистрирован новый пользователь: {user_data.username}")
        
        return {"message": "Пользователь успешно зарегистрирован", "username": user_data.username}

# Временно добавлен эндпойнт для отладки /login-debug
#@app.post("/login-debug")
#async def login_debug(request: Request):
    #"""Специальный эндпоинт для отладки ab тестов"""
    ## 1. Показываем все заголовки
    #print("📨 ЗАГОЛОВКИ ЗАПРОСА:")
    #for name, value in request.headers.items():
        #print(f"  {name}: {value}")
    
    ## 2. Пытаемся прочитать тело как текст
    #body_bytes = await request.body()
    #body_text = body_bytes.decode('utf-8', errors='replace')
    #print(f"📦 ТЕЛО ЗАПРОСА (сырое): '{body_text}'")
    #print(f"📦 Длина тела: {len(body_bytes)} байт")
    
    ## 3. Пытаемся прочитать как JSON
    #try:
        #import json
        #body_json = json.loads(body_text)
        #print(f"✅ JSON успешно распарсен: {body_json}")
    #except json.JSONDecodeError as e:
        #print(f"❌ Ошибка парсинга JSON: {e}")
        #print(f"   Первые 50 байт: {body_bytes[:50]}")
    
    ## 4. Пытаемся прочитать через form-data
    #form_data = await request.form()
    #if form_data:
        #print(f"📋 Form data: {dict(form_data)}")
    
    #return {"debug": "ok", "body_length": len(body_bytes)}




@app.post("/login", response_model=Token)
async def login(user_data: UserLogin):
    with get_user_session() as session:
        user = session.exec(select(User).where(User.username == user_data.username)).first()
        if not user or not verify_password(user_data.password, user.hashed_password):
            raise HTTPException(status_code=401, detail="Неверное имя пользователя или пароль")
        
        if not user.is_active:
            raise HTTPException(status_code=401, detail="Аккаунт заблокирован")
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username, "role": user.role},
        expires_delta=access_token_expires
    )
    
    print(f"🔑 Пользователь {user.username} вошел в систему")
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "username": user.username,
        "role": user.role
    }

@app.get("/users/me")
async def read_users_me(current_user: User = Depends(get_current_active_user)):
    return {
        "username": current_user.username,
        "email": current_user.email,
        "role": current_user.role
    }

# Событие запуска
@app.on_event("startup")
def on_startup():
    create_db_and_tables()

# 🔄 ОСНОВНЫЕ ЭНДПОИНТЫ TODO
@app.get("/todos", response_model=List[TodoResponse])
async def get_all_todos(
    request: Request,
    current_user: User = Depends(get_current_active_user),
    pagination: PaginationParams = Depends(),
    session: Session = Depends(get_session)
):
    try:
        cache_key = get_cache_key(request, user_id=current_user.username)
        cached_data = await get_cached_data(cache_key)
        if cached_data:
            print(f"✅ КЭШ: Данные для пользователя {current_user.username} загружены из кэша")
            return cached_data
        
        print(f"🔄 БД: Запрос к базе для пользователя {current_user.username}")
        
        query = select(Todo).where(Todo.user_id == current_user.username)
        
        if pagination.completed is not None:
            query = query.where(Todo.completed == pagination.completed)
        if pagination.priority is not None:
            query = query.where(Todo.priority == pagination.priority)
        
        todos = session.exec(query.offset(pagination.skip).limit(pagination.limit)).all()
        result = [todo_to_response(todo) for todo in todos]
        
        await set_cached_data(cache_key, result)
        print(f"💾 КЭШ: Данные для пользователя {current_user.username} сохранены в кэш")
        
        return result
    finally:
        session.close()

@app.post("/todos", response_model=TodoResponse)
async def create_todo(
    todo: TodoItem,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_active_user),
    session: Session = Depends(get_session),
):
    try:
        deadline_dt = None
        if todo.deadline:
            try:
                deadline_value = todo.deadline.replace('Z', '').replace('z', '')
                for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M']:
                    try:
                        deadline_dt = datetime.strptime(deadline_value, fmt)
                        break
                    except ValueError:
                        continue
            except Exception as e:
                print(f"❌ Ошибка дедлайна: {e}")

        tags_str = ",".join(todo.tags)
    
        db_todo = Todo(
            id=str(uuid4()),
            title=todo.title,
            description=todo.description,
            completed=todo.completed,
            priority=todo.priority,
            tags=tags_str,
            deadline=deadline_dt,
            user_id=current_user.username
        )
    
        session.add(db_todo)
        session.commit()
        session.refresh(db_todo)
    
        background_tasks.add_task(invalidate_todos_cache)
        return todo_to_response(db_todo)
    finally:
        session.close()

@app.put("/todos/{todo_id}", response_model=TodoResponse)
async def update_todo(
    updated_todo: TodoUpdate,
    todo_id: str,
    background_tasks: BackgroundTasks,
    todo: Todo = Depends(get_todo_by_id),
    session: Session = Depends(get_session)
):
    try:
        update_data = updated_todo.dict(exclude_unset=True)
    
        if 'deadline' in update_data:
            deadline_value = update_data.pop('deadline')
            if deadline_value is not None:
                try:
                    deadline_value = deadline_value.replace('Z', '').replace('z', '')
                    for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M']:
                        try:
                            deadline_dt = datetime.strptime(deadline_value, fmt)
                            todo.deadline = deadline_dt
                            break
                        except ValueError:
                            continue
                except Exception as e:
                    print(f"❌ Ошибка дедлайна: {e}")
                    todo.deadline = None
    
        if 'tags' in update_data and update_data['tags'] is not None:
            todo.tags = ",".join(update_data['tags'])
    
        for field, value in update_data.items():
            if field not in ['deadline', 'tags']:
                setattr(todo, field, value)
    
        todo.updated_at = datetime.now()
        session.add(todo)
        session.commit()
        session.refresh(todo)
    
        background_tasks.add_task(invalidate_todos_cache)
        return todo_to_response(todo)
    finally:
        session.close()

@app.delete("/todos/{todo_id}")
async def delete_todo(
    todo_id: str,
    background_tasks: BackgroundTasks,
    todo: Todo = Depends(get_todo_by_id),
    session: Session = Depends(get_session)
):
    try:
        session.delete(todo)
        session.commit()
        background_tasks.add_task(invalidate_todos_cache)
        return {"message": "Todo deleted"}
    finally:
        session.close()

# 🆕 ЭНДПОИНТ ДЛЯ АДМИНА: ПОЛУЧЕНИЕ ВСЕХ ЗАДАЧ
@app.get("/admin/todos", response_model=List[TodoResponse])
async def get_all_todos_admin(
    admin: User = Depends(get_admin_user),
    session: Session = Depends(get_session)
):
    """Получить ВСЕ задачи всех пользователей (только для админов)"""
    try:
        todos = session.exec(select(Todo)).all()
        return [todo_to_response(todo) for todo in todos]
    finally:
        session.close()

#Фильтрация ВСЕХ задач (только для админа)
@app.get("/admin/todos/filter", response_model=List[TodoResponse])
async def filter_all_todos_admin(
    admin: User = Depends(get_admin_user),
    pagination: PaginationParams = Depends(),
    session: Session = Depends(get_session)
):
    """Фильтрация ВСЕХ задач (только для админа)"""
    try:
        query = select(Todo)  # ← БЕЗ фильтра по user_id!
        
        if pagination.completed is not None:
            query = query.where(Todo.completed == pagination.completed)
        if pagination.priority is not None:
            query = query.where(Todo.priority == pagination.priority)
        
        todos = session.exec(query.offset(pagination.skip).limit(pagination.limit)).all()
        return [todo_to_response(todo) for todo in todos]
    finally:
        session.close()



# 🆕 АДМИНСКИЕ ЭНДПОИНТЫ
@app.get("/admin/users", response_model=dict)
async def get_all_users(admin: User = Depends(get_admin_user)):
    """Получить список всех пользователей (только для админов)"""
    with get_user_session() as session:
        users = session.exec(select(User)).all()
        return {
            "users": [
                {
                    "id": user.id,
                    "username": user.username,
                    "email": user.email,
                    "role": user.role,
                    "is_active": user.is_active,
                    "created_at": user.created_at
                }
                for user in users
            ],
            "total": len(users)
        }

@app.post("/admin/users/{username}/make-admin")
async def make_user_admin(username: str, admin: User = Depends(get_admin_user)):
    """Сделать пользователя администратором"""
    with get_user_session() as session:
        user = session.exec(select(User).where(User.username == username)).first()
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        
        user.role = "admin"
        session.add(user)
        session.commit()
        
        return {"message": f"Пользователь {username} теперь администратор"}

@app.post("/admin/users/{username}/toggle-active")
async def toggle_user_active(username: str, admin: User = Depends(get_admin_user)):
    """Блокировать/разблокировать пользователя"""
    with get_user_session() as session:
        user = session.exec(select(User).where(User.username == username)).first()
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        
        user.is_active = not user.is_active
        session.add(user)
        session.commit()
        
        status = "активен" if user.is_active else "заблокирован"
        return {"message": f"Пользователь {username} теперь {status}"}

# 🛠️ УТИЛИТЫ
@app.get("/cache/info")
async def get_cache_info():
    return {
        "cache_size": len(cache),
        "cache_max_size": cache.maxsize,
        "cache_ttl": cache.ttl
    }

@app.api_route("/cache/clear", methods=["GET", "POST"])
async def clear_cache(background_tasks: BackgroundTasks):
    background_tasks.add_task(invalidate_todos_cache)
    return {"message": "Кэш очищен"}

@app.get("/todos/stats")
async def get_todo_stats(
    current_user: User = Depends(get_current_active_user),
    session: Session = Depends(get_session)
):
    try:
        query = select(Todo).where(Todo.user_id == current_user.username)
        todos = session.exec(query).all()
        completed = [t for t in todos if t.completed]
    
        return {
            "total": len(todos),
            "completed": len(completed),
            "completion_rate": f"{(len(completed) / len(todos) * 100):.1f}%" if todos else "0%",
            "user": current_user.username
        }
    finally:
        session.close()

@app.get("/status")
async def get_status():
    return {
        "status": "Server is running with Authentication",
        "timestamp": datetime.now()
    }

# Маршрут к фронтенду
@app.get("/todos-app")
async def todos_app():
    html_path = os.path.join(os.path.dirname(__file__), "static", "todos.html")
    with open(html_path, "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content, status_code=200)

from database import Session, get_session
from fastapi import HTTPException, Depends, Header
from auth import get_current_active_user, User
from sqlmodel import select

# 🔧 Зависимость для проверки существования задачи
async def get_todo_by_id(
    todo_id: str, 
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_active_user)
):
    """Зависимость, которая проверяет существование задачи И ПРАВА ДОСТУПА"""
    from database import Todo
    todo = session.get(Todo, todo_id)
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    
    # ⬇️ ПРОВЕРКА ПРАВ ДОСТУПА
    if todo.user_id != current_user.username and current_user.role != "admin":
        raise HTTPException(
            status_code=403, 
            detail="Нет доступа к этой задаче"
        )
    
    return todo

# 🔧 Зависимость для пагинации
class PaginationParams:
    def __init__(self, skip: int = 0, limit: int = 100, completed: bool = None, priority: int = None):
        self.skip = skip
        self.limit = limit
        self.completed = completed
        self.priority = priority

# 🔧 Зависимости для логирования
async def log_get_request(user_agent: str = Header(None)):
    print(f"📨 GET /todos - User Agent: {user_agent}")
    return {"method": "GET", "path": "/todos", "user_agent": user_agent}

async def log_post_request(user_agent: str = Header(None)):
    print(f"📨 POST /todos - User Agent: {user_agent}")
    return {"method": "POST", "path": "/todos", "user_agent": user_agent}

async def log_put_request(todo_id: str, user_agent: str = Header(None)):
    print(f"📨 PUT /todos/{todo_id} - User Agent: {user_agent}")
    return {"method": "PUT", "path": f"/todos/{todo_id}", "user_agent": user_agent}

async def log_delete_request(todo_id: str, user_agent: str = Header(None)):
    print(f"📨 DELETE /todos/{todo_id} - User Agent: {user_agent}")
    return {"method": "DELETE", "path": f"/todos/{todo_id}", "user_agent": user_agent}

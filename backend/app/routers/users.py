import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.user import DEFAULT_THEME_PREFERENCE, VALID_THEME_PREFERENCES, User
from app.models.agent import AgentTask
from app.routers.deps import get_current_user, require_admin
from app.services.audit import create_log
from app.core.security import get_password_hash
from datetime import datetime

router = APIRouter()

VALID_ROLES = {"admin", "user", "viewer"}
VALID_STATUSES = {"active", "inactive", "archived"}

USER_FIELDS = {
    "name",
    "email",
    "network_id",
    "role",
    "status",
    "password_hash",
    "playground_connected",
    "playground_connected_at",
    "playground_session_path",
    "theme_preference",
}


def user_theme_preference(user: User) -> str:
    value = str(getattr(user, "theme_preference", "") or "").strip().lower()
    return value if value in VALID_THEME_PREFERENCES else DEFAULT_THEME_PREFERENCE


def normalize_theme_preference(value: str) -> str:
    text = str(value or "").strip().lower()
    if text not in VALID_THEME_PREFERENCES:
        raise HTTPException(422, "theme_preference must be 'light' or 'dark'")
    return text

def public_user(u: User) -> dict:
    return {
        "id": u.id,
        "name": u.name,
        "email": u.email,
        "network_id": u.network_id,
        "role": u.role,
        "status": u.status,
        "playground_connected": bool(u.playground_connected),
        "playground_connected_at": u.playground_connected_at,
        "theme_preference": user_theme_preference(u),
        "has_profile_photo": bool(u.profile_photo_path),
        "profile_photo_updated_at": u.profile_photo_updated_at,
        "last_login_at": u.last_login_at,
        "created_at": u.created_at,
        "updated_at": u.updated_at,
        "archived_at": u.archived_at,
    }

def user_payload(data: dict) -> dict:
    clean = {key: value for key, value in (data or {}).items() if key in USER_FIELDS}
    for key, value in list(clean.items()):
        if value == "" and key != "theme_preference":
            clean[key] = None
    if "theme_preference" in clean:
        clean["theme_preference"] = normalize_theme_preference(clean["theme_preference"])
    if "role" in clean and clean["role"] is not None:
        if clean["role"] not in VALID_ROLES:
            raise HTTPException(422, f"role must be one of: {', '.join(sorted(VALID_ROLES))}")
    if "status" in clean and clean["status"] is not None:
        if clean["status"] not in VALID_STATUSES:
            raise HTTPException(422, f"status must be one of: {', '.join(sorted(VALID_STATUSES))}")
    return clean

@router.get("")
def list_users(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    users = db.query(User).filter(User.is_deleted == False).all()
    return [public_user(u) for u in users]

@router.post("")
def create_user(user_data: dict, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    password = user_data.pop("password", None)
    if password:
        user_data["password_hash"] = get_password_hash(password)
    clean = user_payload(user_data)
    new_user = User(**clean)
    db.add(new_user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A user with this email or network_id already exists")
    db.refresh(new_user)
    create_log(db, "info", f"User created: {new_user.name}", "user", new_user.id)
    return public_user(new_user)

@router.get("/{id}")
def get_user(id: int, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    u = db.query(User).filter(User.id == id, User.is_deleted == False).first()
    if not u: raise HTTPException(404)
    return public_user(u)

@router.put("/{id}")
def update_user(id: int, user_data: dict, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    u = db.query(User).filter(User.id == id, User.is_deleted == False).first()
    if not u: raise HTTPException(404)
    password = user_data.pop("password", None)
    if password:
        user_data["password_hash"] = get_password_hash(password)
    for k, v in user_payload(user_data).items():
        setattr(u, k, v)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A user with this email or network_id already exists")
    db.refresh(u)
    return public_user(u)

@router.delete("/{id}")
def delete_user(id: int, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    u = db.query(User).filter(User.id == id, User.is_deleted == False).first()
    if not u: raise HTTPException(404)
    u.is_deleted = True
    u.deleted_at = datetime.utcnow()
    db.commit()
    create_log(db, "warning", f"User deleted", "user", u.id)
    return {"status": "deleted"}

@router.post("/{id}/archive")
def archive_user(id: int, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    u = db.query(User).filter(User.id == id, User.is_deleted == False).first()
    if not u: raise HTTPException(404)
    u.status = "archived"
    u.archived_at = datetime.utcnow()
    db.commit()
    create_log(db, "info", f"User archived", "user", u.id)
    return {"status": "archived"}

@router.post("/{id}/actions/{action}")
def user_action(id: int, action: str, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    u = db.query(User).filter(User.id == id, User.is_deleted == False).first()
    if not u:
        raise HTTPException(404)
    if action == "delete":
        u.is_deleted = True
        u.deleted_at = datetime.utcnow()
    elif action == "archive":
        u.status = "archived"
        u.archived_at = datetime.utcnow()
    elif action == "link_playground":
        u.playground_connected = True
        u.playground_connected_at = datetime.utcnow()
    elif action == "unlink_playground":
        u.playground_connected = False
        u.playground_session_path = None
    else:
        raise HTTPException(400, "Invalid action")
    db.commit()
    create_log(db, "info", f"User action {action}", "user", u.id)
    return {"status": "action executed", "action": action}

@router.post("/me/connect-playground")
def connect_playground(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    u = current_user
    u.playground_connected = False
    u.playground_session_path = None
    u.playground_connected_at = None
    db.commit()
    
    task = AgentTask(
        task_type="connect_playground_session",
        status="pending",
        payload_json=json.dumps({"user_id": u.id}, ensure_ascii=False),
        created_by_id=u.id
    )
    db.add(task)
    db.commit()
    create_log(db, "info", "Requested playground connection", "user", u.id, user_id=u.id, task_id=task.id)
    return {"status": "task_created", "task_id": task.id}

@router.put("/{id}/playground-session")
def update_playground_session(
    id: int,
    data: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "admin" and current_user.id != id:
        raise HTTPException(403, "Admin profile required")
    u = db.query(User).filter(User.id == id, User.is_deleted == False).first()
    if not u:
        raise HTTPException(404)
    u.playground_connected = bool(data.get("playground_connected", False))
    u.playground_connected_at = data.get("playground_connected_at") or datetime.utcnow()
    if "playground_session_path" in data:
        u.playground_session_path = data.get("playground_session_path")
    db.commit()
    db.refresh(u)
    create_log(db, "info", "Playground session updated", "user", u.id, user_id=u.id)
    return public_user(u)

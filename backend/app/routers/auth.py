from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.config import BACKEND_DIR, resolve_backend_path, runtime_path, settings
from app.core.security import create_access_token, verify_password
from app.db.session import get_db
from app.models.user import DEFAULT_THEME_PREFERENCE, VALID_THEME_PREFERENCES, User
from app.routers.deps import get_current_user
from app.schemas.user import LoginReq, Token
from app.services.audit import create_log

router = APIRouter()

ALLOWED_PROFILE_PHOTO_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}


def user_response(user: User) -> dict:
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "network_id": user.network_id,
        "role": user.role,
        "status": user.status,
        "playground_connected": bool(user.playground_connected),
        "theme_preference": user_theme_preference(user),
        "has_profile_photo": bool(user.profile_photo_path),
        "profile_photo_updated_at": user.profile_photo_updated_at,
        "created_at": user.created_at,
        "last_login_at": user.last_login_at,
    }


def user_theme_preference(user: User) -> str:
    value = str(getattr(user, "theme_preference", "") or "").strip().lower()
    return value if value in VALID_THEME_PREFERENCES else DEFAULT_THEME_PREFERENCE


def normalize_theme_preference(value: str) -> str:
    text = str(value or "").strip().lower()
    if text not in VALID_THEME_PREFERENCES:
        raise HTTPException(status_code=422, detail="theme_preference must be 'light' or 'dark'")
    return text


def profile_photo_dir() -> Path:
    path = runtime_path("PROFILE_PHOTOS_PATH")
    path.mkdir(parents=True, exist_ok=True)
    return path


def stored_photo_path(user: User) -> Path | None:
    if not user.profile_photo_path:
        return None
    path = Path(user.profile_photo_path)
    if path.is_absolute():
        return path
    return resolve_backend_path(str(path))


def path_for_storage(path: Path) -> str:
    try:
        return path.resolve().relative_to(BACKEND_DIR.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def delete_existing_profile_photo(user: User) -> None:
    existing_path = stored_photo_path(user)
    if not existing_path or not existing_path.exists():
        return
    photo_root = profile_photo_dir().resolve()
    try:
        existing_path.resolve().relative_to(photo_root)
    except ValueError:
        return
    existing_path.unlink(missing_ok=True)


@router.post("/login", response_model=Token)
def login(req: LoginReq, db: Session = Depends(get_db)):
    username = req.username or req.login
    if not username:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="username or login is required")

    user = db.query(User).filter(
        (User.network_id == username) | (User.email == username),
        User.is_deleted == False
    ).first()

    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    access_token = create_access_token(data={"sub": user.network_id})
    return {"access_token": access_token, "token_type": "bearer", "user": user_response(user)}


@router.get("/me")
def get_me(current_user: User = Depends(get_current_user)):
    return {"user": user_response(current_user)}


@router.put("/me")
def update_me(data: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    for field in ["name", "email", "playground_session_path"]:
        if field in data:
            setattr(current_user, field, data[field])
    if "theme_preference" in data:
        current_user.theme_preference = normalize_theme_preference(data["theme_preference"])
    db.commit()
    db.refresh(current_user)
    return {"user": user_response(current_user)}


@router.post("/me/photo")
def upload_profile_photo(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    mime_type = (file.content_type or "").split(";", 1)[0].strip().lower()
    extension = ALLOWED_PROFILE_PHOTO_TYPES.get(mime_type)
    if not extension:
        raise HTTPException(status_code=422, detail="Formato inválido. Use PNG, JPG ou WEBP.")

    max_bytes = int(settings.PROFILE_PHOTO_MAX_BYTES or (2 * 1024 * 1024))
    content = file.file.read(max_bytes + 1)
    if not content:
        raise HTTPException(status_code=422, detail="Arquivo de imagem vazio.")
    if len(content) > max_bytes:
        raise HTTPException(status_code=413, detail=f"Imagem maior que o limite de {max_bytes} bytes.")

    timestamp = datetime.utcnow()
    target_path = profile_photo_dir() / f"user_{current_user.id}_{timestamp:%Y%m%d%H%M%S%f}{extension}"
    target_path.write_bytes(content)

    delete_existing_profile_photo(current_user)
    current_user.profile_photo_path = path_for_storage(target_path)
    current_user.profile_photo_mime_type = mime_type
    current_user.profile_photo_updated_at = timestamp
    db.commit()
    db.refresh(current_user)
    create_log(db, "info", "Profile photo updated", "user", current_user.id, user_id=current_user.id)
    return {"status": "photo_saved", "user": user_response(current_user)}


@router.get("/me/photo")
def get_profile_photo(current_user: User = Depends(get_current_user)):
    photo_path = stored_photo_path(current_user)
    if not photo_path or not photo_path.exists():
        raise HTTPException(status_code=404, detail="Foto de perfil não encontrada.")
    return FileResponse(
        photo_path,
        media_type=current_user.profile_photo_mime_type or "application/octet-stream",
        filename=photo_path.name,
    )


@router.post("/logout")
def logout():
    return {"status": "ok"}

from secrets import compare_digest

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from jose import jwt, JWTError

from app.db.session import get_db
from app.core.config import settings
from app.models.user import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")
optional_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

LOCAL_USER_NETWORK_ID = "LOCAL_OPERATOR"
LOCAL_USER_EMAIL = "local.operator@stellantis.local"


def get_or_create_local_user(db: Session) -> User:
    user = db.query(User).filter(
        User.is_deleted == False,
        User.status == "active",
        User.role == "admin",
    ).order_by(User.id.asc()).first()
    if user:
        return user

    user = db.query(User).filter(User.network_id == LOCAL_USER_NETWORK_ID).first()
    if user:
        user.name = user.name or "Operador Local Automation HUB"
        user.email = user.email or LOCAL_USER_EMAIL
        user.role = "admin"
        user.status = "active"
        user.is_deleted = False
    else:
        user = User(
            name="Operador Local Automation HUB",
            email=LOCAL_USER_EMAIL,
            network_id=LOCAL_USER_NETWORK_ID,
            role="admin",
            status="active",
            password_hash="",
        )
        db.add(user)
    db.commit()
    db.refresh(user)
    return user


def user_from_token(db: Session, token: str) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        subject: str = payload.get("sub")
        if subject is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    user_query = db.query(User).filter(User.is_deleted == False)
    if str(subject).isdigit():
        user = user_query.filter(User.id == int(subject)).first()
    else:
        user = user_query.filter((User.network_id == subject) | (User.email == subject)).first()
    if user is None:
        raise credentials_exception
    if user.is_deleted or user.status != "active":
        raise HTTPException(status_code=400, detail="Inactive user")
    return user


def get_current_user(db: Session = Depends(get_db), token: str | None = Depends(optional_oauth2_scheme)):
    if settings.AUTH_DISABLED:
        return get_or_create_local_user(db)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user_from_token(db, token)


def get_optional_current_user(db: Session = Depends(get_db), token: str | None = Depends(optional_oauth2_scheme)):
    if settings.AUTH_DISABLED:
        return get_or_create_local_user(db)
    if not token:
        return None
    return user_from_token(db, token)


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin profile required")
    return current_user


def require_agent_or_user(
    db: Session = Depends(get_db),
    token: str | None = Depends(optional_oauth2_scheme),
    x_agent_token: str | None = Header(default=None, alias="X-Agent-Token"),
):
    if x_agent_token and compare_digest(x_agent_token, settings.AGENT_SHARED_TOKEN):
        return {"kind": "agent"}
    if settings.AUTH_DISABLED:
        return get_or_create_local_user(db)
    if token:
        return user_from_token(db, token)
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Agent token or user bearer token required",
        headers={"WWW-Authenticate": "Bearer"},
    )

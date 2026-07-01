from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class UserBase(BaseModel):
    name: str
    email: str
    network_id: str
    role: str
    status: str

class UserCreate(UserBase):
    password: str

class UserOut(UserBase):
    id: int
    playground_connected: bool
    theme_preference: str = "light"
    has_profile_photo: bool = False
    profile_photo_updated_at: Optional[datetime] = None
    created_at: datetime
    
    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str
    user: UserOut

class LoginReq(BaseModel):
    username: Optional[str] = None
    login: Optional[str] = None
    password: str

"""
Authentication and user models for the API.
"""
from typing import Optional
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class Token(BaseModel):
    """Token schema"""

    access_token: str
    token_type: str


class TokenPayload(BaseModel):
    """Token payload schema"""

    sub: Optional[str] = None
    exp: Optional[int] = None


class UserBase(BaseModel):
    """Base user schema"""

    email: Optional[EmailStr] = None
    full_name: Optional[str] = None
    is_active: Optional[bool] = True
    is_superuser: Optional[bool] = False


class UserCreate(UserBase):
    """User creation schema"""

    email: EmailStr
    full_name: str
    password: str = Field(
        ..., min_length=8, description="Password must be at least 8 characters"
    )


class UserUpdate(UserBase):
    """User update schema"""

    password: Optional[str] = Field(
        None, min_length=8, description="Password must be at least 8 characters"
    )


class UserRead(UserBase):
    """User schema (returned to client)"""

    id: str
    email: EmailStr
    full_name: str
    is_active: bool
    is_superuser: bool
    created_at: datetime
    last_login: Optional[datetime] = None

    model_config = {"from_attributes": True}


class UserInDB(UserRead):
    """User schema in storage (not returned to client)"""

    hashed_password: str
    updated_at: datetime


class UserProfile(BaseModel):
    """User profile with storage statistics"""

    user_id: str
    document_count: int = 0
    storage_used: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}


class LoginRequest(BaseModel):
    """Login request schema"""

    email: EmailStr
    password: str


class RegisterRequest(BaseModel):
    """Registration request schema"""

    email: EmailStr
    full_name: str
    password: str = Field(
        ...,
        min_length=8,
        description="Password must be at least 8 characters with 1 uppercase letter and 1 digit",
    )
    confirm_password: str

    def validate_passwords_match(self):
        """Validate that passwords match"""
        if self.password != self.confirm_password:
            raise ValueError("Passwords do not match")
        return self

    def validate_password_strength(self):
        """Validate password strength requirements"""
        import re

        if len(self.password) < 8:
            raise ValueError("Password must be at least 8 characters long")

        if not re.search(r"[A-Z]", self.password):
            raise ValueError("Password must contain at least one uppercase letter")

        if not re.search(r"[a-z]", self.password):
            raise ValueError("Password must contain at least one lowercase letter")

        if not re.search(r"\d", self.password):
            raise ValueError("Password must contain at least one digit")

        return self

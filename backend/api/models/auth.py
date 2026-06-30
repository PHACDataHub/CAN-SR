"""
Authentication and user models for the API.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel
from pydantic import EmailStr
from pydantic import Field


class Token(BaseModel):
    """Token schema"""

    access_token: str
    token_type: str


class TokenPayload(BaseModel):
    """Token payload schema"""

    sub: str | None = None
    exp: int | None = None


class UserBase(BaseModel):
    """Base user schema"""

    email: EmailStr | None = None
    full_name: str | None = None
    is_active: bool | None = True
    is_superuser: bool | None = False


class UserCreate(UserBase):
    """User creation schema"""

    email: EmailStr
    full_name: str
    password: str = Field(
        ..., min_length=8, description='Password must be at least 8 characters',
    )


class UserUpdate(UserBase):
    """User update schema"""

    password: str | None = Field(
        None, min_length=8, description='Password must be at least 8 characters',
    )


class UserRead(UserBase):
    """User schema (returned to client)"""

    id: str
    email: EmailStr
    full_name: str
    is_active: bool
    is_superuser: bool
    created_at: datetime
    last_login: datetime | None = None

    model_config = {'from_attributes': True}


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

    model_config = {'from_attributes': True}


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
        description='Password must be at least 8 characters with 1 uppercase letter and 1 digit',
    )
    confirm_password: str

    def validate_passwords_match(self):
        """Validate that passwords match"""
        if self.password != self.confirm_password:
            raise ValueError('Passwords do not match')
        return self

    def validate_password_strength(self):
        """Validate password strength requirements"""
        import re

        if len(self.password) < 8:
            raise ValueError('Password must be at least 8 characters long')

        if not re.search(r'[A-Z]', self.password):
            raise ValueError(
                'Password must contain at least one uppercase letter',
            )

        if not re.search(r'[a-z]', self.password):
            raise ValueError(
                'Password must contain at least one lowercase letter',
            )

        if not re.search(r'\d', self.password):
            raise ValueError('Password must contain at least one digit')

        return self

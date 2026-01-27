from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

from .config import settings
from ..services.user_db import user_db_service
from ..models.auth import UserRead, UserCreate, UserUpdate

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# OAuth2
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/token")


def create_access_token(
    data: Dict[str, Any], expires_delta: Optional[timedelta] = None
) -> str:
    """Create a JWT access token"""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a hash"""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Get password hash"""
    return pwd_context.hash(password)


async def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    """Get a user by email"""
    if not user_db_service:
        return None

    return await user_db_service.get_user_by_email(email)


async def get_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    """Get a user by ID"""
    if not user_db_service:
        return None

    return await user_db_service.get_user_by_id(user_id)


async def create_user(user_data: UserCreate) -> Optional[UserRead]:
    """Create a new user"""
    if not user_db_service:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="User registration is not available without Azure Storage configuration",
        )

    return await user_db_service.create_user(user_data)


async def update_user(user_id: str, user_in: UserUpdate) -> Optional[UserRead]:
    """Update a user"""
    if not user_db_service:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="User operations are not available without Azure Storage configuration",
        )

    update_data = user_in.model_dump(exclude_unset=True)

    if "password" in update_data and update_data["password"]:
        update_data["hashed_password"] = get_password_hash(update_data.pop("password"))

    updated_user_data = await user_db_service.update_user(user_id, update_data)
    if not updated_user_data:
        return None

    return UserRead.model_validate(updated_user_data)


async def authenticate_user(email: str, password: str, sso: bool = False) -> Optional[Dict[str, Any]]:
    """Authenticate a user"""
    if not user_db_service:
        user = await get_user_by_email(email)
        if not user:
            return None
        if not verify_password(password, user["hashed_password"]):
            return None
        return user

    return await user_db_service.authenticate_user(email, password, sso=sso)


async def get_current_user(token: str = Depends(oauth2_scheme)) -> Dict[str, Any]:
    """Get the current user from a JWT token"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        print(payload)
        user_id = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    # Try to get user by ID first, then by email for backward compatibility
    user = await get_user_by_id(user_id)
    if user is None:
        user = await get_user_by_email(user_id)  # Fallback for old tokens

    if user is None:
        raise credentials_exception

    return user


async def get_current_active_user(
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Check if the current user is active"""
    if not current_user.get("is_active", False):
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user

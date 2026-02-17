from datetime import timedelta
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from starlette.requests import Request as StarletteRequest
from authlib.integrations.starlette_client import OAuth
from fastapi.responses import RedirectResponse

from ..models.auth import (
    Token,
    UserCreate,
    UserRead,
    UserUpdate,
    LoginRequest,
    RegisterRequest,
    UserProfile,
)
from ..core.security import (
    authenticate_user,
    create_access_token,
    get_current_active_user,
    create_user,
    get_user_by_email,
    update_user,
)
from ..core.config import settings
from ..services.storage import storage_service

router = APIRouter()

# Authlib OAuth client for Microsoft
oauth = OAuth()
oauth.register(
    name="microsoft",
    client_id=settings.OAUTH_CLIENT_ID,
    client_secret=settings.OAUTH_CLIENT_SECRET,
    server_metadata_url=f"https://login.microsoftonline.com/42fd9015-de4d-4223-a368-baeacab48927/v2.0/.well-known/openid-configuration",
    client_kwargs={"scope": "openid profile email"},
)

@router.post("/token", response_model=Token)
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
) -> Any:
    """
    OAuth2 compatible token login, get an access token for future requests.
    """
    user = await authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # User collections will be created when processing files

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user["id"]},
        expires_delta=access_token_expires,  # Use user ID instead of email
    )

    return {"access_token": access_token, "token_type": "Bearer"}


@router.post("/login", response_model=Token)
async def login(login_data: LoginRequest) -> Any:
    """
    Login with email and password (JSON format).
    """
    user = await authenticate_user(login_data.email, login_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user["id"]}, expires_delta=access_token_expires
    )

    return {"access_token": access_token, "token_type": "Bearer"}

@router.get("/microsoft-sso")
async def login_microsoft_sso(request: StarletteRequest, lang: str):
    """
    Start Microsoft OAuth2 flow by redirecting the user to Microsoft login.
    """
    request.session["lang"] = lang
    return await oauth.microsoft.authorize_redirect(request, f"{settings.API_URL}/api/auth/sso-authorize")

@router.get("/sso-authorize")
async def microsoft_authorize(request: StarletteRequest):
    """
    OAuth2 callback handler (stub): exchanges code for tokens and returns user info.
    """
    try:
        token = await oauth.microsoft.authorize_access_token(request)
        userinfo = token.get("userinfo")
        lang = request.session.get("lang", "en")

        user = await authenticate_user(userinfo.get("email").lower(), "", sso=True)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
            )
        access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={"sub": user["id"]}, expires_delta=access_token_expires
        )

        return RedirectResponse(
            url=f"{settings.WEB_APP_URL}/{lang}/sso-login?access_token={access_token}&token_type=Bearer"
        )
    except Exception:
        # Fallback for any unexpected errors during the OAuth callback
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error during Microsoft OAuth callback",
        )

@router.post("/register", response_model=UserRead)
async def register_user(register_data: RegisterRequest) -> Any:
    """
    Register a new user.
    """
    # Validate passwords match and strength
    try:
        register_data.validate_passwords_match()
        register_data.validate_password_strength()
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    # Check if user already exists
    existing_user = await get_user_by_email(register_data.email)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User with this email already exists",
        )

    # Create user data
    user_create = UserCreate(
        email=register_data.email,
        full_name=register_data.full_name,
        password=register_data.password,
    )

    # Create new user
    user = await create_user(user_create)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create user",
        )

    return user


@router.get("/me", response_model=UserRead)
async def read_users_me(
    current_user: Dict[str, Any] = Depends(get_current_active_user),
) -> Any:
    """
    Get current user information.
    """
    return UserRead(
        id=current_user["id"],
        email=current_user["email"],
        full_name=current_user["full_name"],
        is_active=current_user["is_active"],
        is_superuser=current_user.get("is_superuser", False),
        created_at=current_user["created_at"],
        last_login=current_user.get("last_login"),
    )


@router.get("/me/profile", response_model=UserProfile)
async def get_user_profile(
    current_user: Dict[str, Any] = Depends(get_current_active_user),
) -> Any:
    """
    Get current user's profile with storage statistics.
    """
    if not storage_service:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Storage service not available",
        )

    profile = await storage_service.get_user_profile(current_user["id"])
    if not profile:
        # Create default profile if it doesn't exist
        profile = {
            "user_id": current_user["id"],
            "document_count": 0,
            "storage_used": 0,
            "created_at": current_user["created_at"],
        }
        await storage_service.save_user_profile(current_user["id"], profile)

    return UserProfile(**profile)


@router.post("/logout")
async def logout(_: Dict[str, Any] = Depends(get_current_active_user)) -> Any:
    """
    Logout (client should discard the token).
    Note: We still validate the token but don't use the user data.
    """
    return {"message": "Successfully logged out"}


@router.get("/validate-token")
async def validate_token(
    current_user: Dict[str, Any] = Depends(get_current_active_user),
) -> Any:
    """
    Validate if the current token is still valid.
    """
    return {
        "valid": True,
        "user_id": current_user["id"],
        "email": current_user["email"],
    }


@router.put("/me", response_model=UserRead)
async def update_user_me(
    user_in: UserUpdate,
    current_user: Dict[str, Any] = Depends(get_current_active_user),
) -> Any:
    """
    Update own user information.
    """
    user = await update_user(current_user["id"], user_in)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found or failed to update.",
        )
    return user

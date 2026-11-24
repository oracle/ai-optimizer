"""Authentication and local-user administration endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from server.app.auth import repository
from server.app.auth.dependencies import AUTHORITY_STATE, require_admin
from server.app.auth.local import (
    change_database_password,
    login_database_user,
    logout_database_session,
)
from server.app.auth.models import AuthContext, Principal
from server.app.auth.policy import enforce_route_policy
from server.app.auth.schemas import (
    AuthConfigResponse,
    DatabaseLoginRequest,
    DatabasePasswordChangeRequest,
    DatabaseUserResponse,
    LoginResponse,
    MessageResponse,
    PasswordResetRequest,
    UserCreateRequest,
    UserUpdateRequest,
)
from server.app.auth.service import AuthenticationError
from server.app.auth.users import (
    create_member,
    database_user_status,
    require_local_user_management,
    reset_member_password,
    update_member,
)
from server.app.core.settings import settings

router = APIRouter(prefix="/auth", tags=["Authentication"])
users_router = APIRouter(prefix="/users", tags=["Authentication Users"])


def _require_database_mode() -> None:
    if settings.auth_mode == "oidc":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Database authentication is unavailable")
    if not AUTHORITY_STATE.ready:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication authority is unavailable",
        )


def _login_failure() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Database credentials are invalid or the account is unavailable",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _user_response(user, account_status: str) -> DatabaseUserResponse:
    if user.database_username is None:
        raise RuntimeError("Database user mapping is unavailable")
    return DatabaseUserResponse(
        user_id=user.user_id,
        username=user.username,
        database_username=user.database_username,
        display_name=user.display_name,
        email=user.email,
        role=user.role,
        account_status=account_status,
    )


@router.get("/config", response_model=AuthConfigResponse)
async def auth_config() -> AuthConfigResponse:
    """Return safe information needed to select the sign-in flow."""
    if settings.auth_mode == "oidc":
        return AuthConfigResponse(
            mode="oidc",
            credential_authority="oidc",
            login_method="authorization_code",
        )
    return AuthConfigResponse(
        mode=settings.auth_mode,
        credential_authority="oracle_database",
        login_method="database_password",
    )


@router.post("/login", response_model=LoginResponse)
async def login(body: DatabaseLoginRequest, request: Request) -> LoginResponse:
    _require_database_mode()
    try:
        session, principal = await login_database_user(
            body.username,
            body.password.get_secret_value(),
            request.client.host if request.client else None,
        )
    except AuthenticationError:
        raise _login_failure() from None
    return LoginResponse(access_token=session.token, expires=session.expires, principal=principal)


@router.post("/password-change", response_model=MessageResponse)
async def password_change(body: DatabasePasswordChangeRequest) -> MessageResponse:
    _require_database_mode()
    try:
        await change_database_password(
            body.username,
            body.current_password.get_secret_value(),
            body.new_password.get_secret_value(),
        )
    except AuthenticationError:
        raise _login_failure() from None
    return MessageResponse(message="Database password changed")


@router.post("/logout", response_model=MessageResponse)
async def logout(context: AuthContext = Depends(enforce_route_policy)) -> MessageResponse:
    if context.principal.auth_source == "database_end_user":
        await logout_database_session(context.credential.value)
    return MessageResponse(message="Signed out")


@router.get("/me", response_model=Principal)
async def me(context: AuthContext = Depends(enforce_route_policy)) -> Principal:
    return context.principal


@users_router.get("", response_model=list[DatabaseUserResponse])
async def list_users(_context: AuthContext = Depends(require_admin)) -> list[DatabaseUserResponse]:
    try:
        await require_local_user_management()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    users = await repository.list_database_users()
    return [_user_response(user, await database_user_status(user)) for user in users]


@users_router.post("", response_model=DatabaseUserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreateRequest,
    _context: AuthContext = Depends(require_admin),
) -> DatabaseUserResponse:
    try:
        user = await create_member(
            body.username,
            body.temporary_password.get_secret_value(),
            body.display_name,
            body.email,
        )
        return _user_response(user, await database_user_status(user))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@users_router.patch("/{user_id}", response_model=DatabaseUserResponse)
async def patch_user(
    user_id: UUID,
    body: UserUpdateRequest,
    _context: AuthContext = Depends(require_admin),
) -> DatabaseUserResponse:
    current = await repository.get_user_by_id(user_id)
    if current is None:
        raise HTTPException(status_code=404, detail="Authentication member was not found")
    display_name = body.display_name if "display_name" in body.model_fields_set else current.display_name
    email = body.email if "email" in body.model_fields_set else current.email
    try:
        user = await update_member(user_id, body.account_locked, display_name, email)
        return _user_response(user, await database_user_status(user))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


@users_router.post("/{user_id}/password-reset", response_model=MessageResponse)
async def reset_user_password(
    user_id: UUID,
    body: PasswordResetRequest,
    _context: AuthContext = Depends(require_admin),
) -> MessageResponse:
    try:
        await reset_member_password(user_id, body.temporary_password.get_secret_value())
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    return MessageResponse(message="Temporary database password set")

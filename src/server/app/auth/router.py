"""Public authentication discovery endpoint."""

from fastapi import APIRouter

from server.app.auth.schemas import AuthConfigResponse
from server.app.core.settings import settings

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.get("/config", response_model=AuthConfigResponse)
async def auth_config() -> AuthConfigResponse:
    """Return safe information needed to select the sign-in flow."""
    if settings.auth_mode == "oidc":
        return AuthConfigResponse(
            mode="oidc",
            credential_authority="oidc",
            login_method="authorization_code",
            provider_name=settings.oidc_provider_name,
        )
    return AuthConfigResponse(
        mode=settings.auth_mode,
        credential_authority="oracle_database",
        login_method="database_password",
    )

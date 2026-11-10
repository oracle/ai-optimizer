"""Public authentication API schemas."""

from pydantic import BaseModel

from server.app.auth.models import AuthMode


class AuthConfigResponse(BaseModel):
    mode: AuthMode
    credential_authority: str
    login_method: str
    provider_name: str | None = None

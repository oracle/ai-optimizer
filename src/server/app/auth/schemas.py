"""Public authentication API schemas."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, SecretStr, field_validator

from server.app.auth.models import AuthMode, AuthRole, Principal


class _PasswordValidationMixin(BaseModel):
    @field_validator(
        "password",
        "current_password",
        "new_password",
        check_fields=False,
    )
    @classmethod
    def validate_password(cls, value: SecretStr) -> SecretStr:
        if any(character in value.get_secret_value() for character in "\x00\n\r"):
            raise ValueError("Password must not contain control characters")
        return value


class DatabaseLoginRequest(_PasswordValidationMixin):
    username: str = Field(min_length=1, max_length=128)
    password: SecretStr


class DatabasePasswordChangeRequest(_PasswordValidationMixin):
    current_password: SecretStr
    new_password: SecretStr


class LoginResponse(BaseModel):
    access_token: str = Field(repr=False)
    token_type: Literal["bearer"] = "bearer"
    expires: datetime
    password_state: Literal["current"] = "current"
    principal: Principal


class UserCreateRequest(_PasswordValidationMixin):
    username: str = Field(min_length=1, max_length=128)
    password: SecretStr
    display_name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=320)


class UserUpdateRequest(BaseModel):
    account_locked: bool | None = None
    display_name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=320)


class PasswordResetRequest(_PasswordValidationMixin):
    password: SecretStr


class DatabaseUserResponse(BaseModel):
    user_id: UUID
    username: str
    database_username: str
    display_name: str | None = None
    email: str | None = None
    role: AuthRole
    account_status: str


class MessageResponse(BaseModel):
    message: str


class AuthConfigResponse(BaseModel):
    mode: AuthMode
    credential_authority: str
    login_method: str

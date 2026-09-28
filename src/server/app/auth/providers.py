"""GitHub OAuth and external OpenID Connect identity-source adapters."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
import jwt
from jwt import PyJWKClient

from server.app.auth.models import AuthenticatedIdentity
from server.app.auth.tokens import pkce_challenge


class ProviderError(ValueError):
    """An upstream provider could not establish an authorized identity."""


@dataclass(frozen=True, slots=True)
class GitHubProvider:
    """OAuth adapter that uses GitHub's immutable numeric user ID."""

    client_id: str
    client_secret: str
    base_url: str
    allowed_users: frozenset[str]
    allowed_organizations: frozenset[str]
    administrator_users: frozenset[str]
    administrator_teams: frozenset[str]

    @property
    def issuer(self) -> str:
        return self.base_url.rstrip("/")

    @property
    def _api_url(self) -> str:
        if self.issuer == "https://github.com":
            return "https://api.github.com"
        return f"{self.issuer}/api/v3"

    def authorization_url(self, *, redirect_uri: str, state: str, verifier: str) -> str:
        scopes = ["read:user", "user:email"]
        if self.allowed_organizations or self.administrator_teams:
            scopes.append("read:org")
        query = urlencode(
            {
                "client_id": self.client_id,
                "redirect_uri": redirect_uri,
                "state": state,
                "scope": " ".join(scopes),
                "code_challenge": pkce_challenge(verifier),
                "code_challenge_method": "S256",
            }
        )
        return f"{self.issuer}/login/oauth/authorize?{query}"

    async def complete(self, *, code: str, verifier: str, redirect_uri: str) -> AuthenticatedIdentity:
        async with httpx.AsyncClient(timeout=10) as client:
            token_response = await client.post(
                f"{self.issuer}/login/oauth/access_token",
                headers={"Accept": "application/json"},
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "code_verifier": verifier,
                },
            )
            if token_response.is_error:
                raise ProviderError("GitHub token exchange failed")
            token_payload = token_response.json()
            access_token = token_payload.get("access_token") if isinstance(token_payload, dict) else None
            if not isinstance(access_token, str) or not access_token:
                raise ProviderError("GitHub did not return an access token")
            headers = {"Accept": "application/vnd.github+json", "Authorization": f"Bearer {access_token}"}
            user_response = await client.get(f"{self._api_url}/user", headers=headers)
            if user_response.is_error:
                raise ProviderError("GitHub user lookup failed")
            user = user_response.json()
            user_id = user.get("id") if isinstance(user, dict) else None
            if not isinstance(user_id, int):
                raise ProviderError("GitHub did not return a numeric user ID")
            subject = str(user_id)
            organizations, teams = await self._organizations_and_teams(client, headers)
        allowed = subject in self.allowed_users or bool(organizations.intersection(self.allowed_organizations))
        if not allowed:
            raise ProviderError("GitHub account is not authorized for this deployment")
        roles = {"aio.user"}
        if subject in self.administrator_users or teams.intersection(self.administrator_teams):
            roles.add("aio.admin")
        display_name = user.get("name") or user.get("login") or subject
        email = user.get("email")
        return AuthenticatedIdentity(
            issuer=self.issuer,
            subject=subject,
            display_name=display_name if isinstance(display_name, str) else subject,
            email=email if isinstance(email, str) else None,
            roles=frozenset(roles),
        )

    async def _organizations_and_teams(
        self, client: httpx.AsyncClient, headers: dict[str, str]
    ) -> tuple[set[str], set[str]]:
        if not self.allowed_organizations and not self.administrator_teams:
            return set(), set()
        response = await client.get(f"{self._api_url}/user/teams", headers=headers)
        if response.is_error:
            raise ProviderError("GitHub organization lookup failed")
        teams_payload = response.json()
        organizations: set[str] = set()
        teams: set[str] = set()
        if isinstance(teams_payload, list):
            for team in teams_payload:
                if not isinstance(team, dict):
                    continue
                organization = team.get("organization")
                org_login = organization.get("login") if isinstance(organization, dict) else None
                slug = team.get("slug")
                if isinstance(org_login, str):
                    organizations.add(org_login)
                    if isinstance(slug, str):
                        teams.add(f"{org_login}/{slug}")
        return organizations, teams


@dataclass(frozen=True, slots=True)
class OidcProvider:
    """OpenID Connect relying-party adapter for a standards-compliant IdP."""

    issuer: str
    client_id: str
    client_secret: str
    scopes: tuple[str, ...]
    signing_algorithms: tuple[str, ...]
    roles_claim: str
    allowed_claim_values: frozenset[str]
    administrator_claim_values: frozenset[str]

    async def authorization_url(self, *, redirect_uri: str, state: str, nonce: str, verifier: str) -> str:
        metadata = await self._metadata()
        endpoint = metadata.get("authorization_endpoint")
        if not isinstance(endpoint, str):
            raise ProviderError("OIDC provider has no authorization endpoint")
        query = urlencode(
            {
                "response_type": "code",
                "client_id": self.client_id,
                "redirect_uri": redirect_uri,
                "scope": " ".join(self.scopes),
                "state": state,
                "nonce": nonce,
                "code_challenge": pkce_challenge(verifier),
                "code_challenge_method": "S256",
            }
        )
        return f"{endpoint}?{query}"

    async def complete(self, *, code: str, verifier: str, nonce: str, redirect_uri: str) -> AuthenticatedIdentity:
        metadata = await self._metadata()
        token_endpoint = metadata.get("token_endpoint")
        jwks_uri = metadata.get("jwks_uri")
        if not isinstance(token_endpoint, str) or not isinstance(jwks_uri, str):
            raise ProviderError("OIDC provider metadata is incomplete")
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                token_endpoint,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "code_verifier": verifier,
                },
            )
        if response.is_error:
            raise ProviderError("OIDC token exchange failed")
        payload = response.json()
        id_token = payload.get("id_token") if isinstance(payload, dict) else None
        if not isinstance(id_token, str):
            raise ProviderError("OIDC provider did not return an ID token")
        try:
            key = PyJWKClient(jwks_uri).get_signing_key_from_jwt(id_token).key
            claims = jwt.decode(
                id_token,
                key,
                algorithms=list(self.signing_algorithms),
                audience=self.client_id,
                issuer=self.issuer.rstrip("/"),
                options={"require": ["exp", "iat", "sub", "nonce"]},
            )
        except jwt.PyJWTError as exc:
            raise ProviderError("OIDC ID token validation failed") from exc
        if claims.get("nonce") != nonce:
            raise ProviderError("OIDC ID token nonce did not match")
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            raise ProviderError("OIDC ID token has no subject")
        claim_roles = _claim_values(claims.get(self.roles_claim))
        if self.allowed_claim_values and not claim_roles.intersection(self.allowed_claim_values):
            raise ProviderError("OIDC account is not authorized for this deployment")
        roles = {"aio.user"}
        if claim_roles.intersection(self.administrator_claim_values):
            roles.add("aio.admin")
        name = claims.get("name") or claims.get("preferred_username") or subject
        email = claims.get("email")
        return AuthenticatedIdentity(
            issuer=self.issuer.rstrip("/"),
            subject=subject,
            display_name=name if isinstance(name, str) else subject,
            email=email if isinstance(email, str) else None,
            roles=frozenset(roles),
        )

    async def _metadata(self) -> dict[str, object]:
        url = f"{self.issuer.rstrip('/')}/.well-known/openid-configuration"
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url)
        if response.is_error:
            raise ProviderError("OIDC discovery document could not be retrieved")
        metadata = response.json()
        if not isinstance(metadata, dict) or metadata.get("issuer", "").rstrip("/") != self.issuer.rstrip("/"):
            raise ProviderError("OIDC discovery issuer did not match configuration")
        return metadata


def _claim_values(value: object) -> set[str]:
    """Normalize a role or group claim into a set of claim values."""
    if isinstance(value, str):
        return set(value.replace(",", " ").split())
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return set(value)
    return set()

# End-User Authentication and Authorization Plan

This plan establishes multi-user identity for the Streamlit Client, REST API,
MCP server, and Oracle AI Agent Memory. It covers three supported authentication
sources:

1. Local accounts for workstation development and tests.
2. GitHub OAuth for social login.
3. An external OpenID Connect provider, validated with OCI IAM Identity Domains.

Local, GitHub, and external OIDC must produce the same application principal,
session ownership, authorization decisions, and Agent Memory `user_id`.

## Architecture

Streamlit `st.login()` is the browser contract. It requires an OIDC provider and
uses the returned ID token to populate `st.user`. AI Optimizer will expose an
embedded OIDC gateway to Streamlit in every authentication mode.

```text
Streamlit, REST, and MCP clients
                |
                | OIDC authorization code + PKCE
                v
       AI Optimizer auth gateway
          |         |         |
          |         |         +-- external OIDC
          |         +------------ GitHub OAuth
          +---------------------- local accounts
                |
                v
      principal_id + access token
                |
                v
 REST/MCP authorization and Agent Memory user_id
```

The gateway is part of the Server deployment. It is an OIDC provider to AI
Optimizer clients and an OAuth/OIDC client to an external authentication source.
One authentication source is active per deployment.

References:

- [Streamlit `st.login`](https://docs.streamlit.io/develop/api-reference/user/st.login)
- [Streamlit `st.logout`](https://docs.streamlit.io/develop/api-reference/user/st.logout)
- [GitHub OAuth authorization](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps)
- [OCI IAM Identity Domains OpenID discovery](https://docs.oracle.com/en/cloud/paas/iam-domains-rest-api/api-discovery-openid-discovery-docs.html)
- [Oracle AI Agent Memory security](https://docs.oracle.com/en/database/oracle/agent-memory/26.6/guide/security.html)

## Identity Contract

Persist an application principal separately from provider identities:

```text
aio_principals
  principal_id     immutable application user ID
  display_name     current profile value
  email            current profile value
  active           application access switch
  created
  updated

aio_principal_identities
  principal_id     FK to aio_principals
  issuer           authentication-source namespace
  subject          immutable source identifier
  last_login
  UNIQUE (issuer, subject)

aio_principal_roles
  principal_id     FK to aio_principals
  role              application role
  source            local or provider mapping
  UNIQUE (principal_id, role, source)
```

`principal_id` is a UUID string and is the only value passed to Agent Memory as
`user_id`. Provider claims, email addresses, usernames, client IDs, and working
session IDs are never accepted as memory ownership input.

Provider identity keys are:

- Local: an installation-scoped issuer and the local account UUID.
- GitHub: the configured GitHub instance URL and the numeric GitHub user ID as
  a string.
- External OIDC: the validated upstream `iss` and `sub` pair.

Do not link identities by email. Account linking requires an authenticated,
audited flow and is outside the first implementation.

Replace the current `Principal` transport identity with:

```text
Principal
  principal_id
  roles
  authentication_source
```

Provider identifiers remain in the principal directory for audit and account
management. Resource ownership uses `principal_id`.

## Client and Token Contract

The embedded gateway implements:

- `/.well-known/openid-configuration`
- `/authorize`
- `/token`
- `/userinfo`
- `/jwks.json`
- `/logout`
- the existing first-party MCP client metadata document

Authorization uses code flow with PKCE. Redirect URI, client ID, nonce, state,
scope, and PKCE values are validated and authorization codes are short-lived,
single-use records.

The gateway issues:

- A signed ID token for Streamlit. Its `sub` is `principal_id` and its audience
  is the Streamlit client ID.
- An opaque access token for REST and MCP. CORE stores only its digest, client,
  principal, scopes, expiry, and revocation state.

The API middleware resolves the opaque token through CORE on each request and
loads the current principal status and roles. This provides immediate account,
role, and token revocation without requiring an upstream token format.

Initial lifetimes:

- Authorization code: 5 minutes.
- Access token: 15 minutes.
- Gateway login session: 8 hours.

Streamlit exposes the access token through `st.user.tokens`. When it expires,
the Client starts `st.login()` again. The gateway login session normally makes
this a redirect-only renewal. The discovery document publishes
`end_session_endpoint`; `st.logout()` revokes the gateway login session before
returning to the Client.

Upstream access and refresh tokens are used during authentication and discarded
after identity and mapped roles are resolved. A future provider requiring
durable delegated API access must define separate encrypted credential storage.

## Authorization Contract

Authentication establishes a principal. Authorization uses AI Optimizer roles.
The initial roles are:

- `aio.user`: access to the user's own sessions, artifacts, and memories.
- `aio.admin`: management of the shared catalog and authentication settings.

Administrator status does not grant cross-user memory access. Any future support
or compliance workflow that reads another user's memory requires a separate
permission, endpoint, and audit event.

The Server derives `principal_id` before routing a request. It strips or ignores
caller-supplied ownership fields and passes the authenticated principal to REST,
MCP, chat runtime, testbed, and Agent Memory service boundaries.

Principal-authenticated operation requires an available CORE database. Auth
startup and request authentication fail closed when CORE is unavailable. The
shared API-key mode remains a single-principal compatibility mode and cannot
enable Agent Memory.

## Authentication Sources

### Local

Local mode provides multiple individual accounts without an external service.
It reuses the existing scrypt password hashing and login form behavior.

Implement these account operations in the administrative CLI:

- Bootstrap the first administrator once.
- Add and disable users.
- Set a password.
- Grant and revoke `aio.admin`.
- List users without password hashes.

Bootstrap configuration creates a missing administrator and leaves an existing
account unchanged. Password reset is an explicit CLI operation. Login attempts
use a bounded failure delay and generic error response.

Local mode uses the CORE database already required by Agent Memory. All-In-One
startup creates the Streamlit client secret and local bootstrap credential with
owner-only filesystem permissions.

### GitHub

GitHub mode implements GitHub's authorization-code flow with state and PKCE. The
gateway callback exchanges the code server-side, calls GitHub's authenticated
user endpoint, and resolves the numeric `id` as the provider subject.

Configuration supports:

- GitHub.com and a configurable GitHub Enterprise base URL.
- Allowed user IDs and organizations.
- Administrator user IDs and teams.
- Minimal scopes, adding `read:org` only when organization or team policy uses
  it.

The GitHub callback URL targets the auth gateway. Streamlit continues to use its
own `/oauth2callback` redirect URI with the embedded gateway.

The login transaction records the downstream Streamlit authorization request
and a separate upstream state, PKCE verifier, and expiry. It resumes the original
request only after the GitHub callback succeeds.

### External OIDC

External OIDC mode treats the gateway as a relying party. It discovers provider
metadata, starts authorization-code flow with state, nonce, and PKCE, and
validates the returned ID token's signature, algorithm, issuer, audience,
expiry, nonce, and subject. UserInfo is optional and may enrich display fields.

Configuration supports:

- Upstream issuer, client ID, client secret, and scopes.
- Allowed signing algorithms.
- A claim containing groups or roles.
- Claim values that grant application access and `aio.admin`.

The first live provider is OCI IAM Identity Domains. Register AI Optimizer as a
confidential application, use the gateway callback URI, and obtain endpoints
from the identity domain discovery document. Zitadel and Keycloak are expected
to work through the same adapter without provider-specific code.

## Configuration Model

Replace provider-specific downstream settings with shared gateway settings:

```text
AIO_AUTH_MODE=local|github|oidc
AIO_AUTH_ISSUER
AIO_AUTH_LISTEN_HOST
AIO_AUTH_LISTEN_PORT
AIO_AUTH_WEB_REDIRECT_URI
AIO_AUTH_WEB_CLIENT_SECRET
AIO_AUTH_ACCESS_TOKEN_MINUTES
AIO_AUTH_LOGIN_SESSION_HOURS
AIO_AUTH_ADMIN_CLAIM_VALUES
```

Local settings:

```text
AIO_AUTH_LOCAL_ADMIN_USERNAME
AIO_AUTH_LOCAL_ADMIN_PASSWORD
```

GitHub settings:

```text
AIO_AUTH_GITHUB_CLIENT_ID
AIO_AUTH_GITHUB_CLIENT_SECRET
AIO_AUTH_GITHUB_BASE_URL
AIO_AUTH_GITHUB_ALLOWED_USERS
AIO_AUTH_GITHUB_ALLOWED_ORGANIZATIONS
AIO_AUTH_GITHUB_ADMIN_USERS
AIO_AUTH_GITHUB_ADMIN_TEAMS
```

External OIDC settings:

```text
AIO_AUTH_OIDC_ISSUER
AIO_AUTH_OIDC_CLIENT_ID
AIO_AUTH_OIDC_CLIENT_SECRET
AIO_AUTH_OIDC_SCOPES
AIO_AUTH_OIDC_SIGNING_ALGORITHMS
AIO_AUTH_OIDC_ROLES_CLAIM
AIO_AUTH_OIDC_ALLOWED_CLAIM_VALUES
```

List values accept comma-separated or JSON-array environment values. Secrets
use existing secret wrappers and Helm Secret references.

Remove the external-resource-server meaning from
`AIO_AUTH_OIDC_AUDIENCE`, `AIO_AUTH_OIDC_REQUIRED_SCOPES`, and the unconditional
`at+jwt` validation. The external OIDC adapter validates an upstream ID token;
the Server validates an AI Optimizer opaque access token.

## Persistence Changes

Replace the `aio_dev_oidc_*` schema with provider-neutral auth tables:

- `aio_principals`
- `aio_principal_identities`
- `aio_principal_roles`
- `aio_local_accounts`
- `aio_auth_clients`
- `aio_auth_transactions`
- `aio_auth_codes`
- `aio_auth_login_sessions`
- `aio_auth_access_tokens`
- `aio_auth_signing_keys`

Change `aio_principal_sessions` and user-owned application tables to reference
`principal_id`. This includes testsets and future Agent Memory records. Add
foreign keys and indexes for principal ownership.

The current authentication work has not shipped as a production contract.
Replace its tables, settings, and generated secrets in the same change series;
do not add a compatibility layer for the experimental schema. Preserve unrelated
CORE data.

## Code Structure

Create a provider-neutral package:

```text
src/server/app/auth/
|-- models.py
|-- store.py
|-- service.py
|-- gateway.py
|-- tokens.py
`-- providers.py
```

Key interfaces:

```text
IdentityProvider.begin(transaction) -> local form or upstream redirect
IdentityProvider.complete(callback) -> AuthenticatedIdentity
PrincipalStore.resolve(identity) -> Principal
AccessTokenStore.resolve(token) -> Principal
```

Replace the experimental provider modules with this package. Keep protocol
validation in the gateway and provider-specific behavior in adapters.
`core/auth.py` becomes the transport middleware and contains no
provider-specific token parsing.

Update:

- `src/server/app/main.py` to start the gateway for every principal auth mode.
- `src/entrypoint.py` to generate Streamlit OIDC configuration for every mode.
- `src/client/app/main.py` to retain the `st.login`, `st.user`, and `st.logout`
  flow.
- `src/client/app/core/api.py` to forward the opaque access token and renew on
  an authenticated 401 rather than decoding JWT claims.
- REST and MCP dependencies to consume the resolved `Principal`.
- Session and testbed stores to use `principal_id` ownership.
- Helm values, schemas, Secrets, Deployments, Services, and ingress templates
  for the shared gateway and selected provider.

## Delivery Plan

### Phase 1: Domain and Store

- Add principal, identity, role, client, transaction, code, session, token, and
  local-account models.
- Add Oracle-backed stores and schema DDL.
- Change session ownership to `principal_id` and make persistence fail closed.
- Add principal resolution and authorization dependencies.

Exit gate: two principals cannot claim the same working session or testset, and
disabled principals fail authentication immediately.

### Phase 2: Embedded Gateway and Local Mode

- Extract the reusable authorization-code, PKCE, ID-token, discovery, JWKS,
  UserInfo, and logout behavior from the development provider.
- Issue opaque access tokens and resolve them in middleware.
- Implement local login and administrative CLI operations.
- Update All-In-One startup and generated Streamlit secrets.

Exit gate: two local users sign in through `st.login()`, retain distinct durable
sessions across restarts, and cannot read each other's artifacts.

### Phase 3: GitHub OAuth

- Add GitHub provider configuration and callback routes.
- Persist and validate nested downstream/upstream login transactions.
- Resolve GitHub user IDs and apply access and role mappings.
- Add expiry, denial, callback replay, and provider-error handling.

Exit gate: two GitHub users sign in through the same Streamlit flow and receive
different `principal_id` values; the configured administrator mapping controls
shared catalog access.

### Phase 4: External OIDC and OCI IAM

- Add generic OIDC discovery and authorization-code handling.
- Validate ID tokens and map access and administrator claims.
- Test deterministic behavior with a local OIDC fixture.
- Complete a live OCI IAM Identity Domains login and logout test.

Exit gate: OCI users sign in through Streamlit, group or role changes take effect
after reauthentication, and issuer/subject mappings survive profile changes.

### Phase 5: REST, MCP, and Multi-Replica Completion

- Publish the gateway metadata needed by REST and MCP clients.
- Add refresh-token rotation for public API and MCP clients.
- Verify authorization and session context across REST, streaming chat, and MCP.
- Run two Server instances against one CORE database and confirm shared token,
  login-session, and working-session behavior.

Exit gate: one access token produces the same principal on every replica, and
logout or disablement is effective across replicas.

### Phase 6: Agent Memory Boundary

- Expose `principal_id` through authenticated request context.
- Require it on every user-scoped `AgentMemoryService` operation.
- Derive thread ownership from the principal and reject caller ownership fields.
- Add cross-user isolation tests with the real Oracle database.

Exit gate: Local, GitHub, and OCI users retain their own memories across sessions
and cannot search, update, or delete another principal's records.

### Phase 7: Packaging and Documentation

- Replace `devOidc` Helm values with provider-neutral auth values.
- Generate one Streamlit `[auth]` configuration pointing to the embedded gateway.
- Document Local, GitHub, and OCI IAM Identity Domains as complete examples.
- Update access-control, environment-variable, Helm, and Agent Memory guidance.

Exit gate: each documented example can be followed from a clean deployment and
passes the same two-user isolation checks.

## Verification

Use TDD for each phase. Keep deterministic protocol tests local and use live
providers for final smoke tests.

Relevant automated coverage:

- Unit tests for state, nonce, PKCE, redirect validation, code replay, token
  digests, expiry, revocation, principal resolution, and role mapping.
- ASGI tests for gateway endpoints, middleware, REST, streaming chat, and MCP.
- Streamlit content tests for signed-out login, token forwarding, renewal, user
  display, and logout.
- Oracle integration tests for concurrent principal creation, token redemption,
  session claims, role changes, and cross-user ownership.
- Helm contract tests for each auth mode, required Secrets, public issuer routes,
  callback URLs, and generated `secrets.toml`.

Run only relevant test modules, followed by Ruff on touched Python files and
`pyright .`. Documentation-only changes do not run pytest.

Manual acceptance matrix:

| Scenario | Local | GitHub | OCI IAM |
| --- | --- | --- | --- |
| Two users sign in with `st.login()` | Required | Required | Required |
| Stable `principal_id` after logout/login | Required | Required | Required |
| Working-session isolation | Required | Required | Required |
| Shared-catalog administrator mapping | Required | Required | Required |
| Agent Memory isolation | Required | Required | Required |
| Logout invalidates gateway session | Required | Required | Required |
| Multi-replica token resolution | N/A locally | Required | Required |

## Completion Criteria

- All three authentication sources use Streamlit's native OIDC login flow.
- Every authenticated request resolves one active durable principal.
- User-owned resources and Agent Memory use `principal_id` from request context.
- Access and administrator policy is explicit for each provider.
- Revocation and logout work across replicas.
- Provider credentials and identity tokens are absent from logs and persisted
  application records.
- Local setup requires the Client, Server, and CORE database only.
- GitHub and OCI examples pass the same two-user isolation procedure.

# OCI Module

Manages OCI (Oracle Cloud Infrastructure) profile configurations for
authenticating against OCI services (GenAI, Object Storage, etc.).

## Module Structure

| File | Purpose |
|------|---------|
| `schemas.py` | Pydantic models: `OciSensitive`, `OciProfileConfig`, `OciProfileUpdate` |
| `config.py` | OCI config file parser (`parse_oci_config_file`) and connectivity check (`_check_useable`) |
| `client.py` | OCI SDK client factory (`init_client`) and signer helper (`get_signer`) |
| `registry.py` | Profile registry (`register_oci_profile`) and startup entry point (`load_oci_profiles`) |

## Profile Schema

`OciProfileConfig` extends `OciSensitive` and carries all fields needed to
authenticate and interact with OCI services.

### Identity & Authentication

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `auth_profile` | `str` | *required* | Profile identifier; lookups are case-insensitive |
| `user` | `str?` | `None` | OCI user OCID |
| `authentication` | `str?` | `"api_key"` | Auth type: `api_key`, `instance_principal`, `oke_workload_identity`, `security_token` |
| `tenancy` | `str?` | `None` | Tenancy OCID |
| `region` | `str?` | `None` | OCI region identifier |

### Sensitive Fields (from `OciSensitive`)

These fields are excluded from API responses by default:

| Field | Type | Description |
|-------|------|-------------|
| `fingerprint` | `str?` | API key fingerprint |
| `key_content` | `str?` | Inline private key content |
| `key_file` | `str?` | Path to private key file |
| `pass_phrase` | `str?` | Private key passphrase |
| `security_token_file` | `str?` | Path to security token file |

### GenAI & Runtime

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `genai_compartment_id` | `str?` | `None` | Compartment OCID for GenAI inference |
| `genai_region` | `str?` | `None` | Region override for GenAI endpoint |
| `log_requests` | `bool?` | `False` | Enable OCI SDK request logging |
| `additional_user_agent` | `str?` | `""` | Extra User-Agent string |
| `useable` | `bool?` | `False` | Set at runtime by `_check_useable` |

## Startup Lifecycle

The lifespan handler in `main.py` executes these steps in order:

1. `.env` / environment variables loaded (at import time).
2. `configuration.json` overlay applied &mdash; `oci_profile_configs` **excluded**.
3. CORE database initialized.
4. DB settings overlay applied &mdash; `oci_profile_configs` **excluded**.
5. `load_oci_profiles()` called:
   - `parse_oci_config_file()` reads `~/.oci/config` (or the path in
     `OCI_CLI_CONFIG_FILE` env var).
   - Uses `configparser` to enumerate all sections (including `DEFAULT`),
     then `oci.config.from_file()` per profile for proper key inheritance.
   - Each profile is tested via `_check_useable()`.
   - Each profile is registered into `settings.oci_profile_configs` via
     `register_oci_profile()` (deduplicates by `auth_profile`, last-write wins).

## Connectivity Check (`_check_useable`)

Tests that a profile can reach OCI by making a lightweight API call:

- Creates an `ObjectStorageClient` with a short timeout `(1, 10)`.
- Calls `get_namespace()` as the connectivity probe.
- On success: sets `profile.useable = True`, returns `None`.
- On failure: sets `profile.useable = False`, returns the error string.
- Used at startup and on every API create/update.

## Authentication Methods

`init_client` / `get_signer` in `client.py` support four auth types:

| `authentication` value | Mechanism |
|------------------------|-----------|
| `api_key` (default) | Config dict with user, fingerprint, tenancy, region, and key file/content |
| `instance_principal` | `InstancePrincipalsSecurityTokenSigner` &mdash; for compute instances |
| `oke_workload_identity` | OKE workload identity resource principal signer |
| `security_token` | Reads token from `security_token_file`, loads private key, creates `SecurityTokenSigner` |

For GenAI inference clients, `init_client` automatically constructs the
service endpoint from `genai_region` when `genai_compartment_id` is set.

## API Endpoints

All routes are under `/v1/oci-profiles`.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | List all profiles. Sensitive fields excluded unless `?include_sensitive=true`. |
| `GET` | `/{auth_profile}` | Single profile (case-insensitive lookup). 404 if not found. |
| `POST` | `/` | Create a profile. Runs `_check_useable`; returns 422 if connectivity fails, 409 if duplicate. |
| `PUT` | `/{auth_profile}` | Update a profile. Runs `_check_useable`; rolls back changes if the profile was previously useable and the check fails (422). |
| `DELETE` | `/{auth_profile}` | Remove a profile. 404 if not found. |

## Persistence Model

OCI profiles are **not** persisted to the database.

- `persist_settings()` explicitly excludes `oci_profile_configs`.
- Profiles are loaded fresh from the OCI config file at each server startup.
- API CRUD operations (POST/PUT/DELETE) modify the in-memory list only.
- Changes survive for the duration of the server process but are lost on restart.
- The OCI config file (`~/.oci/config`) is the source of truth.

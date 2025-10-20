# Proposed Enhancement for litellm OCI Instance/Workload Principal Authentication

## Problem Statement

The current litellm OCI provider only supports API key authentication (user/fingerprint/tenancy/key). Oracle Cloud Infrastructure also supports instance principals and workload identity authentication, which are essential for cloud-native deployments where:
- VMs authenticate using instance metadata (instance_principal)
- Kubernetes pods authenticate using OKE workload identity (oke_workload_identity)

These authentication methods require the OCI SDK's signer classes, but **litellm cannot have a hard dependency on the 'oci' package**.

## Current Implementation in ai-optimizer

Located in `src/server/patches/litellm_patch.py`:

### Lines 90-145: validate_environment() Patch
- Adds `oci_auth_type` parameter support
- Skips credential validation when `oci_auth_type` is "instance_principal" or "oke_workload_identity"
- Only validates `oci_region` and basic headers

### Lines 148-222: sign_request() Patch
- Detects `oci_auth_type` parameter
- Creates appropriate signer using OCI SDK:
  - `oci.auth.signers.InstancePrincipalsSecurityTokenSigner()`
  - `oci.auth.signers.get_oke_workload_identity_resource_principal_signer()`
- Uses MockRequest class to interface with OCI signer
- Calls `signer.do_request_sign()` to sign the request

**Problem**: This approach imports `oci` directly in the patch, which would create a dependency if merged into litellm.

## Proposed Solution

Instead of importing `oci` directly in litellm, allow users to pass **pre-configured signer objects** through `optional_params`. The signer handles request signing externally, keeping litellm free of OCI SDK dependencies.

### Key Changes

1. **Add new optional parameter**: `oci_signer`
2. **Modify `validate_environment()`**: Skip credential checks when signer is provided
3. **Modify `sign_request()`**: Use the provided signer instead of manual signing
4. **Maintain backward compatibility**: Existing API key authentication unchanged

## Implementation Details

### 1. Define Signer Protocol (No Import Required)

```python
from typing import Protocol

class OCISignerProtocol(Protocol):
    """
    Protocol defining the interface for OCI request signers.
    This allows users to pass any signer that implements do_request_sign().
    """
    def do_request_sign(
        self,
        request,  # Any object with: method, url, headers, body, path_url attributes
        enforce_content_headers: bool = True
    ) -> None:
        """
        Signs an HTTP request by modifying request.headers in-place.

        Args:
            request: Mock request object with attributes:
                - method: HTTP method (GET, POST, etc.)
                - url: Full URL
                - headers: dict of headers (modified in-place)
                - body: Request body as bytes
                - path_url: Path + query string
            enforce_content_headers: Whether to enforce content headers
        """
        ...
```

### 2. Modified validate_environment()

**File**: `litellm/llms/oci/chat/transformation.py` (lines 358-410)

**Changes**:
```python
def validate_environment(
    self,
    headers: dict,
    model: str,
    messages: List[AllMessageValues],
    optional_params: dict,
    litellm_params: dict,
    api_key: Optional[str] = None,
    api_base: Optional[str] = None,
) -> dict:
    """
    MODIFIED: Check for oci_signer parameter to skip credential validation.
    """
    oci_signer = optional_params.get("oci_signer")

    # If a signer is provided, skip credential validation
    if oci_signer is not None:
        logger.info("Using provided OCI signer - skipping credential validation")
        oci_region = optional_params.get("oci_region", "us-ashburn-1")
        api_base = (
            api_base
            or litellm.api_base
            or f"https://inference.generativeai.{oci_region}.oci.oraclecloud.com"
        )

        if not api_base:
            raise Exception(
                "Either `api_base` must be provided or `litellm.api_base` must be set. "
                "Alternatively, you can set the `oci_region` optional parameter."
            )

        headers.update(
            {
                "content-type": "application/json",
                "user-agent": f"litellm/{version}",
            }
        )

        if not messages:
            raise Exception(
                "kwarg `messages` must be an array of messages that follow the openai chat standard"
            )

        return headers

    # EXISTING CODE: Standard API key validation continues below...
    # (lines 368-410 remain unchanged)
```

### 3. Modified sign_request()

**File**: `litellm/llms/oci/chat/transformation.py` (lines 231-356)

**Changes**:
```python
def sign_request(
    self,
    headers: dict,
    optional_params: dict,
    request_data: dict,
    api_base: str,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    stream: Optional[bool] = None,
    fake_stream: Optional[bool] = None,
) -> Tuple[dict, Optional[bytes]]:
    """
    MODIFIED: Use provided oci_signer if available, otherwise use API key signing.
    """
    oci_signer = optional_params.get("oci_signer")

    # If a signer is provided, use it for request signing
    if oci_signer is not None:
        logger.info("Using provided OCI signer for request signing")

        # Prepare the request body
        body = json.dumps(request_data).encode("utf-8")
        parsed = urlparse(api_base)
        method = str(optional_params.get("method", "POST")).upper()

        # Prepare headers with required fields for OCI signing
        prepared_headers = headers.copy()
        prepared_headers.setdefault("content-type", "application/json")
        prepared_headers.setdefault("content-length", str(len(body)))

        # Create a mock request object for OCI signing
        class MockRequest:
            def __init__(self, method: str, url: str, headers: dict, body: bytes):
                self.method = method
                self.url = url
                self.headers = headers
                self.body = body
                # path_url is the path + query string
                parsed_url = urlparse(url)
                self.path_url = parsed_url.path + ("?" + parsed_url.query if parsed_url.query else "")

        mock_request = MockRequest(
            method=method,
            url=api_base,
            headers=prepared_headers,
            body=body
        )

        # Sign the request using the provided signer
        try:
            oci_signer.do_request_sign(mock_request, enforce_content_headers=True)
        except Exception as e:
            raise Exception(
                f"Failed to sign request with provided oci_signer: {str(e)}. "
                "Ensure the signer implements do_request_sign(request, enforce_content_headers=True)"
            )

        # Update headers with signed headers
        headers.update(mock_request.headers)

        return headers, body

    # EXISTING CODE: Standard API key signing continues below...
    # (lines 254-356 remain unchanged)
```

## Usage Examples

### Example 1: Instance Principals (VM)

```python
import litellm
import oci  # User installs this separately

# User creates the signer (requires oci package installed)
instance_principal_signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()

# Use it with litellm
response = litellm.completion(
    model="oci/cohere.command-r-plus",
    messages=[{"role": "user", "content": "Hello!"}],
    oci_compartment_id="ocid1.compartment.oc1...",
    oci_signer=instance_principal_signer,  # NEW PARAMETER
    oci_region="us-ashburn-1"
)
```

### Example 2: OKE Workload Identity (Kubernetes)

```python
import litellm
import oci  # User installs this separately

# User creates the workload identity signer
workload_signer = oci.auth.signers.get_oke_workload_identity_resource_principal_signer()

# Use it with litellm
response = litellm.completion(
    model="oci/cohere.command-r-plus",
    messages=[{"role": "user", "content": "Hello!"}],
    oci_compartment_id="ocid1.compartment.oc1...",
    oci_signer=workload_signer,  # NEW PARAMETER
    oci_region="us-ashburn-1"
)
```

### Example 3: API Key Authentication (Backward Compatible)

```python
# Existing code continues to work unchanged
response = litellm.completion(
    model="oci/cohere.command-r-plus",
    messages=[{"role": "user", "content": "Hello!"}],
    oci_user="ocid1.user.oc1...",
    oci_fingerprint="12:34:56:78:90:ab:cd:ef",
    oci_tenancy="ocid1.tenancy.oc1...",
    oci_key_file="/path/to/private_key.pem",
    oci_compartment_id="ocid1.compartment.oc1...",
    oci_region="us-ashburn-1"
)
```

## Benefits

### 1. No OCI Dependency in litellm
- litellm does not import 'oci' package
- Users who need instance principals install 'oci' themselves
- Keeps litellm lightweight and dependency-free

### 2. Flexible Authentication
- Supports instance principals, workload identity, and future auth types
- Any signer that implements `do_request_sign()` works
- Could even support custom signers

### 3. Backward Compatible
- Existing API key authentication unchanged
- New parameter (`oci_signer`) is optional
- No breaking changes to existing code

### 4. Follows Established Patterns
- Similar to how litellm handles other cloud providers
- Clean separation of concerns
- User manages auth setup, litellm manages LLM calls

### 5. Cloud-Native Friendly
- Essential for Kubernetes deployments on OKE
- Essential for VM deployments using instance metadata
- No need to manage API keys/secrets in containers

## Documentation Updates Needed

Add to litellm OCI provider documentation:

```markdown
## Authentication Methods

### Method 1: API Key Authentication (Default)

Required parameters:
- `oci_user`: User OCID
- `oci_fingerprint`: API key fingerprint
- `oci_tenancy`: Tenancy OCID
- `oci_key` or `oci_key_file`: Private key (string or file path)
- `oci_compartment_id`: Compartment OCID

### Method 2: Instance Principals (VM Instances)

For applications running on OCI compute instances, use instance principal authentication.

**Required**: Install the OCI Python SDK (`pip install oci`)

```python
import litellm
import oci

# Create instance principal signer
signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()

response = litellm.completion(
    model="oci/cohere.command-r-plus",
    messages=[{"role": "user", "content": "Hello!"}],
    oci_signer=signer,
    oci_compartment_id="ocid1.compartment.oc1...",
    oci_region="us-ashburn-1"
)
```

### Method 3: OKE Workload Identity (Kubernetes)

For applications running in Oracle Kubernetes Engine (OKE), use workload identity authentication.

**Required**: Install the OCI Python SDK (`pip install oci`)

```python
import litellm
import oci

# Create workload identity signer
signer = oci.auth.signers.get_oke_workload_identity_resource_principal_signer()

response = litellm.completion(
    model="oci/cohere.command-r-plus",
    messages=[{"role": "user", "content": "Hello!"}],
    oci_signer=signer,
    oci_compartment_id="ocid1.compartment.oc1...",
    oci_region="us-ashburn-1"
)
```

### Custom Signers

You can provide any signer object that implements the `do_request_sign(request, enforce_content_headers=True)` method.
```

## Testing Considerations

### Unit Tests
1. API key authentication (existing tests - no change)
2. Signer-based authentication with mock signer
3. `validate_environment()` skips credential check when signer provided
4. `sign_request()` uses signer instead of manual signing
5. Error handling when signer fails
6. Backward compatibility (no signer provided)

### Integration Tests
(In separate OCI-enabled environment)
1. Actual instance principal authentication
2. Actual workload identity authentication
3. End-to-end LLM calls with different auth methods

## Migration Path for ai-optimizer

Once this is merged into litellm, we can simplify our code:

### Before (Current Patch)
**File**: `src/server/patches/litellm_patch.py` (lines 90-222)
- Custom `validate_environment()` with `oci_auth_type` checks
- Custom `sign_request()` with oci SDK import
- Monkey-patching `OCIChatConfig`
- **~130 lines of patch code**

### After (Using Upstream litellm)
**File**: Model configuration (e.g., `src/server/bootstrap/models.py`)

```python
import oci

def get_oci_signer(oci_auth_type: str):
    """Create OCI signer based on auth type."""
    if oci_auth_type == "instance_principal":
        return oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
    elif oci_auth_type == "oke_workload_identity":
        return oci.auth.signers.get_oke_workload_identity_resource_principal_signer()
    else:
        return None  # Use API key auth

# When calling litellm
signer = get_oci_signer(model_config.oci_auth_type)

response = litellm.completion(
    model="oci/cohere.command-r-plus",
    messages=[...],
    oci_signer=signer,  # Pass signer here
    oci_compartment_id="...",
    oci_region="...",
    ...
)
```

**Result**:
- Remove ~130 lines of patch code
- Cleaner implementation
- No monkey-patching required
- Easier to maintain

## Comparison with Current Patch

| Aspect | Current Patch | Proposed Solution |
|--------|---------------|-------------------|
| OCI import location | Inside litellm patch | User's code (outside litellm) |
| Auth type parameter | `oci_auth_type` (string) | `oci_signer` (object) |
| Signer creation | Inside `sign_request()` | User creates before calling litellm |
| Dependency on oci | Implicit (via patch) | Explicit (user installs if needed) |
| Maintainability | Requires patching | Uses standard litellm API |
| litellm changes | None (external patch) | Minimal (2 functions, ~60 lines) |

## Contribution Checklist

- [ ] Fork litellm repository
- [ ] Create feature branch: `feature/oci-signer-support`
- [ ] Implement changes to `litellm/llms/oci/chat/transformation.py`
- [ ] Add unit tests with mock signer
- [ ] Update documentation (OCI provider docs)
- [ ] Add examples to documentation
- [ ] Test backward compatibility
- [ ] Create pull request with detailed description
- [ ] Reference this analysis document in PR

## Files to Modify in litellm Repository

1. **litellm/llms/oci/chat/transformation.py**
   - Line 358-410: Modify `validate_environment()`
   - Line 231-356: Modify `sign_request()`
   - Add ~60 lines of new code (signer support)
   - No lines removed (backward compatible)

2. **tests/test_oci.py** (or similar)
   - Add test cases for signer-based authentication
   - Add mock signer class for testing
   - Test backward compatibility

3. **docs/my-website/docs/providers/oci.md** (or similar)
   - Add section on instance principal authentication
   - Add section on workload identity authentication
   - Add usage examples

## Expected Impact

- **Breaking changes**: None
- **New dependencies**: None
- **Lines of code**: ~60 new lines, 0 removed
- **Test coverage**: Existing tests pass, new tests for signer support
- **Performance**: No impact (same signing process)
- **Security**: Improved (supports cloud-native auth methods)

## Next Steps

1. Review this analysis with the team
2. Create GitHub issue in litellm repository explaining the use case
3. Get feedback from litellm maintainers on approach
4. Implement changes in fork
5. Submit pull request with comprehensive tests and documentation
6. Once merged, update ai-optimizer to use new upstream functionality
7. Remove patch code from ai-optimizer

## References

- Current patch: `src/server/patches/litellm_patch.py` (lines 90-222)
- litellm OCI implementation: `.venv/lib/python3.11/site-packages/litellm/llms/oci/chat/transformation.py`
- OCI SDK signers: https://docs.oracle.com/en-us/iaas/tools/python/latest/api/signing.html

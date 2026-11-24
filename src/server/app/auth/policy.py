"""Authorization policy for authenticated HTTP routes."""

from typing import Literal

from fastapi import Depends, HTTPException, Request, status

from server.app.auth.dependencies import require_authenticated
from server.app.auth.models import AuthContext

RoutePolicy = Literal["member", "admin", "system"]

_MEMBER_ENDPOINTS = {
    "me",
    "logout",
    "get_client_settings",
    "update_client_settings",
    "list_databases",
    "get_database",
    "list_models",
    "models_supported",
    "get_model",
    "list_oci_profiles",
    "get_oci_profile",
    "list_genai_models",
    "oci_list_compartments",
    "oci_list_buckets",
    "oci_list_bucket_objects",
    "list_specs",
    "get_spec",
    "get_all_help",
    "get_help",
    "chat_completions",
    "chat_stream",
    "chat_history_return",
    "chat_history_clean",
    "list_testsets",
    "list_evaluations",
    "get_evaluation",
    "get_testset_qa_endpoint",
    "evaluate_testset",
    "embed_get_files",
    "list_embed_jobs",
    "get_embed_job",
    "deepsec_status",
    "deepsec_objects",
    "deepsec_object_columns",
    "list_data_roles",
    "list_end_users",
    "dds_connect_as",
    "dds_clear_connect_as",
    "list_data_role_grants",
    "list_data_grants",
    "openapi_schema",
    "list_tools",
    "list_resources",
    "list_prompts",
    "get_client_config",
}

_ADMIN_ENDPOINTS = {
    "list_users",
    "create_user",
    "patch_user",
    "reset_user_password",
    "export_settings",
    "copy_to_server",
    "import_settings",
    "reset_to_factory",
    "create_database",
    "update_database",
    "remove_database",
    "delete_vector_store",
    "pull_model",
    "create_model",
    "update_model",
    "delete_model",
    "create_oci_profile",
    "update_oci_profile",
    "delete_oci_profile",
    "enable_genai_models",
    "oci_download_objects",
    "update_prompt",
    "reset_all_prompts",
    "reset_prompt",
    "delete_testset_endpoint",
    "upload_testset",
    "generate_testset_endpoint",
    "embed_drop_vs",
    "comment_vs",
    "store_sql_file",
    "store_web_file",
    "store_local_file",
    "embed_oci_store",
    "split_embed",
    "refresh_vector_store",
    "create_data_role",
    "drop_data_role",
    "create_end_user",
    "drop_end_user",
    "grant_data_role",
    "revoke_data_role",
    "create_data_grant",
    "drop_data_grant",
}

_SYSTEM_ENDPOINTS = {"create_client_settings", "delete_client_settings"}

ROUTE_POLICIES: dict[str, RoutePolicy] = {
    **dict.fromkeys(_MEMBER_ENDPOINTS, "member"),
    **dict.fromkeys(_ADMIN_ENDPOINTS, "admin"),
    **dict.fromkeys(_SYSTEM_ENDPOINTS, "system"),
}


async def enforce_route_policy(
    request: Request,
    context: AuthContext = Depends(require_authenticated),
) -> AuthContext:
    """Enforce the declared policy for the matched endpoint."""
    route = request.scope.get("route")
    name = getattr(route, "name", None)
    policy = ROUTE_POLICIES.get(name) if isinstance(name, str) else None
    if policy is None:
        raise HTTPException(status_code=500, detail="Route authorization policy is missing")
    if policy == "system":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Internal route")
    if policy == "admin" and "admin" not in context.principal.roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator role required")
    return context

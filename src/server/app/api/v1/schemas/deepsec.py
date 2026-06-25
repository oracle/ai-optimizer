"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Pydantic models for the Deep Data Security API.
"""
# spell-checker:ignore deepsec

from pydantic import BaseModel, Field


class DeepSecCapabilities(BaseModel):
    """What the connected database user is privileged to do with Deep Data Security."""

    create_data_role: bool
    drop_data_role: bool
    create_end_user: bool
    drop_end_user: bool
    manage_data_grants: bool
    grant_data_roles: bool
    list_data_roles: bool
    list_end_users: bool
    list_data_grants: bool
    list_data_role_grants: bool


class DeepSecStatus(BaseModel):
    """Availability + capability matrix that drives UI enablement."""

    available: bool = Field(description="Whether the database build includes Deep Data Security")
    version: str | None = Field(default=None, description="Database version_full")
    capabilities: DeepSecCapabilities


class SchemaObject(BaseModel):
    """A table or view in the user's schema that a data grant can target."""

    name: str
    type: str


class DataRole(BaseModel):
    """A Deep Data Security data role."""

    name: str
    mapped_to: str | None = None
    enabled_by_default: bool = True


class DataRoleCreate(BaseModel):
    """Request to create a data role."""

    name: str
    mapped_to: str | None = Field(default=None, description="External application role mapping")


class EndUser(BaseModel):
    """A Deep Data Security end user."""

    name: str
    account_status: str | None = None
    schema_name: str | None = None
    created: str | None = None


class EndUserCreate(BaseModel):
    """Request to create an end user.

    The end user is provisioned server-side with the same password as the
    connected database user, so no password is accepted from the client.
    """

    name: str
    schema_name: str | None = Field(default=None, description="Existing schema for name resolution")


class ConnectAsRequest(BaseModel):
    """Designate a DDS end user for chat-time read tools to connect as."""

    end_user: str = Field(description="Existing DDS end user to connect tools as")


class ConnectAsResponse(BaseModel):
    """The runtime-only managed connection registered for the connect-as end user."""

    alias: str = Field(description="Managed database alias the chat tools will use")
    base_alias: str = Field(description="Owner database alias this override is scoped to")
    end_user: str


class DataRoleGrant(BaseModel):
    """A data role granted to an end user (row from DBA_DATA_ROLE_GRANTS)."""

    data_role: str
    grantee: str
    start_time: str | None = None
    end_time: str | None = None


class DataRoleGrantCreate(BaseModel):
    """Request to grant one or more locally-managed data roles to an end user."""

    grantee: str = Field(description="Local end user to grant the data roles to")
    roles: list[str] = Field(description="Locally-managed data roles to grant")


class DataGrant(BaseModel):
    """A row in USER_DATA_GRANTS (data grants are expanded per granted column)."""

    name: str
    privilege: str | None = None
    column_name: str | None = None
    all_columns_except: bool | None = None
    object_owner: str | None = None
    object_name: str | None = None
    object_type: str | None = None
    predicate: str | None = None
    grantee: str | None = None
    grantee_type: str | None = None
    start_time: str | None = None
    end_time: str | None = None


class DataGrantCreate(BaseModel):
    """Request to create a data grant."""

    name: str
    privileges: list[str] = Field(description="One or more of SELECT, INSERT, UPDATE, DELETE")
    object_name: str = Field(description="Target table/view in the user's schema")
    grantee: str = Field(description="Data role (or end user) to authorize")
    columns: list[str] | None = Field(default=None, description="Columns the privileges apply to")
    all_columns_except: bool = Field(
        default=False, description="Treat 'columns' as the excluded set (ALL COLUMNS EXCEPT)"
    )
    predicate: str | None = Field(default=None, description="Row-level WHERE predicate (policy text)")
    or_replace: bool = False

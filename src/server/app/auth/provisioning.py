"""Constrained Oracle package for local end-user administration."""

import hashlib

import oracledb

from server.app.database.quoting import quote_identifier
from server.app.database.sql import execute_sql

_PACKAGE_ROLE_PREFIX = "AIO_AUTH_PACKAGE_"
LOGIN_DATA_ROLE = "AIO_LOGIN_ROLE"


def package_role_name(application_schema: str) -> str:
    digest = hashlib.sha256(application_schema.upper().encode()).hexdigest()[:16].upper()
    return f"{_PACKAGE_ROLE_PREFIX}{digest}"


PROVISIONING_DDL = (
    """CREATE OR REPLACE PACKAGE aio_auth_admin AUTHID DEFINER AS
         PROCEDURE create_user(
           p_username IN VARCHAR2,
           p_password IN VARCHAR2
         );
         PROCEDURE alter_user(p_username IN VARCHAR2, p_action IN VARCHAR2, p_password IN VARCHAR2 DEFAULT NULL);
         PROCEDURE account_status(p_username IN VARCHAR2, p_status OUT VARCHAR2);
       END aio_auth_admin;""",
    """CREATE OR REPLACE PACKAGE BODY aio_auth_admin AS
         FUNCTION quoted_username(p_username IN VARCHAR2) RETURN VARCHAR2 IS
         BEGIN
           IF NOT REGEXP_LIKE(p_username, '^[A-Za-z][A-Za-z0-9_$#]{0,127}$') THEN
             RAISE_APPLICATION_ERROR(-20001, 'Invalid end-user name');
           END IF;
           RETURN '"' || UPPER(p_username) || '"';
         END;
         FUNCTION quoted_password(p_password IN VARCHAR2) RETURN VARCHAR2 IS
         BEGIN
           IF p_password IS NULL OR INSTR(p_password, CHR(0)) > 0 OR
              INSTR(p_password, CHR(10)) > 0 OR INSTR(p_password, CHR(13)) > 0 THEN
             RAISE_APPLICATION_ERROR(-20002, 'Invalid password');
           END IF;
           RETURN '"' || REPLACE(p_password, '"', '""') || '"';
         END;
         PROCEDURE create_user(
           p_username IN VARCHAR2,
           p_password IN VARCHAR2
         ) IS
         BEGIN
           EXECUTE IMMEDIATE 'CREATE END USER ' || quoted_username(p_username) ||
             ' IDENTIFIED BY ' || quoted_password(p_password);
           BEGIN
             EXECUTE IMMEDIATE 'GRANT DATA ROLE "@@LOGIN_ROLE@@" TO ' || quoted_username(p_username);
           EXCEPTION WHEN OTHERS THEN
             EXECUTE IMMEDIATE 'DROP END USER ' || quoted_username(p_username);
             RAISE;
           END;
         END;
         PROCEDURE alter_user(p_username IN VARCHAR2, p_action IN VARCHAR2, p_password IN VARCHAR2 DEFAULT NULL) IS
         BEGIN
           IF UPPER(p_action) = 'LOCK' THEN
             EXECUTE IMMEDIATE 'ALTER END USER ' || quoted_username(p_username) || ' ACCOUNT LOCK';
           ELSIF UPPER(p_action) = 'UNLOCK' THEN
             EXECUTE IMMEDIATE 'ALTER END USER ' || quoted_username(p_username) || ' ACCOUNT UNLOCK';
           ELSIF UPPER(p_action) = 'RESET' THEN
             EXECUTE IMMEDIATE 'ALTER END USER ' || quoted_username(p_username) || ' IDENTIFIED BY ' ||
               quoted_password(p_password) || ' ACCOUNT UNLOCK';
           ELSE
             RAISE_APPLICATION_ERROR(-20003, 'Unsupported account action');
           END IF;
         END;
         PROCEDURE account_status(p_username IN VARCHAR2, p_status OUT VARCHAR2) IS
           v_login_roles NUMBER;
         BEGIN
           EXECUTE IMMEDIATE
             'SELECT account_status FROM dba_end_users WHERE username = :username'
             INTO p_status USING UPPER(p_username);
           EXECUTE IMMEDIATE
             'SELECT COUNT(*) FROM dba_data_role_grants WHERE grantee = :username ' ||
             'AND data_role = ''@@LOGIN_ROLE@@'' AND grantee_type = ''END USER'''
             INTO v_login_roles USING UPPER(p_username);
           IF v_login_roles = 0 THEN p_status := 'UNMANAGED'; END IF;
         EXCEPTION WHEN NO_DATA_FOUND THEN p_status := 'MISSING';
         END;
       END aio_auth_admin;""",
)


async def provisioning_package_available(conn: oracledb.AsyncConnection) -> bool:
    rows = await execute_sql(
        conn,
        "SELECT object_type FROM user_objects WHERE object_name = 'AIO_AUTH_ADMIN' "
        "AND object_type IN ('PACKAGE', 'PACKAGE BODY') AND status = 'VALID'",
        max_rows=2,
    )
    return {row[0] for row in rows or []} == {"PACKAGE", "PACKAGE BODY"}


async def missing_local_user_management_capabilities(conn: oracledb.AsyncConnection) -> list[str]:
    """Return database capabilities needed to manage member end users."""
    missing = []
    for view, capability in (
        ("DBA_END_USERS", "local end-user accounts"),
        ("DBA_DATA_ROLES", "data roles"),
        ("DBA_DATA_ROLE_GRANTS", "data-role grants"),
    ):
        try:
            await execute_sql(
                conn,
                f"SELECT 1 FROM {view} WHERE 1 = 0",
                max_rows=1,
                ignored_error_codes=frozenset(),
            )
        except oracledb.Error:
            missing.append(capability)
    try:
        rows = await execute_sql(
            conn,
            "SELECT privilege FROM USER_SYS_PRIVS "
            "WHERE privilege IN ('CREATE END USER', 'ALTER END USER', 'DROP END USER', "
            "'CREATE DATA ROLE', 'GRANT ANY DATA ROLE')",
            max_rows=10,
        )
    except oracledb.Error:
        rows = []
    privileges = {row[0] for row in rows or []}
    for privilege, capability in (
        ("CREATE END USER", "CREATE END USER privilege"),
        ("ALTER END USER", "ALTER END USER privilege"),
        ("DROP END USER", "DROP END USER privilege"),
        ("CREATE DATA ROLE", "CREATE DATA ROLE privilege"),
        ("GRANT ANY DATA ROLE", "GRANT ANY DATA ROLE privilege"),
    ):
        if privilege not in privileges:
            missing.append(capability)
    return missing


async def local_user_management_issues(conn: oracledb.AsyncConnection) -> list[str]:
    """Return conditions preventing local member administration."""
    if not await provisioning_package_available(conn):
        return ["AIO_AUTH_ADMIN package is unavailable"]
    try:
        identity = await execute_sql(
            conn,
            "SELECT SYS_CONTEXT('USERENV', 'SESSION_USER') FROM dual",
            max_rows=1,
        )
        if not identity:
            return ["database identity is unavailable"]
        delegated_role = package_role_name(str(identity[0][0]))
        delegated_roles = await execute_sql(
            conn,
            "SELECT granted_role FROM user_role_privs WHERE granted_role = :role AND delegate_option = 'YES'",
            {"role": delegated_role},
            max_rows=10,
        )
    except oracledb.Error:
        delegated_roles = []
    if delegated_roles:
        return []
    try:
        login_role = await execute_sql(
            conn,
            "SELECT data_role FROM dba_data_roles WHERE data_role = :role",
            {"role": LOGIN_DATA_ROLE},
            max_rows=1,
        )
    except oracledb.Error:
        return [f"{LOGIN_DATA_ROLE} data role is unavailable"]
    if not login_role:
        return [f"{LOGIN_DATA_ROLE} data role is unavailable"]
    return await missing_local_user_management_capabilities(conn)


async def install_provisioning_package(conn: oracledb.AsyncConnection) -> None:
    """Install the constrained local-user administration package."""
    async with conn.cursor() as cursor:
        for ddl in PROVISIONING_DDL:
            await cursor.execute(ddl.replace("@@LOGIN_ROLE@@", LOGIN_DATA_ROLE))


async def configure_provisioning_authority(
    privileged_conn: oracledb.AsyncConnection,
    package_conn: oracledb.AsyncConnection,
    application_schema: str,
) -> None:
    """Attach end-user privileges exclusively to the provisioning package."""
    schema = quote_identifier(application_schema)
    package_role = package_role_name(application_schema)
    role_rows = await execute_sql(
        privileged_conn,
        "SELECT role, SYS_CONTEXT('USERENV', 'SESSION_USER') FROM dba_roles WHERE role = :role",
        {"role": package_role},
        max_rows=1,
        ignored_error_codes=frozenset(),
    )
    if role_rows:
        user_grants = await execute_sql(
            privileged_conn,
            "SELECT grantee FROM dba_role_privs WHERE granted_role = :role",
            {"role": package_role},
            max_rows=100,
            ignored_error_codes=frozenset(),
        )
        expected_grantees = {application_schema.upper(), str(role_rows[0][1]).upper()}
        unexpected_users = {row[0] for row in user_grants or []} - expected_grantees
        code_grants = await execute_sql(
            privileged_conn,
            "SELECT owner, object_name FROM dba_code_role_privs WHERE role = :role",
            {"role": package_role},
            max_rows=100,
            ignored_error_codes=frozenset(),
        )
        unexpected_code = {(row[0], row[1]) for row in code_grants or []} - {
            (application_schema.upper(), "AIO_AUTH_ADMIN")
        }
        if unexpected_users or unexpected_code:
            raise RuntimeError("Authentication package role has unexpected grantees")
    if not role_rows:
        await execute_sql(
            privileged_conn,
            f"CREATE ROLE {package_role}",
            ignored_error_codes=frozenset(),
        )
    for statement in (
        f"GRANT CREATE END USER TO {package_role}",
        f"GRANT ALTER END USER TO {package_role}",
        f"GRANT DROP END USER TO {package_role}",
        f"GRANT GRANT ANY DATA ROLE TO {package_role}",
        f"GRANT SELECT ANY DICTIONARY TO {package_role}",
        f"GRANT {package_role} TO {schema} WITH DELEGATE OPTION",
    ):
        try:
            await execute_sql(privileged_conn, statement, ignored_error_codes=frozenset())
        except oracledb.DatabaseError:
            raise RuntimeError(f"Could not configure authentication package authority: {statement}") from None
    await execute_sql(
        package_conn,
        f"GRANT {package_role} TO PACKAGE {schema}.AIO_AUTH_ADMIN",
        ignored_error_codes=frozenset(),
    )
    for privilege in ("CREATE END USER", "ALTER END USER", "DROP END USER"):
        try:
            await execute_sql(
                privileged_conn,
                f"REVOKE {privilege} FROM {schema}",
                ignored_error_codes=frozenset(),
            )
        except oracledb.DatabaseError as exc:
            code = getattr(exc.args[0], "code", None) if exc.args else None
            if code != 1952:
                raise
    await execute_sql(
        package_conn,
        "ALTER PACKAGE aio_auth_admin COMPILE PACKAGE",
        ignored_error_codes=frozenset(),
    )
    await execute_sql(
        package_conn,
        "ALTER PACKAGE aio_auth_admin COMPILE BODY",
        ignored_error_codes=frozenset(),
    )

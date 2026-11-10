"""Constrained Oracle package for local end-user administration."""

import re

import oracledb

from server.app.core.settings import settings

PROVISIONING_DDL = (
    """CREATE OR REPLACE PACKAGE aio_auth_admin AUTHID DEFINER AS
         PROCEDURE create_user(p_username IN VARCHAR2, p_password IN VARCHAR2);
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
         PROCEDURE create_user(p_username IN VARCHAR2, p_password IN VARCHAR2) IS
         BEGIN
           EXECUTE IMMEDIATE 'CREATE END USER ' || quoted_username(p_username) ||
             ' IDENTIFIED BY ' || quoted_password(p_password) || ' PASSWORD EXPIRE';
           EXECUTE IMMEDIATE 'GRANT DATA ROLE "@@LOGIN_ROLE@@" TO ' || quoted_username(p_username);
         END;
         PROCEDURE alter_user(p_username IN VARCHAR2, p_action IN VARCHAR2, p_password IN VARCHAR2 DEFAULT NULL) IS
         BEGIN
           IF UPPER(p_action) = 'LOCK' THEN
             EXECUTE IMMEDIATE 'ALTER END USER ' || quoted_username(p_username) || ' ACCOUNT LOCK';
           ELSIF UPPER(p_action) = 'UNLOCK' THEN
             EXECUTE IMMEDIATE 'ALTER END USER ' || quoted_username(p_username) || ' ACCOUNT UNLOCK';
           ELSIF UPPER(p_action) = 'RESET' THEN
             EXECUTE IMMEDIATE 'ALTER END USER ' || quoted_username(p_username) || ' IDENTIFIED BY ' ||
               quoted_password(p_password) || ' PASSWORD EXPIRE ACCOUNT UNLOCK';
           ELSE
             RAISE_APPLICATION_ERROR(-20003, 'Unsupported account action');
           END IF;
         END;
         PROCEDURE account_status(p_username IN VARCHAR2, p_status OUT VARCHAR2) IS
         BEGIN
           SELECT account_status INTO p_status FROM dba_end_users WHERE username = UPPER(p_username);
         EXCEPTION WHEN NO_DATA_FOUND THEN p_status := 'MISSING';
         END;
       END aio_auth_admin;""",
)


async def install_provisioning_package(conn: oracledb.AsyncConnection) -> None:
    """Install the constrained package using the configured login data role."""
    role = settings.auth_login_data_role.upper()
    if re.fullmatch(r"[A-Z][A-Z0-9_$#]{0,127}", role) is None:
        raise ValueError("AIO_AUTH_LOGIN_DATA_ROLE must be a simple Oracle identifier")
    async with conn.cursor() as cursor:
        for ddl in PROVISIONING_DDL:
            await cursor.execute(ddl.replace("@@LOGIN_ROLE@@", role))

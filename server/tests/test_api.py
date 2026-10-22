"""Registration, sign-in, sessions, roles and administration against a real PostgreSQL (H3, H12, H14, H15)."""

from __future__ import annotations

import uuid
from datetime import timedelta

import psycopg
import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from fastapi.routing import APIRoute
from sqlalchemy import text

from mbs import accounts, postgres
from mbs.models import AccountsBase, BiometricBase

PASSWORD = "a long enough passphrase"
NEW_PASSWORD = "another long passphrase"


def register(client, username="michael", email="michael@example.org", national_id="123456782", password=PASSWORD):
    return client.post("/api/register", json={"username": username, "email": email, "password": password,
                                              "national_id": national_id})


def sign_in(client, login="michael", password=PASSWORD):
    response = client.post("/api/login", json={"login": login, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["token"]


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def administrator(client, databases, username="admin", email="admin@example.org"):
    """A signed-in administrator whose one-time password was replaced; returns its token."""
    one_time = accounts.first_administrator(databases, username, email)
    token = sign_in(client, username, one_time)
    assert client.post("/api/me/password", json={"current": one_time, "new": NEW_PASSWORD},
                       headers=auth(token)).status_code == 204
    return token


def error(response):
    return response.status_code, response.json()["error"]


def test_register_then_sign_in_with_username_or_email(client):
    created = register(client)
    assert created.status_code == 201
    assert created.json()["account"]["role"] == "user"
    for login in ("michael", "MICHAEL", "Michael@Example.org"):
        me = client.get("/api/me", headers=auth(sign_in(client, login)))
        assert me.status_code == 200
        assert me.json()["modalities"] == {m: {"enrolled": False} for m in ("fingerprint", "face", "voice")}


def test_the_national_id_is_checked_and_registered_once(client):
    assert error(register(client, national_id="123456789")) == (400, "invalid_national_id")
    assert register(client).status_code == 201
    second = register(client, username="other", email="other@example.org", national_id="12345678-2")
    assert error(second) == (409, "national_id_registered")


def test_usernames_and_emails_are_unique_ignoring_case(client):
    assert register(client).status_code == 201
    assert error(register(client, username="MICHAEL", email="x@example.org", national_id="000000018")) == \
        (409, "username_taken")
    assert error(register(client, username="other", email="MICHAEL@example.org", national_id="000000018")) == \
        (409, "email_taken")


@pytest.mark.parametrize("field, value, code", [("username", "a", "invalid_username"),
                                                ("username", "two words", "invalid_username"),
                                                ("email", "not-an-email", "invalid_email"),
                                                ("password", "short", "weak_password")])
def test_registration_fields_are_checked(client, field, value, code):
    assert error(register(client, **{field: value})) == (400, code)


def test_hebrew_usernames_are_accepted(client):
    assert register(client, username="מיכאל").status_code == 201
    sign_in(client, "מיכאל")


def test_the_national_id_is_stored_nowhere_and_the_link_opens(client, databases, keys):
    account_id = uuid.UUID(register(client).json()["account"]["id"])
    for engine in (databases.accounts, databases.biometric):
        with engine.connect() as conn:
            tables = conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")).scalars().all()
            for table in tables:
                rows = conn.execute(text(f'SELECT row_to_json(t)::text FROM "{table}" t')).scalars().all()
                assert not any("123456782" in row for row in rows), table
    subject = accounts.subject_of(databases, keys, account_id)
    with databases.biometric.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM subject WHERE id = :id"), {"id": subject}).scalar() == 1


def test_a_wrong_password_and_an_unknown_name_get_the_same_answer(client):
    register(client)
    wrong = client.post("/api/login", json={"login": "michael", "password": "not the right one"})
    unknown = client.post("/api/login", json={"login": "nobody", "password": PASSWORD})
    assert error(wrong) == error(unknown) == (401, "wrong_credentials")


def test_repeated_failed_sign_ins_are_slowed_down(client):
    register(client)
    for _ in range(accounts.Throttle.FREE):
        assert client.post("/api/login", json={"login": "michael", "password": "wrong"}).status_code == 401
    slowed = client.post("/api/login", json={"login": "michael", "password": PASSWORD})
    assert error(slowed) == (429, "too_many_attempts")
    assert int(slowed.headers["Retry-After"]) >= 1


def test_every_route_declares_who_may_call_it(client):
    routes = [r for r in client.app.routes if isinstance(r, APIRoute)]
    assert routes
    assert all(getattr(r.endpoint, "mbs_allow", None) for r in routes), [r.path for r in routes]


def test_a_route_without_a_declaration_is_refused(client):
    @client.app.get("/api/undeclared")
    def undeclared() -> dict:
        return {}

    assert error(client.get("/api/undeclared")) == (403, "forbidden")


def test_routes_need_a_session_and_the_right_role(client):
    register(client)
    assert error(client.get("/api/me")) == (401, "not_signed_in")
    assert error(client.get("/api/me", headers=auth("made-up"))) == (401, "not_signed_in")
    assert error(client.get("/api/admin/accounts", headers=auth(sign_in(client)))) == (403, "forbidden")


def test_sign_out_and_idle_sessions_end(client, databases):
    register(client)
    token = sign_in(client)
    assert client.post("/api/logout", headers=auth(token)).status_code == 204
    assert error(client.get("/api/me", headers=auth(token))) == (401, "not_signed_in")
    idle = sign_in(client)
    with databases.accounts.begin() as conn:
        conn.execute(text("UPDATE session SET last_seen_at = now() - :idle"),
                     {"idle": accounts.SESSION_IDLE + timedelta(minutes=1)})
    assert error(client.get("/api/me", headers=auth(idle))) == (401, "not_signed_in")


def test_a_password_change_signs_out_the_other_sessions(client):
    register(client)
    first, second = sign_in(client), sign_in(client)
    assert client.post("/api/me/password", json={"current": PASSWORD, "new": NEW_PASSWORD},
                       headers=auth(first)).status_code == 204
    assert client.get("/api/me", headers=auth(first)).status_code == 200
    assert error(client.get("/api/me", headers=auth(second))) == (401, "not_signed_in")
    sign_in(client, password=NEW_PASSWORD)


def test_the_first_administrator_must_replace_its_one_time_password(client, databases):
    one_time = accounts.first_administrator(databases, "admin", "admin@example.org")
    token = sign_in(client, "admin", one_time)
    assert error(client.get("/api/admin/accounts", headers=auth(token))) == (403, "password_change_required")
    me = client.get("/api/me", headers=auth(token)).json()
    assert me["account"]["must_change_password"] is True and me["modalities"] is None
    assert client.post("/api/me/password", json={"current": one_time, "new": NEW_PASSWORD},
                       headers=auth(token)).status_code == 204
    assert client.get("/api/admin/accounts", headers=auth(token)).status_code == 200


def test_administrators_have_no_national_id_or_biometric_link(client, databases):
    administrator(client, databases)
    with databases.accounts.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM identity_link")).scalar() == 0
    with databases.biometric.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM subject")).scalar() == 0


def test_a_new_administrator_needs_the_password_again_and_is_audited(client, databases):
    token = administrator(client, databases)
    body = {"password": "not the right one", "username": "second", "email": "second@example.org"}
    assert error(client.post("/api/admin/administrators", json=body, headers=auth(token))) == (403, "wrong_password")
    created = client.post("/api/admin/administrators", json={**body, "password": NEW_PASSWORD}, headers=auth(token))
    assert created.status_code == 201
    second = sign_in(client, "second", created.json()["one_time_password"])
    assert error(client.get("/api/admin/audit", headers=auth(second))) == (403, "password_change_required")
    entries = client.get("/api/admin/audit", headers=auth(token)).json()["entries"]
    assert [(e["action"], e["target"]) for e in entries] == [("create_administrator", "second"),
                                                             ("first_administrator", "admin")]


def test_a_disabled_account_loses_its_sessions_and_cannot_sign_in(client, databases):
    account_id = register(client).json()["account"]["id"]
    user = sign_in(client)
    token = administrator(client, databases)
    status = f"/api/admin/accounts/{account_id}/status"
    assert client.post(status, json={"password": NEW_PASSWORD, "status": "disabled"}, headers=auth(token)).status_code == 204
    assert error(client.get("/api/me", headers=auth(user))) == (401, "not_signed_in")
    assert error(client.post("/api/login", json={"login": "michael", "password": PASSWORD})) == (403, "account_disabled")
    assert client.post(status, json={"password": NEW_PASSWORD, "status": "active"}, headers=auth(token)).status_code == 204
    sign_in(client)


def test_the_last_active_administrator_cannot_be_disabled(client, databases):
    token = administrator(client, databases)
    accounts_list = client.get("/api/admin/accounts", headers=auth(token)).json()["accounts"]
    own = f"/api/admin/accounts/{accounts_list[0]['id']}/status"
    assert error(client.post(own, json={"password": NEW_PASSWORD, "status": "disabled"}, headers=auth(token))) == \
        (409, "last_administrator")
    created = client.post("/api/admin/administrators", headers=auth(token),
                          json={"password": NEW_PASSWORD, "username": "second", "email": "second@example.org"})
    second = f"/api/admin/accounts/{created.json()['account']['id']}/status"
    assert client.post(second, json={"password": NEW_PASSWORD, "status": "disabled"}, headers=auth(token)).status_code == 204


@pytest.mark.parametrize("statement", ["UPDATE audit_log SET action = 'x'", "DELETE FROM audit_log",
                                       "TRUNCATE audit_log"])
def test_the_audit_log_only_takes_inserts(client, databases, statement):
    administrator(client, databases)
    with pytest.raises(Exception, match="only takes inserts"):
        with databases.accounts.begin() as conn:
            conn.execute(text(statement))


def test_each_database_is_closed_to_the_other_role(config, keys, databases):
    with pytest.raises(psycopg.OperationalError, match="permission denied"):
        psycopg.connect(host="127.0.0.1", port=config.database_port, dbname=postgres.ACCOUNTS,
                        user=postgres.BIOMETRIC, password=keys.database["biometric"], connect_timeout=5,
                        **postgres.CONNECTION_OPTIONS)


def test_the_migrated_schema_matches_the_models(databases):
    for engine, base in ((databases.accounts, AccountsBase), (databases.biometric, BiometricBase)):
        with engine.connect() as conn:
            assert compare_metadata(MigrationContext.configure(conn), base.metadata) == []


def test_each_account_keeps_its_own_theme(client):
    register(client)
    token = sign_in(client)
    assert client.get("/api/me", headers=auth(token)).json()["account"]["theme"] == "system"
    assert client.post("/api/me/theme", json={"theme": "dark"}, headers=auth(token)).status_code == 204
    assert client.get("/api/me", headers=auth(sign_in(client))).json()["account"]["theme"] == "dark"
    assert error(client.post("/api/me/theme", json={"theme": "blue"}, headers=auth(token))) == (400, "invalid_theme")
    assert error(client.post("/api/me/theme", json={"theme": "dark"})) == (401, "not_signed_in")

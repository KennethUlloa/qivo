from flask import Flask, request
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from werkzeug.exceptions import BadRequest, Unauthorized

from qivo import Qivo
from qivo.db.sql.auth import (
    AuthBase,
    DBSessionAuthenticator,
    Permission,
    Role,
    User,
    role_permissions,
    user_roles,
)
from qivo.db.sql.extensions import SQLEngine
from qivo.guards import WithAll


def test_auth_relationships_and_timestamp_metadata(tmp_path):
    for model in (User, Role, Permission):
        assert list(model.__table__.columns.keys())[-2:] == [
            "created_at",
            "updated_at",
        ]
    assert list(user_roles.columns.keys())[-1] == "created_at"
    assert list(role_permissions.columns.keys())[-1] == "created_at"

    engine = create_engine(f"sqlite:///{tmp_path}/auth.db")
    AuthBase.metadata.create_all(engine)

    try:
        with Session(engine) as session:
            permission = Permission(key="users:read", description="Read users")
            role = Role(key="admin", name="Administrator", permissions=[permission])
            user = User(username="ana", roles=[role])
            user.set_password("secreto")
            session.add(user)
            session.commit()

            user_id = user.id
            session.expire_all()
            user = session.get(User, user_id)

            assert user is not None
            assert user.roles[0].users[0].username == "ana"
            assert user.roles[0].permissions[0].roles[0].key == "admin"
            assert user.created_at is not None
            assert user.updated_at is not None
            assert user.roles[0].created_at is not None
            assert user.roles[0].permissions[0].updated_at is not None
            assert session.scalar(select(user_roles.c.created_at)) is not None
            assert session.scalar(select(role_permissions.c.created_at)) is not None

        assert User.__table__.c.updated_at.onupdate is not None
        assert Role.__table__.c.updated_at.onupdate is not None
        assert Permission.__table__.c.updated_at.onupdate is not None
    finally:
        AuthBase.metadata.drop_all(engine)
        engine.dispose()


def test_db_session_authenticator_works_as_a_qivo_auth_gate(tmp_path):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY="test-secret",
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path}/auth-gate.db",
    )
    database = SQLEngine(app, model=AuthBase)
    AuthBase.metadata.create_all(database.engine)
    with Session(database.engine) as db_session:
        permission = Permission(key="users:read", description="Read users")
        role = Role(key="reader", name="Reader", permissions=[permission])
        user = User(username="ana", roles=[role])
        user.set_password("secreto")
        db_session.add(user)
        db_session.commit()

    authenticator = DBSessionAuthenticator()
    qivo = Qivo(app, guards={"web": authenticator})

    @app.post("/login")
    def login():
        user = authenticator.authenticate(request.get_json())
        return {"id": user.id}

    @app.get("/private")
    @qivo.view(auth=True, policies=[WithAll(["users:read"])])
    def private():
        return {"user_id": authenticator.authenticated().id}

    try:
        with app.test_client() as client:
            assert client.get("/private").status_code == 401
            login_response = client.post(
                "/login", json={"username": "ana", "password": "secreto"}
            )
            assert login_response.status_code == 200

            response = client.get("/private")

            assert response.status_code == 200
            assert response.get_json() == {"user_id": login_response.get_json()["id"]}
    finally:
        AuthBase.metadata.drop_all(database.engine)
        database.dispose()


def test_db_session_authenticator_uses_the_current_gate_contract():
    app = Flask(__name__)
    authenticator = DBSessionAuthenticator()

    with app.test_request_context("/"):
        assert authenticator.authenticated() is None

        try:
            authenticator.require_authentication()
        except Unauthorized:
            pass
        else:
            raise AssertionError("Unauthenticated requests must be rejected")

        try:
            authenticator.authenticate()
        except BadRequest as error:
            assert error.description == "auth.missing_credentials"
        else:
            raise AssertionError("Credential authentication requires input data")

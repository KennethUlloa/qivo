from flask import g, session
from sqlalchemy import Column, DateTime, ForeignKey, Table, func, select
from sqlalchemy.orm import (
    Mapped,
    Session,
    mapped_column,
    relationship,
    selectinload,
    sessionmaker,
)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.exceptions import BadRequest, Unauthorized

from qivo.db.sql.mixins import TimestampMixin
from qivo.db.sql.model import model_base
from qivo.guards import Authenticated, Authenticator


AuthBase = model_base("AuthBase")


class User(TimestampMixin, AuthBase):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(unique=True, nullable=False)
    password: Mapped[str] = mapped_column(nullable=False)
    active: Mapped[bool] = mapped_column(default=True, nullable=False)
    roles: Mapped[list["Role"]] = relationship(
        secondary="user_roles", back_populates="users"
    )

    def check_password(self, password: str) -> bool:
        """Check if the given password matches the stored password."""
        return check_password_hash(self._password, password)

    def set_password(self, password: str) -> None:
        """Set the user's password."""
        self._password = generate_password_hash(password)

    def get_id(self) -> int:
        return self.id

    def is_active(self) -> bool:
        return self.active

    def get_permissions(self) -> list[str]:
        permissions = []
        for role in self.roles:
            for permission in role.permissions:
                permissions.append(permission.key)
        return permissions

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "username": self.username,
            "active": self.active,
            "permissions": self.get_permissions(),
            "roles": [role.key for role in self.roles],
        }


class Role(TimestampMixin, AuthBase):
    __tablename__ = "roles"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(unique=True, nullable=False)
    name: Mapped[str] = mapped_column(unique=True, nullable=False)
    users: Mapped[list[User]] = relationship(
        secondary="user_roles", back_populates="roles"
    )
    permissions: Mapped[list["Permission"]] = relationship(
        secondary="role_permissions", back_populates="roles"
    )

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "key": self.key,
            "name": self.name,
            "permissions": [permission.key for permission in self.permissions],
        }


class Permission(TimestampMixin, AuthBase):
    __tablename__ = "permissions"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(unique=True, nullable=False)
    description: Mapped[str] = mapped_column()
    roles: Mapped[list[Role]] = relationship(
        secondary="role_permissions", back_populates="permissions"
    )

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "key": self.key,
            "description": self.description,
        }


user_roles = Table(
    "user_roles",
    AuthBase.metadata,
    Column("user_id", ForeignKey("users.id"), primary_key=True),
    Column("role_id", ForeignKey("roles.id"), primary_key=True),
    Column(
        "created_at",
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    ),
)

role_permissions = Table(
    "role_permissions",
    AuthBase.metadata,
    Column("role_id", ForeignKey("roles.id"), primary_key=True),
    Column("permission_id", ForeignKey("permissions.id"), primary_key=True),
    Column(
        "created_at",
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    ),
)


class DBSessionAuthenticator(Authenticator):
    """A simple database-backed authenticator for users."""

    def __init__(
        self,
        session_factory: sessionmaker[Session] | None = None,
        model: type[User] | None = None,
    ):
        self.session_factory = session_factory
        self.model = model or User

    def authenticate(self, data: dict | None = None) -> User:
        """Authenticate credentials or validate the current Flask login."""
        if data is None:
            raise BadRequest("auth.missing_credentials")

        username = data.get("username")
        password = data.get("password")

        if not isinstance(username, str) or not isinstance(password, str):
            raise Unauthorized("auth.invalid_credentials")

        with self._session_factory()() as db_session:
            user = db_session.scalar(
                select(self.model)
                .options(
                    selectinload(self.model.roles).selectinload(Role.permissions)
                )
                .where(self.model.username == username)
            )
            if user is None or not user.is_active() or not user.check_password(password):
                raise Unauthorized("auth.invalid_credentials")

            user_id = user.id

        setattr(g, "authenticated_user", user)
        session["user_id"] = user_id
        return user

    def authenticated(self) -> User:
        user_id = session.get("user_id")

        if user_id is None:
            return None

        authenticated_user = getattr(g, "authenticated_user", None)

        if authenticated_user is not None and authenticated_user.id == user_id:
            return authenticated_user

        with self._session_factory()() as db_session:
            user = db_session.scalar(
                select(self.model)
                .options(
                    selectinload(self.model.roles).selectinload(Role.permissions)
                )
                .where(self.model.id == user_id)
            )
            
        setattr(g, "authenticated_user", user)
        return user

    def permissions(self) -> list[str]:
        user = self.authenticated()
        return user.get_permissions()

    def has_permission(self, permission: str) -> bool:
        scope = permission.split(":")[0]
        permissions = self.permissions()

        return (
            permission in permissions
            or f"{scope}:*" in permissions
            or "*:*" in permissions
        )

    def logout(self) -> None:
        setattr(g, "authenticated_user", None)
        session.clear()

    
    def require_authentication(self):
        if not self.authenticated():
            raise Unauthorized()

    def _session_factory(self) -> sessionmaker[Session]:
        if self.session_factory is not None:
            return self.session_factory

        try:
            factory = g.session_factory
        except RuntimeError as error:
            raise RuntimeError(
                "DBSessionAuthenticator requires SQLEngine to attach a request "
                "session factory"
            ) from error
        if factory is None:
            raise RuntimeError(
                "DBSessionAuthenticator requires SQLEngine to attach a request "
                "session factory"
            )
        return factory

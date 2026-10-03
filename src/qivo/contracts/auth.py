from typing import Protocol


class AuthenticatedUser(Protocol):
    def get_id(self) -> str:
        """
        Get the user id
        """
        ...
    def get_permissions(self) -> list[str]:
        """
        Get the user permissions
        """
        ...
    def is_active(self) -> bool:
        """
        Check if the user is active
        """
        ...
    def any_permission(self, permissions: list[str]) -> bool:
        """
        Check if the user has any of the given permissions
        """
        ...
    def all_permissions(self, permissions: list[str]) -> bool:
        """
        Check if the user has all of the given permissions
        """
        ...


class AuthGuard(Protocol):
    def check_logged_in(self) -> bool:
        """
        Check if the user is logged in
        """
        pass

    def get_current_user(self, required: bool = False) -> AuthenticatedUser | None:
        """
        Get the current user
        """
        pass

    def permission_check_failed(self):
        """
        Handle permission check failure, raise an exception or return a Flask valid response: str, dict, etc...
        """
        pass

    def logged_in_check_failed(self):
        """
        Handle logged in check failure, raise an exception or return a Flask valid response: str, dict, etc...
        """
        pass

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Callable, Protocol

if TYPE_CHECKING:
    from qivo import Qivo


class ViewExtension(Protocol):
    def wrap_view(
        self,
        app: Qivo,
        view_func: Callable[..., Any],
        *,
        options: Mapping[str, Any],
    ) -> Callable[..., Any]: ...

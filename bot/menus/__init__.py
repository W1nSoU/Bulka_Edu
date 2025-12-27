"""Menu modules for the Bulka bot."""

from .manager import register_manager_handlers
from .developer import register_developer_menu_handlers

__all__ = [
    "register_manager_handlers",
    "register_developer_menu_handlers",
]

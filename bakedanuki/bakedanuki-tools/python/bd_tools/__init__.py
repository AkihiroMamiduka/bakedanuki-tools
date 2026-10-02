# coding: utf-8
"""bakedanuki Mayaツール群の公開API。"""

# バージョンと利用者向けAPIをpackage直下へ公開する
from . import _version
from ._dev.lifecycle import (
    ReloadDisposalError,
    register_reload_disposer,
    unregister_reload_disposer,
)
from ._dev.reload import reload_package
from .menu import install_menu, uninstall_menu

__version__ = _version.__version__

__all__ = [
    "ReloadDisposalError",
    "__version__",
    "install_menu",
    "register_reload_disposer",
    "reload_package",
    "uninstall_menu",
    "unregister_reload_disposer",
]

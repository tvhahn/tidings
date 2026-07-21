"""Guard: every public model in a models submodule is re-exported by the barrel.

Routers import their Pydantic schemas from ``src.api.models`` (the barrel), which
hand-curates an ``__all__``. When a submodule gains a model but the barrel is not
updated, the drift is silent until an import breaks. This walks every submodule of
``src.api.models`` and asserts each public model it *defines* appears in
``src.api.models.__all__``.

"Public" respects a submodule's own ``__all__`` when it declares one (the
authoritative statement of that module's public surface); otherwise it means every
non-underscore name. Only ``BaseModel`` subclasses actually defined in the module
(not imported into it) are checked.
"""

import importlib
import inspect
import pkgutil

import pytest
from pydantic import BaseModel

import src.api.models as barrel


def _model_module_names() -> list[str]:
    """Every submodule of ``src.api.models`` (``__init__`` is never yielded)."""
    return sorted(info.name for info in pkgutil.iter_modules(barrel.__path__))


def _public_names(module: object) -> list[str]:
    """The module's declared public surface — its ``__all__`` or non-underscore names."""
    declared = getattr(module, "__all__", None)
    if declared is not None:
        return list(declared)
    return [name for name in vars(module) if not name.startswith("_")]


@pytest.mark.parametrize("module_name", _model_module_names())
def test_submodule_public_models_are_exported_by_barrel(module_name: str) -> None:
    module = importlib.import_module(f"src.api.models.{module_name}")
    barrel_exports = set(barrel.__all__)

    defined_models = [
        name
        for name in _public_names(module)
        if inspect.isclass(getattr(module, name, None))
        and issubclass(getattr(module, name), BaseModel)
        and getattr(module, name).__module__ == module.__name__
    ]

    missing = sorted(name for name in defined_models if name not in barrel_exports)
    assert not missing, (
        f"src.api.models.{module_name} defines public model(s) absent from "
        f"src.api.models.__all__: {missing}. Add them to the barrel's import block "
        "and __all__ so routers can import them from src.api.models."
    )

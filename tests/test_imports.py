"""Every module must at least import: catches syntax errors in entry points that no
other test exercises (e.g. the preview and check commands run only in Actions)."""

import importlib
import pkgutil

import pytest

import linkedin_bot

MODULES = sorted(
    name for _, name, _ in pkgutil.walk_packages(linkedin_bot.__path__, "linkedin_bot.")
)


@pytest.mark.parametrize("module", MODULES)
def test_module_imports(module):
    importlib.import_module(module)

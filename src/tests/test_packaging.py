"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Guard that the build manifest ships every top-level helper module.

The wheel/sdist enumerates bare-name modules in ``[tool.setuptools].py-modules``;
``packages.find`` only collects the ``server`` and ``client`` packages. A new
``src/*.py`` helper that is imported by those packages but omitted from
``py-modules`` imports fine in the source tree (pytest adds ``src`` to the path)
yet raises ``ModuleNotFoundError`` from an installed package. This test keeps the
manifest in sync with the files on disk.
"""

import tomllib
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "src"


def test_all_top_level_modules_are_packaged():
    """Every bare-name ``src/*.py`` module must be listed in py-modules."""
    pyproject = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    declared = set(pyproject["tool"]["setuptools"]["py-modules"])
    on_disk = {path.stem for path in _SRC.glob("*.py")}

    missing = on_disk - declared
    assert not missing, f"top-level modules missing from [tool.setuptools].py-modules: {sorted(missing)}"

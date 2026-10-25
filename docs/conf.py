"""Sphinx configuration for the library and protocol reference."""

import os
from importlib.metadata import version

project = "BatteryView for Python"
author = "BatteryView contributors"
release = version("batteryview")
version = release
extensions = ["sphinx.ext.autodoc", "sphinxarg.ext", "sphinx_copybutton"]
autodoc_typehints = "none"
html_theme = "furo"
html_baseurl = os.environ.get("READTHEDOCS_CANONICAL_URL", "")
html_theme_options = {
    "source_repository": "https://github.com/nijel/batteryview/",
    "source_branch": "main",
    "source_directory": "docs/",
}
exclude_patterns = ["_build"]

# Standard-library type; this offline build does not fetch intersphinx inventories.
nitpick_ignore = [("py:class", "pathlib.Path")]

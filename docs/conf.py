"""Sphinx configuration for the library and protocol reference."""

import os
from importlib.metadata import version

project = "Pylontech Tools"
author = "Pylontech Tools contributors"
release = version("pylontech-tools")
version = release
extensions = ["sphinx.ext.autodoc", "sphinxarg.ext", "sphinx_copybutton"]
autodoc_typehints = "none"
html_theme = "furo"
html_baseurl = os.environ.get(
    "READTHEDOCS_CANONICAL_URL", "https://pylontech-tools.readthedocs.io/en/latest/"
)
html_theme_options = {
    "source_repository": "https://github.com/nijel/pylontech-tools/",
    "source_branch": "main",
    "source_directory": "docs/",
}
exclude_patterns = ["_build"]

# Standard-library type; this offline build does not fetch intersphinx inventories.
nitpick_ignore = [("py:class", "pathlib.Path")]

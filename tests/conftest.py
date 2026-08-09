"""
Pytest configuration for the test suite.

This runs before any test module is imported — which matters because
cli.py loads plugins from EXPERTIES_PLUGINS_DIR (or the real
~/.experties/plugins/ if that's unset) the moment it's imported, as a
module-level side effect. Without forcing this here, running the test
suite on a machine that has real plugins installed would execute those
plugins' register() functions just from collecting tests — exactly the
kind of hidden coupling a test suite should never have.

os.environ.setdefault(...) is used rather than a fixture because this
needs to be in place before import, not before any individual test
runs — by the time a fixture could set it, `from experties.cli import
app` has already happened during collection.
"""

import os
import tempfile

os.environ.setdefault(
    "EXPERTIES_PLUGINS_DIR",
    os.path.join(tempfile.gettempdir(), "experties_test_no_plugins_here"),
)
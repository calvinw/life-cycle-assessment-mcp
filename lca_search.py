"""Compatibility alias for :mod:`lca_core.search`."""

import sys

from lca_core import search as _search

sys.modules[__name__] = _search

"""Compatibility alias for :mod:`lca_core.engine`."""

import sys

from lca_core import engine as _engine

sys.modules[__name__] = _engine

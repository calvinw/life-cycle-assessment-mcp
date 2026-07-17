"""Compatibility alias for :mod:`lca_core.visualization`."""

import sys

from lca_core import visualization as _visualization

sys.modules[__name__] = _visualization

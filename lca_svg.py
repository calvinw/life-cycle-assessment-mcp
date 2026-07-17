"""Compatibility alias for :mod:`lca_core.svg_renderer`."""

import sys

from lca_core import svg_renderer as _renderer

sys.modules[__name__] = _renderer

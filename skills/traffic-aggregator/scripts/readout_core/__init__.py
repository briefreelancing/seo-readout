"""Readout core: shared parsing, normalizing and checking for Readout skills.

Source of truth lives in shared/readout_core. Each skill folder carries a copy
(skills/*/scripts/readout_core) so it works on its own when uploaded to Claude.
Run tools/sync_shared.py after editing this package.
"""

__version__ = "0.1.0"

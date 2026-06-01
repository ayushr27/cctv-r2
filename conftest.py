"""
Pytest bootstrap.

NOTE on the two `schemas` modules: the worker uses a flat `worker/schemas.py`
(imported bare as `schemas`) while the api uses an `api/schemas/` PACKAGE
(`schemas.events`, `schemas.responses`). Both cannot occupy the top-level name
`schemas` in one interpreter. So we do NOT put both `api/` and `worker/` on the
path globally. Instead each test file inserts the one source dir it needs at
import time, and CI runs the worker-scoped and api-scoped tests as separate
pytest invocations (with --cov-append) so the two `schemas` never collide.

This conftest only ensures the repo root is importable; per-scope path setup
lives in the individual test files.
"""

import os
import sys

ROOT = os.path.dirname(__file__)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

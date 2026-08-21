"""EVE Algo Lab Railway service."""

# Install append-only/shared historical-memory ownership before app.main creates
# the autonomous services. This prevents duplicate six-year Python object graphs.
from app.services import memory_guard_v1 as _memory_guard_v1  # noqa: F401

from __future__ import annotations

from app.h1_30m_research_api import build_h1_30m_router
from app.main import app, repo, require_admin


app.include_router(build_h1_30m_router(repo, require_admin))

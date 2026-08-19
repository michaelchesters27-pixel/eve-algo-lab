from __future__ import annotations

from app.four_ccb_bias_research_api import build_four_ccb_bias_router
from app.four_ccb_candidate_audit_api import build_four_ccb_candidate_audit_router
from app.four_ccb_research_api import build_four_ccb_router
from app.four_ccb_structure_research_api import build_four_ccb_structure_router
from app.h1_30m_research_api import build_h1_30m_router
from app.main import app, repo, require_admin


app.include_router(build_h1_30m_router(repo, require_admin))
app.include_router(build_four_ccb_router(repo, require_admin))
app.include_router(build_four_ccb_bias_router(repo, require_admin))
app.include_router(build_four_ccb_structure_router(repo, require_admin))
app.include_router(build_four_ccb_candidate_audit_router(repo, require_admin))
# Keep research routers on the Railway entrypoint so GitHub pushes redeploy them together.

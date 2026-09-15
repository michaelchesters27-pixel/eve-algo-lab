from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from app.services import strategy_lab as strategy_lab_module
from app.services.autonomy import number
from app.services.everyday_bot_hunt import build_everyday_specs


logger = logging.getLogger(__name__)


async def seed_everyday_queue(service: Any) -> int:
    """Seed the dedicated hunt even when the normal Strategy Lab queue is full.

    The standard Strategy Lab intentionally waits for its queue to fall below a
    floor before generating another batch. That is sensible for normal research,
    but it would make a newly requested Everyday Hunt sit behind hundreds of old
    jobs. This one-shot startup seed inserts the strict Everyday candidates now;
    their higher research priority lets the worker start testing them without
    deleting or weakening the existing queue.
    """

    state = await service.repo.get_strategy_lab_state("XAU/USD", strategy_lab_module.SNAPSHOT_INTERVAL) or {}
    generation = max(1, int(number(state.get("generator_generation"), 1)))
    sources = await service.repo.list_strategy_source_research(
        "XAU/USD", strategy_lab_module.SNAPSHOT_INTERVAL, limit=250
    )
    specs = build_everyday_specs(sources, generation)
    if not specs:
        return 0
    await service.repo.upsert_strategy_candidates(specs)
    await service.repo.log_event(
        "info",
        "everyday-bot-hunt",
        "Everyday Hunt seeded",
        {
            "generation": generation,
            "source_count": len(sources),
            "candidate_count": len(specs),
            "target_pf": 1.50,
            "target_full_history_opportunities": 1000,
            "target_daily_coverage": 0.60,
        },
    )
    return len(specs)


def apply_everyday_startup_seed() -> None:
    if getattr(strategy_lab_module.StrategyLabService, "_eve_everyday_startup_seed_applied", False):
        return

    original_ensure_queue = strategy_lab_module.StrategyLabService._ensure_queue

    async def ensure_queue_with_immediate_hunt(self):
        now = strategy_lab_module.utc_now()
        seeded = bool(getattr(self, "_everyday_hunt_seeded", False))
        retry_after = getattr(self, "_everyday_hunt_retry_after", None)
        if not seeded and (retry_after is None or now >= retry_after):
            try:
                count = await seed_everyday_queue(self)
                self._everyday_hunt_seeded = True
                logger.info("Seeded %s Everyday Hunt candidates on startup", count)
            except Exception:
                # The ordinary Strategy Lab must keep running even if this extra
                # research lane encounters a transient database problem.
                self._everyday_hunt_retry_after = now + timedelta(minutes=5)
                logger.exception("Everyday Hunt startup seed failed; will retry")
        await original_ensure_queue(self)

    strategy_lab_module.StrategyLabService._ensure_queue = ensure_queue_with_immediate_hunt
    setattr(strategy_lab_module.StrategyLabService, "_eve_everyday_startup_seed_applied", True)

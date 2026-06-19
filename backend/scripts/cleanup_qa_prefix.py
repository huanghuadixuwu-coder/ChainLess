"""Hard-delete QA records for one owned automation prefix.

This script is intentionally not exposed as an API. It is used by local QA
verification to remove durable records that product APIs correctly soft-delete
or archive for user safety.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy import String, cast, delete, func, or_, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.deps import _async_session_factory
from app.models.capability import CapabilityAnalysisJob, CapabilityCandidate
from app.models.conversation import Conversation, Message
from app.models.memory import Memory
from app.models.skill import Skill
from app.models.worker import Worker

ALLOWED_PREFIX = "qa-v2-capability-"


def _like(prefix: str) -> str:
    return f"%{prefix}%"


async def _count_remaining(db, prefix: str) -> dict[str, int]:
    pattern = _like(prefix)
    conversation_ids = select(Message.conversation_id).where(Message.content.ilike(pattern))
    counts: dict[str, int] = {}
    counts["conversations"] = int(
        (
            await db.execute(
                select(func.count())
                .select_from(Conversation)
                .where(or_(Conversation.title.ilike(pattern), Conversation.id.in_(conversation_ids)))
            )
        ).scalar()
        or 0
    )
    counts["capability_candidates"] = int(
        (
            await db.execute(
                select(func.count())
                .select_from(CapabilityCandidate)
                .where(
                    or_(
                        CapabilityCandidate.title.ilike(pattern),
                        CapabilityCandidate.body.ilike(pattern),
                        CapabilityCandidate.dedupe_key.ilike(pattern),
                        cast(CapabilityCandidate.evidence, String).ilike(pattern),
                        cast(CapabilityCandidate.payload, String).ilike(pattern),
                        cast(CapabilityCandidate.metadata_, String).ilike(pattern),
                    )
                )
            )
        ).scalar()
        or 0
    )
    counts["capability_analysis_jobs"] = int(
        (
            await db.execute(
                select(func.count())
                .select_from(CapabilityAnalysisJob)
                .where(
                    or_(
                        CapabilityAnalysisJob.source_run_id.ilike(pattern),
                        cast(CapabilityAnalysisJob.payload, String).ilike(pattern),
                        cast(CapabilityAnalysisJob.result_metadata, String).ilike(pattern),
                    )
                )
            )
        ).scalar()
        or 0
    )
    counts["workers"] = int(
        (
            await db.execute(
                select(func.count())
                .select_from(Worker)
                .where(
                    or_(
                        Worker.name.ilike(pattern),
                        Worker.description.ilike(pattern),
                        cast(Worker.trigger, String).ilike(pattern),
                        cast(Worker.policy, String).ilike(pattern),
                        cast(Worker.metadata_, String).ilike(pattern),
                    )
                )
            )
        ).scalar()
        or 0
    )
    counts["memories"] = int(
        (
            await db.execute(
                select(func.count())
                .select_from(Memory)
                .where(
                    or_(
                        Memory.name.ilike(pattern),
                        Memory.content.ilike(pattern),
                        cast(Memory.tags, String).ilike(pattern),
                        cast(Memory.meta_data, String).ilike(pattern),
                    )
                )
            )
        ).scalar()
        or 0
    )
    counts["skills"] = int(
        (
            await db.execute(
                select(func.count())
                .select_from(Skill)
                .where(
                    or_(
                        Skill.name.ilike(pattern),
                        Skill.description.ilike(pattern),
                        cast(Skill.trigger_terms, String).ilike(pattern),
                        cast(Skill.metadata_, String).ilike(pattern),
                    )
                )
            )
        ).scalar()
        or 0
    )
    return counts


async def cleanup(prefix: str, *, dry_run: bool) -> dict:
    if not prefix.startswith(ALLOWED_PREFIX):
        raise SystemExit(f"Refusing to clean prefix outside {ALLOWED_PREFIX!r}: {prefix!r}")

    pattern = _like(prefix)
    async with _async_session_factory() as db:
        before = await _count_remaining(db, prefix)
        deleted = dict.fromkeys(before, 0)
        if not dry_run:
            conversation_ids = select(Message.conversation_id).where(Message.content.ilike(pattern))
            statements = [
                (
                    "capability_candidates",
                    delete(CapabilityCandidate).where(
                        or_(
                            CapabilityCandidate.title.ilike(pattern),
                            CapabilityCandidate.body.ilike(pattern),
                            CapabilityCandidate.dedupe_key.ilike(pattern),
                            cast(CapabilityCandidate.evidence, String).ilike(pattern),
                            cast(CapabilityCandidate.payload, String).ilike(pattern),
                            cast(CapabilityCandidate.metadata_, String).ilike(pattern),
                        )
                    ),
                ),
                (
                    "capability_analysis_jobs",
                    delete(CapabilityAnalysisJob).where(
                        or_(
                            CapabilityAnalysisJob.source_run_id.ilike(pattern),
                            cast(CapabilityAnalysisJob.payload, String).ilike(pattern),
                            cast(CapabilityAnalysisJob.result_metadata, String).ilike(pattern),
                        )
                    ),
                ),
                (
                    "memories",
                    delete(Memory).where(
                        or_(
                            Memory.name.ilike(pattern),
                            Memory.content.ilike(pattern),
                            cast(Memory.tags, String).ilike(pattern),
                            cast(Memory.meta_data, String).ilike(pattern),
                        )
                    ),
                ),
                (
                    "skills",
                    delete(Skill).where(
                        or_(
                            Skill.name.ilike(pattern),
                            Skill.description.ilike(pattern),
                            cast(Skill.trigger_terms, String).ilike(pattern),
                            cast(Skill.metadata_, String).ilike(pattern),
                        )
                    ),
                ),
                (
                    "workers",
                    delete(Worker).where(
                        or_(
                            Worker.name.ilike(pattern),
                            Worker.description.ilike(pattern),
                            cast(Worker.trigger, String).ilike(pattern),
                            cast(Worker.policy, String).ilike(pattern),
                            cast(Worker.metadata_, String).ilike(pattern),
                        )
                    ),
                ),
                (
                    "conversations",
                    delete(Conversation).where(
                        or_(Conversation.title.ilike(pattern), Conversation.id.in_(conversation_ids))
                    ),
                ),
            ]
            for label, statement in statements:
                result = await db.execute(statement.execution_options(synchronize_session=False))
                deleted[label] = int(result.rowcount or 0)
            await db.commit()
        after = await _count_remaining(db, prefix)
    return {"prefix": prefix, "dry_run": dry_run, "before": before, "deleted": deleted, "after": after}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(cleanup(args.prefix, dry_run=args.dry_run)), sort_keys=True))


if __name__ == "__main__":
    main()

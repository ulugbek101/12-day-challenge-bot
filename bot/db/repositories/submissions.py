from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from bot.db.models import Client, ClientStatus, ScreenshotKind, Submission, SubmissionStatus
from bot.services.phone import digits_only
from bot.services.timefmt import utcnow

PAGE_SIZE = 10


def _latest_submission_ids_subquery():
    return (
        select(Submission.client_id, func.max(Submission.id).label("max_id"))
        .group_by(Submission.client_id)
        .subquery()
    )


async def create(
    session: AsyncSession,
    *,
    client_id: int,
    full_name: str,
    phone: str,
    screenshot_file_id: str,
    screenshot_kind: ScreenshotKind,
) -> Submission:
    submission = Submission(
        client_id=client_id,
        full_name=full_name,
        phone=phone,
        phone_normalized=digits_only(phone),
        screenshot_file_id=screenshot_file_id,
        screenshot_kind=screenshot_kind,
        status=SubmissionStatus.pending,
        created_at=utcnow(),
    )
    session.add(submission)
    await session.flush()
    return submission


async def get_by_id(session: AsyncSession, submission_id: int) -> Submission | None:
    return await session.get(Submission, submission_id)


async def get_latest_for_client(session: AsyncSession, client_id: int) -> Submission | None:
    stmt = (
        select(Submission)
        .where(Submission.client_id == client_id)
        .order_by(Submission.id.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_for_client(session: AsyncSession, client_id: int) -> list[Submission]:
    """All attempts for a client, newest first (for the history view)."""
    stmt = (
        select(Submission)
        .where(Submission.client_id == client_id)
        .order_by(Submission.id.desc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def count_for_client(session: AsyncSession, client_id: int) -> int:
    stmt = select(func.count()).select_from(Submission).where(Submission.client_id == client_id)
    return (await session.execute(stmt)).scalar_one()


async def list_by_status(
    session: AsyncSession, status: ClientStatus, page: int, page_size: int = PAGE_SIZE
) -> tuple[list[tuple[Client, Submission]], int]:
    """Clients whose *current* status matches, with their latest submission.

    Pending is FIFO (oldest first); approved/rejected are newest first.
    """
    latest = _latest_submission_ids_subquery()
    latest_submission = aliased(Submission)
    order_col = (
        latest_submission.created_at.asc()
        if status == ClientStatus.pending
        else latest_submission.created_at.desc()
    )
    stmt = (
        select(Client, latest_submission)
        .join(latest, Client.id == latest.c.client_id)
        .join(latest_submission, latest_submission.id == latest.c.max_id)
        .where(Client.status == status)
        .order_by(order_col)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await session.execute(stmt)).all()
    total = await session.scalar(
        select(func.count()).select_from(Client).where(Client.status == status)
    )
    return [(row[0], row[1]) for row in rows], total or 0


async def search(
    session: AsyncSession, query: str, page: int, page_size: int = PAGE_SIZE
) -> tuple[list[tuple[Client, Submission]], int]:
    """Case-insensitive partial match on name/phone/username, exact match on telegram id.

    Phone matching ignores formatting: the query's digits are compared against
    submissions.phone_normalized.
    """
    like = f"%{query}%"
    digits = digits_only(query)

    matches: list = [
        Submission.full_name.like(like),
        Client.username.like(like),
    ]
    if digits:
        matches.append(Submission.phone_normalized.like(f"%{digits}%"))
    if query.lstrip("-").isdigit():
        matches.append(Client.telegram_id == int(query))

    matching_client_ids = (
        select(Submission.client_id)
        .join(Client, Client.id == Submission.client_id)
        .where(or_(*matches))
        .distinct()
        .subquery()
    )

    latest = _latest_submission_ids_subquery()
    latest_submission = aliased(Submission)
    stmt = (
        select(Client, latest_submission)
        .join(latest, Client.id == latest.c.client_id)
        .join(latest_submission, latest_submission.id == latest.c.max_id)
        .where(Client.id.in_(select(matching_client_ids.c.client_id)))
        .order_by(latest_submission.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await session.execute(stmt)).all()

    total = await session.scalar(
        select(func.count())
        .select_from(Client)
        .where(Client.id.in_(select(matching_client_ids.c.client_id)))
    )
    return [(row[0], row[1]) for row in rows], total or 0


async def set_review_result(
    session: AsyncSession,
    *,
    submission_id: int,
    client_id: int,
    new_status: SubmissionStatus,
    admin_telegram_id: int,
    admin_name: str,
) -> bool:
    """Atomically move a *pending* submission (and its client) to approved/rejected.

    Returns False (no-op) if the submission was no longer pending, so the caller
    can show "Already processed by <admin>" instead of double-processing it.
    """
    now = utcnow()
    result = await session.execute(
        update(Submission)
        .where(Submission.id == submission_id, Submission.status == SubmissionStatus.pending)
        .values(
            status=new_status,
            reviewed_by=admin_telegram_id,
            reviewed_by_name=admin_name,
            reviewed_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount == 0:
        # Someone else got there first; make sure the caller sees *their* result.
        await session.get(Submission, submission_id, populate_existing=True)
        return False

    client_status = (
        ClientStatus.approved if new_status == SubmissionStatus.approved else ClientStatus.rejected
    )
    await session.execute(
        update(Client)
        .where(Client.id == client_id)
        .values(status=client_status, updated_at=now)
        .execution_options(synchronize_session=False)
    )
    # Bulk UPDATEs bypass the identity map; refresh any already-loaded objects.
    await session.get(Submission, submission_id, populate_existing=True)
    await session.get(Client, client_id, populate_existing=True)
    return True

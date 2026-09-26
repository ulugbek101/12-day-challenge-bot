from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import InviteLink
from bot.services.timefmt import utcnow


async def create(
    session: AsyncSession,
    *,
    client_id: int,
    submission_id: int,
    link: str,
    name: str,
    expires_at: datetime,
) -> InviteLink:
    invite = InviteLink(
        client_id=client_id,
        submission_id=submission_id,
        link=link,
        name=name,
        created_at=utcnow(),
        expires_at=expires_at,
        sent_to_user=False,
    )
    session.add(invite)
    await session.flush()
    return invite


async def get_by_id(session: AsyncSession, invite_id: int) -> InviteLink | None:
    return await session.get(InviteLink, invite_id)


async def get_by_link(session: AsyncSession, link: str) -> InviteLink | None:
    stmt = select(InviteLink).where(InviteLink.link == link)
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_current_for_client(session: AsyncSession, client_id: int) -> InviteLink | None:
    """Most recently created invite link for a client, regardless of its state."""
    stmt = (
        select(InviteLink)
        .where(InviteLink.client_id == client_id)
        .order_by(InviteLink.id.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_active_for_client(session: AsyncSession, client_id: int) -> InviteLink | None:
    """The one link that is still usable: not revoked, not used, not expired."""
    now = utcnow()
    stmt = (
        select(InviteLink)
        .where(
            InviteLink.client_id == client_id,
            InviteLink.revoked_at.is_(None),
            InviteLink.used_at.is_(None),
            InviteLink.expires_at > now,
        )
        .order_by(InviteLink.id.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def revoke(session: AsyncSession, invite_id: int) -> None:
    invite = await session.get(InviteLink, invite_id)
    if invite is None or invite.revoked_at is not None or invite.used_at is not None:
        return
    invite.revoked_at = utcnow()


async def mark_used(session: AsyncSession, invite_id: int) -> None:
    invite = await session.get(InviteLink, invite_id)
    if invite is None:
        return
    invite.used_at = utcnow()


async def mark_send_result(
    session: AsyncSession, invite_id: int, *, success: bool, error: str | None = None
) -> None:
    invite = await session.get(InviteLink, invite_id)
    if invite is None:
        return
    invite.sent_to_user = success
    invite.send_error = None if success else error


async def list_due_for_reminder(session: AsyncSession, *, within_hours: int) -> list[InviteLink]:
    """Active, unused, non-revoked links expiring within `within_hours` with no reminder sent yet."""
    now = utcnow()
    from datetime import timedelta

    horizon = now + timedelta(hours=within_hours)
    stmt = select(InviteLink).where(
        InviteLink.reminded_at.is_(None),
        InviteLink.revoked_at.is_(None),
        InviteLink.used_at.is_(None),
        InviteLink.expires_at > now,
        InviteLink.expires_at <= horizon,
    )
    return list((await session.execute(stmt)).scalars().all())


async def mark_reminded(session: AsyncSession, invite_id: int) -> None:
    invite = await session.get(InviteLink, invite_id)
    if invite is None:
        return
    invite.reminded_at = utcnow()


async def list_newly_expired(session: AsyncSession) -> list[InviteLink]:
    """Links past expiry, never used/revoked, not yet flagged as expired-notified."""
    now = utcnow()
    stmt = select(InviteLink).where(
        InviteLink.expired_notified_at.is_(None),
        InviteLink.revoked_at.is_(None),
        InviteLink.used_at.is_(None),
        InviteLink.expires_at <= now,
    )
    return list((await session.execute(stmt)).scalars().all())


async def mark_expired_notified(session: AsyncSession, invite_id: int) -> None:
    invite = await session.get(InviteLink, invite_id)
    if invite is None:
        return
    invite.expired_notified_at = utcnow()

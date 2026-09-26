"""Pure decision logic for chat_join_request: who gets approved into the channel.

A plain invite link (even member_limit=1) can be claimed by whoever clicks it
first, so admission is decided here against the invite_links + clients rows,
not by Telegram's own link mechanics.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime

from bot.db.models import ClientStatus, InviteLink


class JoinAction(str, enum.Enum):
    approve = "approve"
    decline = "decline"


@dataclass(frozen=True)
class JoinDecision:
    action: JoinAction
    reason: str


def decide(
    *,
    invite: InviteLink | None,
    client_status: ClientStatus | None,
    client_telegram_id: int | None,
    requester_telegram_id: int,
    now: datetime,
) -> JoinDecision:
    """Decide whether a chat_join_request should be approved.

    Approves only when: the invite link is known, not revoked, not already
    used, not expired, belongs to a client whose current status is approved,
    and the requester is that exact client (never an admin, never anyone else
    who got hold of the link).
    """
    if invite is None:
        return JoinDecision(JoinAction.decline, "unknown invite link")
    if invite.revoked_at is not None:
        return JoinDecision(JoinAction.decline, "link revoked")
    if invite.used_at is not None:
        return JoinDecision(JoinAction.decline, "link already used")
    if invite.expires_at <= now:
        return JoinDecision(JoinAction.decline, "link expired")
    if client_status != ClientStatus.approved:
        return JoinDecision(JoinAction.decline, "client is not approved")
    if client_telegram_id != requester_telegram_id:
        return JoinDecision(JoinAction.decline, "requester is not the approved client")
    return JoinDecision(JoinAction.approve, "ok")

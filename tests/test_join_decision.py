from datetime import datetime, timedelta

import pytest

from bot.db.models import ClientStatus, InviteLink
from bot.services.join_requests import JoinAction, decide

NOW = datetime(2026, 1, 1, 12, 0, 0)


def make_invite(**overrides) -> InviteLink:
    defaults = dict(
        id=1,
        client_id=1,
        submission_id=1,
        link="https://t.me/+abc",
        name="c1s1",
        created_at=NOW - timedelta(hours=1),
        expires_at=NOW + timedelta(hours=23),
        revoked_at=None,
        used_at=None,
        sent_to_user=True,
    )
    defaults.update(overrides)
    return InviteLink(**defaults)


def test_approves_the_correct_approved_client():
    invite = make_invite()
    result = decide(
        invite=invite,
        client_status=ClientStatus.approved,
        client_telegram_id=555,
        requester_telegram_id=555,
        now=NOW,
    )
    assert result.action == JoinAction.approve


def test_declines_unknown_link():
    result = decide(
        invite=None,
        client_status=ClientStatus.approved,
        client_telegram_id=555,
        requester_telegram_id=555,
        now=NOW,
    )
    assert result.action == JoinAction.decline
    assert "unknown" in result.reason


def test_declines_revoked_link():
    invite = make_invite(revoked_at=NOW - timedelta(minutes=1))
    result = decide(
        invite=invite,
        client_status=ClientStatus.approved,
        client_telegram_id=555,
        requester_telegram_id=555,
        now=NOW,
    )
    assert result.action == JoinAction.decline
    assert "revoked" in result.reason


def test_declines_already_used_link():
    invite = make_invite(used_at=NOW - timedelta(minutes=1))
    result = decide(
        invite=invite,
        client_status=ClientStatus.approved,
        client_telegram_id=555,
        requester_telegram_id=555,
        now=NOW,
    )
    assert result.action == JoinAction.decline
    assert "used" in result.reason


def test_declines_expired_link():
    invite = make_invite(expires_at=NOW - timedelta(minutes=1))
    result = decide(
        invite=invite,
        client_status=ClientStatus.approved,
        client_telegram_id=555,
        requester_telegram_id=555,
        now=NOW,
    )
    assert result.action == JoinAction.decline
    assert "expired" in result.reason


def test_declines_when_client_no_longer_approved():
    invite = make_invite()
    result = decide(
        invite=invite,
        client_status=ClientStatus.rejected,
        client_telegram_id=555,
        requester_telegram_id=555,
        now=NOW,
    )
    assert result.action == JoinAction.decline
    assert "approved" in result.reason


@pytest.mark.parametrize("requester_id", [999, -1001234567890])
def test_declines_someone_other_than_the_approved_client(requester_id):
    """Covers both a random user and an admin trying the client's link."""
    invite = make_invite()
    result = decide(
        invite=invite,
        client_status=ClientStatus.approved,
        client_telegram_id=555,
        requester_telegram_id=requester_id,
        now=NOW,
    )
    assert result.action == JoinAction.decline
    assert "not the approved client" in result.reason

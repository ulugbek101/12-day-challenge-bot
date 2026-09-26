"""Join requests, link expiry notices and the startup rights check, end to end."""
from __future__ import annotations

from datetime import timedelta

from aiogram.methods import (
    ApproveChatJoinRequest,
    DeclineChatJoinRequest,
    GetChatMember,
    RevokeChatInviteLink,
    SendMessage,
)
from sqlalchemy import select

from bot.db.models import Client, InviteLink
from bot.keyboards.callbacks import CardCb
from bot.services import expiry
from bot.services.startup import check_channel_rights, report_channel_problem
from bot.services.timefmt import utcnow
from tests import fakes
from tests.conftest import ADMIN_1, ADMIN_2, CHANNEL_ID
from tests.test_flow_admin import USER, last_panel_screen, open_card, row, seed_pending, tap


async def approved_with_link(app) -> tuple[int, InviteLink]:
    cid, sid = await seed_pending(app)
    await open_card(app, cid)
    await tap(app, CardCb(a="apy", cid=cid, sid=sid).pack())
    [invite] = await row(app, InviteLink)
    app.tg.reset()
    return cid, invite


# ------------------------------------------------------------------ join requests


async def test_the_right_client_is_admitted_and_admins_notified(app):
    cid, invite = await approved_with_link(app)
    await app.feed(fakes.join_request(USER, invite.link, channel_id=CHANNEL_ID))

    [approve] = app.tg.of(ApproveChatJoinRequest)
    assert (approve.chat_id, approve.user_id) == (CHANNEL_ID, USER)
    assert app.tg.of(DeclineChatJoinRequest) == []
    [invite] = await row(app, InviteLink)
    [client] = await row(app, Client, telegram_id=USER)
    assert invite.used_at is not None and invite.revoked_at is not None
    assert client.joined_at is not None
    assert [c.invite_link for c in app.tg.of(RevokeChatInviteLink)] == [invite.link]
    for admin in (ADMIN_1, ADMIN_2):
        notice = [c for c in app.tg.of(SendMessage) if c.chat_id == admin][-1]
        assert "Aziza Karimova вступил(а) в канал" in notice.text

    # the card now shows the join time
    await tap(app, CardCb(a="open", cid=cid, src="a").pack())
    caption, _ = last_panel_screen(app)
    assert "Вступил(а):" in caption and "использована" in caption


async def test_admin_or_anyone_else_using_the_link_is_declined(app):
    _, invite = await approved_with_link(app)
    for stranger in (ADMIN_1, 987654321):
        await app.feed(fakes.join_request(stranger, invite.link, channel_id=CHANNEL_ID))
    declined = [c.user_id for c in app.tg.of(DeclineChatJoinRequest)]
    assert declined == [ADMIN_1, 987654321]
    assert app.tg.of(ApproveChatJoinRequest) == []
    [invite] = await row(app, InviteLink)
    assert invite.used_at is None  # still usable by the real client

    await app.feed(fakes.join_request(USER, invite.link, channel_id=CHANNEL_ID))
    assert [c.user_id for c in app.tg.of(ApproveChatJoinRequest)] == [USER]


async def test_unknown_link_or_no_link_is_declined(app):
    await app.feed(fakes.join_request(USER, "https://t.me/+somethingElse", channel_id=CHANNEL_ID))
    await app.feed(fakes.join_request(USER, None, channel_id=CHANNEL_ID))
    assert len(app.tg.of(DeclineChatJoinRequest)) == 2


async def test_used_link_cannot_be_used_twice(app):
    _, invite = await approved_with_link(app)
    await app.feed(fakes.join_request(USER, invite.link, channel_id=CHANNEL_ID))
    await app.feed(fakes.join_request(USER, invite.link, channel_id=CHANNEL_ID))
    assert len(app.tg.of(ApproveChatJoinRequest)) == 1
    assert len(app.tg.of(DeclineChatJoinRequest)) == 1


async def test_expired_or_revoked_link_is_declined(app, session_factory):
    cid, invite = await approved_with_link(app)
    async with session_factory() as s:
        (await s.get(InviteLink, invite.id)).expires_at = utcnow() - timedelta(minutes=1)
        await s.commit()
    await app.feed(fakes.join_request(USER, invite.link, channel_id=CHANNEL_ID))
    assert len(app.tg.of(DeclineChatJoinRequest)) == 1

    old = invite
    async with session_factory() as s:
        (await s.get(InviteLink, old.id)).created_at = utcnow() - timedelta(minutes=5)
        await s.commit()
    await tap(app, CardCb(a="gen", cid=cid, sid=old.submission_id, src="a").pack())
    await app.feed(fakes.join_request(USER, old.link, channel_id=CHANNEL_ID))  # revoked now
    assert len(app.tg.of(DeclineChatJoinRequest)) == 2
    new = (await row(app, InviteLink))[-1]
    await app.feed(fakes.join_request(USER, new.link, channel_id=CHANNEL_ID))
    assert len(app.tg.of(ApproveChatJoinRequest)) == 1


async def test_join_requests_for_other_chats_are_ignored(app):
    _, invite = await approved_with_link(app)
    await app.feed(fakes.join_request(USER, invite.link, channel_id=-100999))
    assert app.tg.of(ApproveChatJoinRequest) == [] and app.tg.of(DeclineChatJoinRequest) == []


async def test_join_request_does_not_create_client_rows_for_strangers(app):
    await app.feed(fakes.join_request(55555, None, channel_id=CHANNEL_ID))
    async with app.session_factory() as s:
        assert (await s.execute(select(Client).where(Client.telegram_id == 55555))).first() is None


# ------------------------------------------------------------------ link expiry


async def test_expired_unused_link_notifies_admins_exactly_once(app, session_factory):
    cid, invite = await approved_with_link(app)
    async with session_factory() as s:
        (await s.get(InviteLink, invite.id)).expires_at = utcnow() - timedelta(minutes=1)
        await s.commit()

    await expiry.run_once(app.bot, session_factory)
    await expiry.run_once(app.bot, session_factory)  # e.g. next loop / after a restart

    for admin in (ADMIN_1, ADMIN_2):
        notices = [c for c in app.tg.of(SendMessage) if c.chat_id == admin and "истекла" in c.text]
        assert len(notices) == 1
        assert len(notices[0].reply_markup.inline_keyboard) == 1  # "Open"
    [invite] = await row(app, InviteLink)
    assert invite.expired_notified_at is not None
    # the client is NOT reminded or notified about expiry
    assert [c for c in app.tg.of(SendMessage) if c.chat_id == USER] == []


async def test_expiry_notice_is_retried_if_no_admin_got_it(app, session_factory):
    _, invite = await approved_with_link(app)
    async with session_factory() as s:
        (await s.get(InviteLink, invite.id)).expires_at = utcnow() - timedelta(minutes=1)
        await s.commit()
    app.tg.fail(SendMessage, chat_id=ADMIN_1)
    app.tg.fail(SendMessage, chat_id=ADMIN_2)
    await expiry.run_once(app.bot, session_factory)
    [invite] = await row(app, InviteLink)
    assert invite.expired_notified_at is None

    app.tg.clear_failures()
    await expiry.run_once(app.bot, session_factory)
    [invite] = await row(app, InviteLink)
    assert invite.expired_notified_at is not None


async def test_used_revoked_or_active_links_are_not_reported(app, session_factory):
    _, invite = await approved_with_link(app)
    await expiry.run_once(app.bot, session_factory)  # still active
    await app.feed(fakes.join_request(USER, invite.link, channel_id=CHANNEL_ID))  # used
    async with session_factory() as s:
        (await s.get(InviteLink, invite.id)).expires_at = utcnow() - timedelta(minutes=1)
        await s.commit()
    app.tg.reset()
    await expiry.run_once(app.bot, session_factory)
    assert [c for c in app.tg.of(SendMessage) if "истекла" in c.text] == []


# ------------------------------------------------------------------ startup check


async def test_startup_check_passes_when_bot_can_invite(app):
    assert await check_channel_rights(app.bot) is None
    assert app.tg.of(GetChatMember)[-1].chat_id == CHANNEL_ID


async def test_startup_check_reports_missing_invite_right_to_admins(app):
    app.tg.bot_is_admin = False
    problem = await check_channel_rights(app.bot)
    assert problem is not None and "Invite users via link" in problem
    await report_channel_problem(app.bot, problem)
    for admin in (ADMIN_1, ADMIN_2):
        assert "Проблема настройки бота" in [c for c in app.tg.of(SendMessage) if c.chat_id == admin][-1].text

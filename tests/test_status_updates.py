import asyncio

import pytest

from bot.db.models import ClientStatus, ScreenshotKind, SubmissionStatus
from bot.db.repositories import clients as clients_repo
from bot.db.repositories import submissions as submissions_repo


async def _make_pending_submission(session, *, telegram_id: int = 111):
    client, _ = await clients_repo.get_or_create(session, telegram_id, "some_user")
    submission = await submissions_repo.create(
        session,
        client_id=client.id,
        full_name="Aziza Karimova",
        phone="+998901234567",
        screenshot_file_id="AgAD123",
        screenshot_kind=ScreenshotKind.photo,
    )
    await clients_repo.set_status(session, client.id, ClientStatus.pending)
    await session.commit()
    return client, submission


async def test_approve_pending_submission_succeeds(session):
    client, submission = await _make_pending_submission(session)

    ok = await submissions_repo.set_review_result(
        session,
        submission_id=submission.id,
        client_id=client.id,
        new_status=SubmissionStatus.approved,
        admin_telegram_id=1,
        admin_name="Admin One",
    )
    await session.commit()

    assert ok is True
    refreshed_submission = await submissions_repo.get_by_id(session, submission.id)
    refreshed_client = await clients_repo.get_by_id(session, client.id)
    assert refreshed_submission.status == SubmissionStatus.approved
    assert refreshed_submission.reviewed_by == 1
    assert refreshed_submission.reviewed_by_name == "Admin One"
    assert refreshed_submission.reviewed_at is not None
    assert refreshed_client.status == ClientStatus.approved


async def test_reject_pending_submission_succeeds(session):
    client, submission = await _make_pending_submission(session, telegram_id=222)

    ok = await submissions_repo.set_review_result(
        session,
        submission_id=submission.id,
        client_id=client.id,
        new_status=SubmissionStatus.rejected,
        admin_telegram_id=2,
        admin_name="Admin Two",
    )
    await session.commit()

    assert ok is True
    refreshed_client = await clients_repo.get_by_id(session, client.id)
    assert refreshed_client.status == ClientStatus.rejected


async def test_second_review_of_already_approved_submission_is_a_noop(session):
    client, submission = await _make_pending_submission(session, telegram_id=333)

    first = await submissions_repo.set_review_result(
        session,
        submission_id=submission.id,
        client_id=client.id,
        new_status=SubmissionStatus.approved,
        admin_telegram_id=1,
        admin_name="Admin One",
    )
    await session.commit()

    second = await submissions_repo.set_review_result(
        session,
        submission_id=submission.id,
        client_id=client.id,
        new_status=SubmissionStatus.rejected,
        admin_telegram_id=2,
        admin_name="Admin Two",
    )
    await session.commit()

    assert first is True
    assert second is False  # already processed: must not flip to rejected
    refreshed_submission = await submissions_repo.get_by_id(session, submission.id)
    refreshed_client = await clients_repo.get_by_id(session, client.id)
    assert refreshed_submission.status == SubmissionStatus.approved
    assert refreshed_submission.reviewed_by == 1  # untouched by admin 2's attempt
    assert refreshed_client.status == ClientStatus.approved


async def test_two_admins_approving_concurrently_only_one_wins(session_factory):
    """Simulates the manual-test scenario: two admins tap Approve at the same time."""
    async with session_factory() as setup_session:
        client, submission = await _make_pending_submission(setup_session, telegram_id=444)
        client_id, submission_id = client.id, submission.id

    async def attempt(admin_id: int, admin_name: str) -> bool:
        async with session_factory() as session:
            result = await submissions_repo.set_review_result(
                session,
                submission_id=submission_id,
                client_id=client_id,
                new_status=SubmissionStatus.approved,
                admin_telegram_id=admin_id,
                admin_name=admin_name,
            )
            await session.commit()
            return result

    results = await asyncio.gather(
        attempt(1, "Admin One"),
        attempt(2, "Admin Two"),
    )

    assert sorted(results) == [False, True]

    async with session_factory() as session:
        refreshed_submission = await submissions_repo.get_by_id(session, submission_id)
        assert refreshed_submission.reviewed_by in (1, 2)
        # Only one admin's name ended up recorded, not a mix of both.
        winner_name = "Admin One" if refreshed_submission.reviewed_by == 1 else "Admin Two"
        assert refreshed_submission.reviewed_by_name == winner_name

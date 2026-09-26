"""A fake Telegram Bot API for end-to-end handler tests.

FakeSession plugs into aiogram's Bot as its HTTP session: every API call is
recorded (inspect `session.calls`) and answered with a plausible object, and
failures can be injected per method/chat (e.g. "bot was blocked by the user").
"""
from __future__ import annotations

import itertools
import time
from collections.abc import AsyncGenerator, Callable
from typing import Any

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.methods import (
    AnswerCallbackQuery,
    ApproveChatJoinRequest,
    CopyMessage,
    CreateChatInviteLink,
    DeclineChatJoinRequest,
    DeleteMessage,
    DeleteWebhook,
    EditMessageCaption,
    EditMessageMedia,
    EditMessageReplyMarkup,
    EditMessageText,
    GetChatMember,
    GetMe,
    RevokeChatInviteLink,
    SendDocument,
    SendMessage,
    SendPhoto,
    TelegramMethod,
)
from aiogram.types import (
    Chat,
    ChatInviteLink,
    ChatMemberAdministrator,
    Document,
    Message,
    MessageId,
    PhotoSize,
    User,
)

BOT_USER = User(id=777000, is_bot=True, first_name="StylistBot", username="stylist_bot")

FailRule = Callable[[TelegramMethod[Any]], Exception | None]


class FakeSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[TelegramMethod[Any]] = []
        self.rules: list[FailRule] = []
        self._ids = itertools.count(5000)
        self._links = itertools.count(1)
        self.bot_is_admin = True

    # -------------------------------------------------------------- failure injection

    def fail(self, method_type: type, *, chat_id: int | None = None, error: str = "blocked") -> FailRule:
        def rule(method: TelegramMethod[Any]) -> Exception | None:
            if not isinstance(method, method_type):
                return None
            if chat_id is not None and getattr(method, "chat_id", None) != chat_id:
                return None
            if error == "blocked":
                return TelegramForbiddenError(method=method, message="Forbidden: bot was blocked by the user")
            return TelegramBadRequest(method=method, message=f"Bad Request: {error}")

        self.rules.append(rule)
        return rule

    def clear_failures(self) -> None:
        self.rules.clear()

    # -------------------------------------------------------------- inspection helpers

    def of(self, method_type: type) -> list[Any]:
        return [c for c in self.calls if isinstance(c, method_type)]

    def texts_to(self, chat_id: int) -> list[str]:
        out = []
        for c in self.calls:
            if isinstance(c, SendMessage) and c.chat_id == chat_id:
                out.append(c.text)
            elif isinstance(c, (SendPhoto, SendDocument)) and c.chat_id == chat_id:
                out.append(c.caption or "")
        return out

    def reset(self) -> None:
        self.calls.clear()

    # -------------------------------------------------------------- BaseSession API

    def _message(self, chat_id: int, **extra: Any) -> Message:
        return Message(
            message_id=next(self._ids),
            date=int(time.time()),
            chat=Chat(id=chat_id, type="private"),
            from_user=BOT_USER,
            **extra,
        )

    async def make_request(self, bot: Bot, method: TelegramMethod[Any], timeout: int | None = None) -> Any:
        self.calls.append(method)
        for rule in self.rules:
            exc = rule(method)
            if exc is not None:
                raise exc

        if isinstance(method, SendMessage):
            return self._message(method.chat_id, text=method.text).as_(bot)
        if isinstance(method, SendPhoto):
            photo = [PhotoSize(file_id=str(method.photo), file_unique_id="u", width=10, height=10)]
            return self._message(method.chat_id, photo=photo, caption=method.caption).as_(bot)
        if isinstance(method, SendDocument):
            doc = Document(file_id=str(method.document), file_unique_id="u")
            return self._message(method.chat_id, document=doc, caption=method.caption).as_(bot)
        if isinstance(method, CopyMessage):
            return MessageId(message_id=next(self._ids))
        if isinstance(method, (EditMessageText, EditMessageMedia, EditMessageCaption, EditMessageReplyMarkup)):
            return True
        if isinstance(method, (DeleteMessage, AnswerCallbackQuery, ApproveChatJoinRequest,
                               DeclineChatJoinRequest, DeleteWebhook)):
            return True
        if isinstance(method, CreateChatInviteLink):
            return ChatInviteLink(
                invite_link=f"https://t.me/+fakeLink{next(self._links)}",
                creator=BOT_USER,
                creates_join_request=bool(method.creates_join_request),
                is_primary=False,
                is_revoked=False,
                name=method.name,
            )
        if isinstance(method, RevokeChatInviteLink):
            return ChatInviteLink(
                invite_link=method.invite_link, creator=BOT_USER, creates_join_request=True,
                is_primary=False, is_revoked=True,
            )
        if isinstance(method, GetMe):
            return BOT_USER
        if isinstance(method, GetChatMember):
            return ChatMemberAdministrator(
                user=BOT_USER, can_be_edited=False, is_anonymous=False, can_manage_chat=True,
                can_delete_messages=True, can_manage_video_chats=False, can_restrict_members=True,
                can_promote_members=False, can_change_info=False, can_invite_users=self.bot_is_admin,
                can_post_stories=False, can_edit_stories=False, can_delete_stories=False,
                can_send_welcome_messages=False,
            )
        raise NotImplementedError(f"FakeSession has no response for {type(method).__name__}")

    async def stream_content(self, url: str, headers: dict[str, Any] | None = None, timeout: int = 30,
                             chunk_size: int = 65536, raise_for_status: bool = True) -> AsyncGenerator[bytes, None]:
        raise NotImplementedError
        yield b""  # pragma: no cover

    async def close(self) -> None:
        pass


# ------------------------------------------------------------------ raw update builders

_update_ids = itertools.count(1)
_message_ids = itertools.count(1)


def _user(user_id: int, username: str | None = None, first_name: str = "Test") -> dict[str, Any]:
    user: dict[str, Any] = {"id": user_id, "is_bot": False, "first_name": first_name}
    if username:
        user["username"] = username
    return user


def message(user_id: int, *, username: str | None = None, **content: Any) -> dict[str, Any]:
    """content: text=..., photo=True, document_mime=..., contact_of=<user_id>+phone=..., voice=True,
    sticker=True, animation=True, video=True"""
    msg: dict[str, Any] = {
        "message_id": next(_message_ids),
        "date": int(time.time()),
        "chat": {"id": user_id, "type": "private"},
        "from": _user(user_id, username),
    }
    if "text" in content:
        msg["text"] = content["text"]
        if content["text"].startswith("/"):
            msg["entities"] = [{"type": "bot_command", "offset": 0, "length": len(content["text"].split()[0])}]
    if content.get("photo"):
        msg["photo"] = [{"file_id": "PHOTO-small", "file_unique_id": "p1", "width": 90, "height": 90},
                        {"file_id": content.get("file_id", "PHOTO-big"), "file_unique_id": "p2", "width": 900, "height": 900}]
    if "document_mime" in content:
        msg["document"] = {"file_id": content.get("file_id", "DOC-1"), "file_unique_id": "d1",
                           "mime_type": content["document_mime"], "file_name": "file"}
    if content.get("animation"):
        anim = {"file_id": "GIF-1", "file_unique_id": "g1", "width": 1, "height": 1, "duration": 1}
        msg["animation"] = anim
        msg["document"] = {"file_id": "GIF-1", "file_unique_id": "g1", "mime_type": "video/mp4"}
    if "contact_of" in content:
        msg["contact"] = {"phone_number": content["phone"], "first_name": "C", "user_id": content["contact_of"]}
    if content.get("voice"):
        msg["voice"] = {"file_id": "VOICE-1", "file_unique_id": "v1", "duration": 3}
    if content.get("sticker"):
        msg["sticker"] = {"file_id": "STK-1", "file_unique_id": "s1", "type": "regular", "width": 1,
                          "height": 1, "is_animated": False, "is_video": False}
    if content.get("video"):
        msg["video"] = {"file_id": "VID-1", "file_unique_id": "vd1", "width": 1, "height": 1, "duration": 1}
    if "caption" in content:
        msg["caption"] = content["caption"]
    return {"update_id": next(_update_ids), "message": msg}


def callback(user_id: int, data: str, *, message_id: int = 1, media: bool = False, text: str = "panel") -> dict[str, Any]:
    msg: dict[str, Any] = {
        "message_id": message_id,
        "date": int(time.time()),
        "chat": {"id": user_id, "type": "private"},
        "from": BOT_USER.model_dump(exclude_none=True),
    }
    if media:
        msg["photo"] = [{"file_id": "X", "file_unique_id": "x", "width": 1, "height": 1}]
        msg["caption"] = text
    else:
        msg["text"] = text
    return {
        "update_id": next(_update_ids),
        "callback_query": {
            "id": f"cb{next(_update_ids)}",
            "from": _user(user_id),
            "chat_instance": "ci",
            "data": data,
            "message": msg,
        },
    }


def join_request(user_id: int, link: str | None, *, channel_id: int) -> dict[str, Any]:
    request: dict[str, Any] = {
        "chat": {"id": channel_id, "type": "channel", "title": "Stylist Challenge"},
        "from": _user(user_id),
        "user_chat_id": user_id,
        "date": int(time.time()),
    }
    if link is not None:
        request["invite_link"] = {
            "invite_link": link, "creator": BOT_USER.model_dump(exclude_none=True),
            "creates_join_request": True, "is_primary": False, "is_revoked": False,
        }
    return {"update_id": next(_update_ids), "chat_join_request": request}

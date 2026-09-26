"""SQLAlchemy 2.0 declarative models. Migrated via Alembic, never create_all()."""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, ForeignKey, Index, JSON, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

_TABLE_KW = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"}


def _enum_values(enum_cls: type[enum.Enum]) -> list[str]:
    return [member.value for member in enum_cls]


class Base(DeclarativeBase):
    pass


class Language(str, enum.Enum):
    ru = "ru"
    uz = "uz"


class ClientStatus(str, enum.Enum):
    none = "none"
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class SubmissionStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class ScreenshotKind(str, enum.Enum):
    photo = "photo"
    document = "document"


class Client(Base):
    __tablename__ = "clients"
    __table_args__ = _TABLE_KW

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    language: Mapped[Language | None] = mapped_column(
        Enum(Language, name="language", values_callable=_enum_values), nullable=True
    )
    status: Mapped[ClientStatus] = mapped_column(
        Enum(ClientStatus, name="client_status", values_callable=_enum_values),
        nullable=False,
        default=ClientStatus.none,
        server_default=ClientStatus.none.value,
        index=True,
    )
    joined_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    submissions: Mapped[list["Submission"]] = relationship(
        back_populates="client", order_by="Submission.id"
    )
    invite_links: Mapped[list["InviteLink"]] = relationship(back_populates="client")


class Submission(Base):
    __tablename__ = "submissions"
    __table_args__ = (
        Index("ix_submissions_client_id_id", "client_id", "id"),
        _TABLE_KW,
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    full_name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    phone_normalized: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    screenshot_file_id: Mapped[str] = mapped_column(String(255), nullable=False)
    screenshot_kind: Mapped[ScreenshotKind] = mapped_column(
        Enum(ScreenshotKind, name="screenshot_kind", values_callable=_enum_values), nullable=False
    )
    status: Mapped[SubmissionStatus] = mapped_column(
        Enum(SubmissionStatus, name="submission_status", values_callable=_enum_values),
        nullable=False,
        default=SubmissionStatus.pending,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reviewed_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    client: Mapped["Client"] = relationship(back_populates="submissions")
    invite_links: Mapped[list["InviteLink"]] = relationship(back_populates="submission")


class InviteLink(Base):
    __tablename__ = "invite_links"
    __table_args__ = _TABLE_KW

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    submission_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False
    )
    link: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sent_to_user: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    send_error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    reminded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expired_notified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    client: Mapped["Client"] = relationship(back_populates="invite_links")
    submission: Mapped["Submission"] = relationship(back_populates="invite_links")


class AdminPanel(Base):
    """Tracks each admin's single live panel message so it survives restarts."""

    __tablename__ = "admin_panels"
    __table_args__ = _TABLE_KW

    admin_telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    is_media: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class FSMRecord(Base):
    """Backs the custom MySQL aiogram FSM storage. key = StorageKey serialized to text."""

    __tablename__ = "fsm_storage"
    __table_args__ = _TABLE_KW

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    state: Mapped[str | None] = mapped_column(String(255), nullable=True)
    data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-09-27 01:22:48.858685
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('admin_panels',
    sa.Column('admin_telegram_id', sa.BigInteger(), nullable=False),
    sa.Column('chat_id', sa.BigInteger(), nullable=False),
    sa.Column('message_id', sa.BigInteger(), nullable=False),
    sa.Column('is_media', sa.Boolean(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('admin_telegram_id'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci'
    )
    op.create_table('clients',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('telegram_id', sa.BigInteger(), nullable=False),
    sa.Column('username', sa.String(length=64), nullable=True),
    sa.Column('language', sa.Enum('ru', 'uz', name='language'), nullable=True),
    sa.Column('status', sa.Enum('none', 'pending', 'approved', 'rejected', name='client_status'), server_default='none', nullable=False),
    sa.Column('joined_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci'
    )
    op.create_index(op.f('ix_clients_status'), 'clients', ['status'], unique=False)
    op.create_index(op.f('ix_clients_telegram_id'), 'clients', ['telegram_id'], unique=True)
    op.create_index(op.f('ix_clients_username'), 'clients', ['username'], unique=False)
    op.create_table('fsm_storage',
    sa.Column('key', sa.String(length=255), nullable=False),
    sa.Column('state', sa.String(length=255), nullable=True),
    sa.Column('data', sa.JSON(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('key'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci'
    )
    op.create_table('submissions',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('client_id', sa.BigInteger(), nullable=False),
    sa.Column('full_name', sa.String(length=100), nullable=False),
    sa.Column('phone', sa.String(length=32), nullable=False),
    sa.Column('phone_normalized', sa.String(length=20), nullable=False),
    sa.Column('screenshot_file_id', sa.String(length=255), nullable=False),
    sa.Column('screenshot_kind', sa.Enum('photo', 'document', name='screenshot_kind'), nullable=False),
    sa.Column('status', sa.Enum('pending', 'approved', 'rejected', name='submission_status'), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('reviewed_by', sa.BigInteger(), nullable=True),
    sa.Column('reviewed_by_name', sa.String(length=128), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci'
    )
    op.create_index(op.f('ix_submissions_client_id'), 'submissions', ['client_id'], unique=False)
    op.create_index('ix_submissions_client_id_id', 'submissions', ['client_id', 'id'], unique=False)
    op.create_index(op.f('ix_submissions_created_at'), 'submissions', ['created_at'], unique=False)
    op.create_index(op.f('ix_submissions_phone_normalized'), 'submissions', ['phone_normalized'], unique=False)
    op.create_index(op.f('ix_submissions_status'), 'submissions', ['status'], unique=False)
    op.create_table('invite_links',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('client_id', sa.BigInteger(), nullable=False),
    sa.Column('submission_id', sa.BigInteger(), nullable=False),
    sa.Column('link', sa.String(length=255), nullable=False),
    sa.Column('name', sa.String(length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=False),
    sa.Column('revoked_at', sa.DateTime(), nullable=True),
    sa.Column('used_at', sa.DateTime(), nullable=True),
    sa.Column('sent_to_user', sa.Boolean(), nullable=False),
    sa.Column('send_error', sa.String(length=512), nullable=True),
    sa.Column('expired_notified_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['submission_id'], ['submissions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('link'),
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci'
    )
    op.create_index(op.f('ix_invite_links_client_id'), 'invite_links', ['client_id'], unique=False)
    op.create_index(op.f('ix_invite_links_expires_at'), 'invite_links', ['expires_at'], unique=False)


def downgrade() -> None:
    # Dropping a table drops its indexes; dropping those indexes first would fail on
    # MySQL, which refuses to drop an index that a foreign key still depends on.
    op.drop_table("invite_links")
    op.drop_table("submissions")
    op.drop_table("fsm_storage")
    op.drop_table("clients")
    op.drop_table("admin_panels")

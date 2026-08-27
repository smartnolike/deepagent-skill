"""Persistence and locking for conversation-scoped workspace sessions."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import psycopg


@dataclass(frozen=True)
class WorkspaceReference:
    id: uuid.UUID
    provider: str
    workspace_reference: str
    namespace: str | None
    expires_at: datetime | None
    last_activity_at: datetime | None = None


class WorkspaceSessionStore:
    """Own SQL access and cross-replica locking for workspace session records."""

    def __init__(self, psycopg_url: str) -> None:
        self._psycopg_url = psycopg_url

    @contextmanager
    def locked(self, conversation_id: uuid.UUID):
        with psycopg.connect(self._psycopg_url) as connection:
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (str(conversation_id),)
            )
            yield connection

    @staticmethod
    def get_active(conversation_id: uuid.UUID, connection) -> WorkspaceReference | None:
        row = connection.execute(
            """SELECT id, provider, workspace_reference, namespace, expires_at, last_activity_at
               FROM ai_agent_sandbox_sessions
               WHERE conversation_id = %s AND status = 'active'""",
            (conversation_id,),
        ).fetchone()
        return WorkspaceReference(*row) if row else None

    @staticmethod
    def create(
        conversation_id: uuid.UUID,
        provider: str,
        workspace_reference: str,
        namespace: str | None,
        expires_at: datetime | None,
        connection,
    ) -> WorkspaceReference:
        row = connection.execute(
            """INSERT INTO ai_agent_sandbox_sessions
               (id, conversation_id, provider, workspace_reference, namespace, status, expires_at)
               VALUES (%s, %s, %s, %s, %s, 'active', %s)
               RETURNING id, provider, workspace_reference, namespace, expires_at, last_activity_at""",
            (uuid.uuid4(), conversation_id, provider, workspace_reference, namespace, expires_at),
        ).fetchone()
        assert row is not None
        return WorkspaceReference(*row)

    @staticmethod
    def touch(session_id: uuid.UUID, connection) -> None:
        connection.execute(
            "UPDATE ai_agent_sandbox_sessions SET last_activity_at = now() WHERE id = %s", (session_id,)
        )

    @staticmethod
    def expire(session_id: uuid.UUID, connection) -> None:
        connection.execute(
            "UPDATE ai_agent_sandbox_sessions SET status = 'expired' WHERE id = %s", (session_id,)
        )

    @staticmethod
    def is_expired(reference: WorkspaceReference, idle_ttl_seconds: int | None) -> bool:
        now = datetime.now(UTC)
        absolute_expired = reference.expires_at is not None and reference.expires_at <= now
        idle_expired = (
            idle_ttl_seconds is not None
            and reference.last_activity_at is not None
            and reference.last_activity_at + timedelta(seconds=idle_ttl_seconds) <= now
        )
        return absolute_expired or idle_expired

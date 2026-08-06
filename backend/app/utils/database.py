"""Database connection adapters for local SQLite and PostgreSQL deployments."""

import asyncio
import os
import re
import sqlite3
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import asyncpg
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent.parent
_pool: Any = None


def is_sqlite_database(database_url: str | None = None) -> bool:
    """Return whether the configured database URL selects local SQLite."""
    return (database_url or os.getenv("DATABASE_URL", "")).lower().startswith("sqlite:")


def _sqlite_path(database_url: str) -> str:
    """Resolve a sqlite URL to an absolute path under the backend by default."""
    raw_path = database_url[len("sqlite:///") :].split("?", 1)[0]
    if raw_path in {":memory:", ""}:
        return raw_path or ":memory:"

    path = Path(raw_path)
    if not path.is_absolute():
        path = BASE_DIR / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def _convert_sqlite_query(
    query: str, args: tuple[Any, ...]
) -> tuple[str, tuple[Any, ...]]:
    """Translate asyncpg positional placeholders to sqlite placeholders."""
    converted_query = re.sub(r"\$\d+", "?", query)
    converted_query = re.sub(
        r"\s+FOR\s+UPDATE\s*$", "", converted_query, flags=re.IGNORECASE
    )
    converted_args = tuple(
        value.isoformat() if isinstance(value, datetime) else value for value in args
    )
    return converted_query, converted_args


class SQLiteConnection:
    """Async facade over one serialized sqlite3 connection.

    VoxBridge's local mode is intentionally single-process. A single connection
    plus an async lock keeps state updates atomic without introducing another
    service for a recording/demo environment. Local queries are deliberately
    small and run synchronously while holding the lock; this avoids creating
    executor work for every request and keeps the single-process demo lifecycle
    deterministic.
    """

    def __init__(self, raw_connection: sqlite3.Connection):
        self._raw_connection = raw_connection
        self._lock = asyncio.Lock()
        self._transaction_task: asyncio.Task | None = None

    async def _run(self, operation: Callable[[], Any]) -> Any:
        current_task = asyncio.current_task()
        if current_task is self._transaction_task:
            return operation()

        async with self._lock:
            return operation()

    def _rows(self, cursor: sqlite3.Cursor) -> list[dict[str, Any]]:
        columns = [column[0] for column in cursor.description or []]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    async def execute(self, query: str, *args: Any) -> str:
        statement, parameters = _convert_sqlite_query(query, args)
        commit_after = asyncio.current_task() is not self._transaction_task

        def operation() -> str:
            cursor = self._raw_connection.execute(statement, parameters)
            if commit_after:
                self._raw_connection.commit()
            return f"{cursor.rowcount}"

        return await self._run(operation)

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        statement, parameters = _convert_sqlite_query(query, args)

        def operation() -> list[dict[str, Any]]:
            if "information_schema.columns" in statement.lower():
                table_match = re.search(
                    r"table_name\s*=\s*'([^']+)'", statement, flags=re.IGNORECASE
                )
                if not table_match:
                    return []
                table_name = table_match.group(1).replace('"', '""')
                cursor = self._raw_connection.execute(
                    f'PRAGMA table_info("{table_name}")'
                )
                return [{"column_name": row[1]} for row in cursor.fetchall()]

            cursor = self._raw_connection.execute(statement, parameters)
            return self._rows(cursor)

        return await self._run(operation)

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        rows = await self.fetch(query, *args)
        return rows[0] if rows else None

    async def fetchval(self, query: str, *args: Any) -> Any:
        row = await self.fetchrow(query, *args)
        return next(iter(row.values())) if row else None

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator["SQLiteConnection"]:
        """Run a group of calls in one serialized SQLite transaction."""
        current_task = asyncio.current_task()
        if current_task is self._transaction_task:
            yield self
            return

        await self._lock.acquire()
        self._transaction_task = current_task
        try:
            self._raw_connection.execute("BEGIN")
            yield self
            self._raw_connection.commit()
        except Exception:
            self._raw_connection.rollback()
            raise
        finally:
            self._transaction_task = None
            self._lock.release()

    async def close(self) -> None:
        async with self._lock:
            self._raw_connection.close()


class SQLitePool:
    """Pool-shaped wrapper so existing route/service code remains unchanged."""

    def __init__(self, path: str):
        raw_connection = sqlite3.connect(path, check_same_thread=False)
        raw_connection.row_factory = sqlite3.Row
        self.connection = SQLiteConnection(raw_connection)

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[SQLiteConnection]:
        yield self.connection

    async def close(self) -> None:
        await self.connection.close()


async def init_db_pool() -> None:
    """Initialize the selected local or PostgreSQL database backend."""
    global _pool

    database_url = os.getenv("DATABASE_URL", "")
    if not database_url:
        raise ValueError("DATABASE_URL not configured")

    if is_sqlite_database(database_url):
        database_path = _sqlite_path(database_url)
        _pool = SQLitePool(database_path)
        async with _pool.acquire() as connection:
            await connection.execute("PRAGMA foreign_keys = ON")
            await connection.fetchval("SELECT 1")
        print(f"✓ SQLite database initialized ({database_path})")
        return

    if database_url.startswith("postgresql+asyncpg://"):
        database_url = database_url.replace("postgresql+asyncpg://", "postgresql://")

    try:
        _pool = await asyncpg.create_pool(
            database_url,
            min_size=2,
            max_size=10,
            max_queries=50000,
            max_inactive_connection_lifetime=300,
            command_timeout=60,
        )

        async with _pool.acquire() as connection:
            await connection.fetchval("SELECT 1")

        print("✓ PostgreSQL pool initialized")
    except Exception as exc:
        print(f"✗ Failed to connect to PostgreSQL: {exc}")
        raise


async def close_db_pool() -> None:
    """Close the active database backend."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        print("✓ Database pool closed")


def get_pool() -> Any:
    """Return the initialized database backend."""
    if not _pool:
        raise RuntimeError("Database pool not initialized. Call init_db_pool() first.")
    return _pool


@asynccontextmanager
async def get_db_connection() -> AsyncIterator[Any]:
    """Acquire a connection from the configured database backend."""
    pool = get_pool()
    async with pool.acquire() as connection:
        yield connection

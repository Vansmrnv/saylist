from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_engine


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """A session whose work is rolled back after the test, even if the code under test commits.

    Needs a migrated database: mark the test `@pytest.mark.db` and run `make test-db`.
    """
    async with get_engine().connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(bind=connection, join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import create_app


def test_app_starts_and_reports_health() -> None:
    response = TestClient(create_app()).get("/health")
    assert response.json() == {"status": "ok"}


@pytest.mark.db
async def test_database_is_reachable(db_session: AsyncSession) -> None:
    assert (await db_session.execute(text("select 1"))).scalar_one() == 1

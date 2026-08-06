import asyncio

from app.services.audit_service import (
    create_job,
    get_job,
    init_database,
    save_job_state,
)
from app.utils import database


def test_sqlite_backend_persists_job_and_json_state(monkeypatch, tmp_path):
    database_path = tmp_path / "voxbridge-test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")

    async def scenario():
        await database.init_db_pool()
        try:
            await init_database()
            await create_job("local-job", "sample.mp4", "storage/uploads/sample.mp4")
            await save_job_state(
                "local-job",
                {"pipeline_step": "ready", "source_type": "upload"},
            )
            job = await get_job("local-job")
            assert job is not None
            assert job["state_data"] == {
                "pipeline_step": "ready",
                "source_type": "upload",
            }
        finally:
            await database.close_db_pool()

    asyncio.run(scenario())

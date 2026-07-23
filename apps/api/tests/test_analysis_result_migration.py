"""Contract tests for the analysis result Alembic migration."""

import importlib.util
from pathlib import Path
from types import ModuleType

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def _migration() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "0003_create_analysis_results.py"
    )
    spec = importlib.util.spec_from_file_location("analysis_result_migration", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("migration module could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_revision_chain_is_0002_to_0003() -> None:
    migration = _migration()

    assert migration.revision == "0003"
    assert migration.down_revision == "0002"


def test_migration_upgrades_downgrades_and_reupgrades_on_sqlite() -> None:
    migration = _migration()
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    sa.Table(
        "analyses",
        metadata,
        sa.Column("id", sa.Uuid(), primary_key=True),
    )

    with engine.begin() as connection:
        metadata.create_all(connection)
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration.upgrade()

        inspector = sa.inspect(connection)
        assert "analysis_results" in inspector.get_table_names()
        assert inspector.get_pk_constraint("analysis_results")["constrained_columns"] == [
            "analysis_id"
        ]
        foreign_keys = inspector.get_foreign_keys("analysis_results")
        assert len(foreign_keys) == 1
        assert foreign_keys[0]["referred_table"] == "analyses"
        assert foreign_keys[0]["options"]["ondelete"] == "CASCADE"
        columns = {column["name"]: column for column in inspector.get_columns("analysis_results")}
        assert isinstance(columns["payload"]["type"], sa.JSON)
        assert columns["schema_version"]["nullable"] is False

        with Operations.context(context):
            migration.downgrade()
        assert "analysis_results" not in sa.inspect(connection).get_table_names()

        with Operations.context(context):
            migration.upgrade()
        assert "analysis_results" in sa.inspect(connection).get_table_names()

import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from app.models import Base, EmergencyCall  # noqa: E402,F401


def test_emergency_calls_table_has_expected_columns():
    table = Base.metadata.tables["emergency_calls"]
    column_names = {c.name for c in table.columns}
    assert column_names == {
        "id",
        "call_number",
        "urgency_category",
        "address",
        "received_at",
        "arrived_at",
        "outcome",
    }
    assert table.columns["id"].primary_key
    assert not table.columns["call_number"].nullable


def test_urgency_category_is_indexed():
    table = Base.metadata.tables["emergency_calls"]
    indexed_columns = {col.name for idx in table.indexes for col in idx.columns}
    assert "urgency_category" in indexed_columns

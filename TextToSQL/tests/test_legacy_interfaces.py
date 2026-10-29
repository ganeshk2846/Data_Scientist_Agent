import sqlite3

from src.onboarding.inspector import inspect_database
from src.onboarding.profiler import profile_database


def test_inspector_and_profiler_legacy_shapes_remain_available(tmp_path):
    path = tmp_path / "legacy.sqlite"
    connection = sqlite3.connect(path)
    connection.executescript("CREATE TABLE orders (order_id INTEGER PRIMARY KEY, amount REAL); INSERT INTO orders VALUES (1, 2.5);")
    connection.commit()
    connection.close()
    schema = inspect_database(str(path))
    assert schema["orders"][0]["name"] == "order_id"
    report = profile_database(str(path))
    assert report["orders"]["row_count"] == 1
    assert report["orders"]["columns"]["amount"]["null_count"] == 0
    assert report["orders"]["columns"]["amount"]["sample_values"] == [2.5]

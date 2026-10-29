from src.onboarding.inspector import inspect_database

db_path = "spider_data/spider_data/database/academic/academic.sqlite"

schema = inspect_database(db_path)

print(f"Tables found: {len(schema)}")

for table_name, columns in schema.items():
    print(f"\nTable: {table_name}")
    for column in columns:
        print(f"  {column['name']} ({column['type']})")

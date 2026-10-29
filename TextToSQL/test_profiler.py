from src.onboarding.profiler import profile_database

db_path = "spider_data/spider_data/database/academic/academic.sqlite"

report = profile_database(db_path)

for table_name, table_info in report.items():
    print(f"\nTable: {table_name}")
    print(f"Rows: {table_info['row_count']}")

    for column_name, stats in table_info["columns"].items():
        print(f"  {column_name}: "
              f"NULLs={stats['null_count']}, "
              f"Distinct={stats['distinct_count']}, "
              f"Samples={stats['sample_values']}")

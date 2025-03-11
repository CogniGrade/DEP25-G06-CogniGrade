import sqlite3

# Connect to the SQLite database file
conn = sqlite3.connect('classroom.db')
cursor = conn.cursor()

# Retrieve the names of all tables in the database
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
tables = cursor.fetchall()

if not tables:
    print("No tables found in the database.")
else:
    # Iterate over each table and print its content
    for table_name_tuple in tables:
        # Extract the table name from the tuple
        table_name = table_name_tuple[0]
        print(f"\nContents of table '{table_name}':")
        cursor.execute(f"SELECT * FROM {table_name};")
        rows = cursor.fetchall()
        if rows:
            for row in rows:
                print(row)
        else:
            print("  (No rows found)")
        print("-" * 40)

# Close the connection
conn.close()

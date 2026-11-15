
import sqlite3

conn = sqlite3.connect("eventsphere.db")
cursor = conn.cursor()

columns = [
    row[1] for row in cursor.execute("PRAGMA table_info(tickets)").fetchall()
]

if "ticket_category_id" not in columns:
    cursor.execute(
        "ALTER TABLE tickets ADD COLUMN ticket_category_id INTEGER"
    )
    print("ticket_category_id column added successfully!")
else:
    print("ticket_category_id column already exists!")

conn.commit()
conn.close()

#!/usr/bin/env python3
"""
Database migration script to add deployment tracking fields.

Run this script to add new columns for detailed deployment progress tracking.
"""

import sqlite3
import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def migrate():
    db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'app.db')
    
    if not os.path.exists(db_path):
        print(f"Database not found at {db_path}")
        return False
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get existing columns
    cursor.execute("PRAGMA table_info(jobs)")
    existing_columns = [row[1] for row in cursor.fetchall()]
    
    migrations = [
        ("deployment_stage", "VARCHAR(50)"),
        ("deployment_stage_updated_at", "DATETIME"),
        ("deployment_console_lines", "INTEGER DEFAULT 0"),
        ("deployment_services_count", "VARCHAR(10)"),
    ]
    
    for column_name, column_type in migrations:
        if column_name not in existing_columns:
            try:
                cursor.execute(f"ALTER TABLE jobs ADD COLUMN {column_name} {column_type}")
                print(f"✓ Added column: {column_name}")
            except sqlite3.OperationalError as e:
                if "duplicate column name" in str(e).lower():
                    print(f"  Column {column_name} already exists")
                else:
                    print(f"✗ Error adding {column_name}: {e}")
        else:
            print(f"  Column {column_name} already exists")
    
    conn.commit()
    conn.close()
    
    print("\n✓ Migration completed successfully!")
    return True

if __name__ == "__main__":
    migrate()

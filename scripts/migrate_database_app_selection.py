#!/usr/bin/env python3
"""
Database Migration Script - Add App Selection Field

This script adds the selected_apps field to the jobs table
for tracking which App Garden apps should be pre-installed.

Usage:
    python3 scripts/migrate_database_app_selection.py
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import engine
from sqlalchemy import text

def migrate():
    """Add selected_apps field to jobs table"""

    print("=" * 60)
    print("Database Migration: Adding App Selection Field")
    print("=" * 60)

    with engine.connect() as conn:
        # Check if column already exists
        result = conn.execute(text("PRAGMA table_info(jobs)"))
        columns = {row[1] for row in result}

        # Add selected_apps column if it doesn't exist
        if 'selected_apps' not in columns:
            print("✓ Adding selected_apps column...")
            conn.execute(text(
                "ALTER TABLE jobs ADD COLUMN selected_apps JSON"
            ))
            conn.commit()
            print("✓ Migration applied successfully")
        else:
            print("• selected_apps column already exists")
            print("✓ Database is already up to date")

        print("=" * 60)
        print("Migration completed successfully!")
        print("=" * 60)

if __name__ == "__main__":
    try:
        migrate()
    except Exception as e:
        print(f"ERROR: Migration failed: {str(e)}")
        sys.exit(1)

#!/usr/bin/env python3
"""
Database migration script to add toolshed-related fields to the jobs table.

This script adds:
- selected_tools: JSON field to store selected tool template names
- tool_deployment_status: JSON field to store deployment status of each tool

Run this script after updating the models to add toolshed support.

Usage:
    python scripts/migrate_database_tools.py
"""

import sqlite3
import json
import sys
from pathlib import Path

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import settings


def migrate_database():
    """Add toolshed-related fields to jobs table"""

    # Parse database URL to get database path
    db_url = settings.database_url
    if db_url.startswith("sqlite:///"):
        db_path = db_url.replace("sqlite:///", "")
    else:
        print(f"Error: This script only supports SQLite databases. Got: {db_url}")
        return False

    print(f"Connecting to database: {db_path}")

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Check if columns already exist
        cursor.execute("PRAGMA table_info(jobs)")
        columns = [col[1] for col in cursor.fetchall()]

        migrations_needed = []
        if 'selected_tools' not in columns:
            migrations_needed.append('selected_tools')
        if 'tool_deployment_status' not in columns:
            migrations_needed.append('tool_deployment_status')

        if not migrations_needed:
            print("✓ Database already up to date. No migrations needed.")
            return True

        print(f"Adding {len(migrations_needed)} new column(s) to jobs table...")

        # Add selected_tools column if it doesn't exist
        if 'selected_tools' in migrations_needed:
            print("  • Adding 'selected_tools' column...")
            cursor.execute("""
                ALTER TABLE jobs
                ADD COLUMN selected_tools TEXT
            """)
            print("    ✓ Added selected_tools column")

        # Add tool_deployment_status column if it doesn't exist
        if 'tool_deployment_status' in migrations_needed:
            print("  • Adding 'tool_deployment_status' column...")
            cursor.execute("""
                ALTER TABLE jobs
                ADD COLUMN tool_deployment_status TEXT
            """)
            print("    ✓ Added tool_deployment_status column")

        # Commit changes
        conn.commit()
        print("\n✓ Database migration completed successfully!")
        print(f"  Added {len(migrations_needed)} new column(s)")

        # Verify columns were added
        cursor.execute("PRAGMA table_info(jobs)")
        columns = [col[1] for col in cursor.fetchall()]

        all_present = all(col in columns for col in ['selected_tools', 'tool_deployment_status'])
        if all_present:
            print("  ✓ Verified: All new columns are present in the database")
        else:
            print("  ⚠ Warning: Some columns may not have been added successfully")
            return False

        return True

    except sqlite3.Error as e:
        print(f"\n✗ Database error: {e}")
        return False
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        return False
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    print("=" * 60)
    print("Database Migration: Add Toolshed Support")
    print("=" * 60)
    print()

    success = migrate_database()

    print()
    print("=" * 60)
    if success:
        print("Migration completed successfully!")
        print("You can now use toolshed features in your Kamiwaza deployments.")
    else:
        print("Migration failed. Please check the errors above.")
        sys.exit(1)
    print("=" * 60)

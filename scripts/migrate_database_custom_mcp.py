#!/usr/bin/env python3
"""
Database migration script to add custom_mcp_github_urls field to the jobs table.

This script adds:
- custom_mcp_github_urls: JSON field to store GitHub URLs for custom MCP tools to import

Run this script after updating the models to add custom MCP import support.

Usage:
    python scripts/migrate_database_custom_mcp.py
"""

import sqlite3
import json
import sys
from pathlib import Path

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import settings


def migrate_database():
    """Add custom_mcp_github_urls field to jobs table"""

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

        # Check if column already exists
        cursor.execute("PRAGMA table_info(jobs)")
        columns = [col[1] for col in cursor.fetchall()]

        if 'custom_mcp_github_urls' in columns:
            print("✓ Database already up to date. Column 'custom_mcp_github_urls' exists.")
            return True

        print("Adding 'custom_mcp_github_urls' column to jobs table...")

        # Add custom_mcp_github_urls column
        cursor.execute("""
            ALTER TABLE jobs
            ADD COLUMN custom_mcp_github_urls TEXT
        """)
        print("  ✓ Added custom_mcp_github_urls column")

        # Commit changes
        conn.commit()
        print("\n✓ Database migration completed successfully!")

        # Verify column was added
        cursor.execute("PRAGMA table_info(jobs)")
        columns = [col[1] for col in cursor.fetchall()]

        if 'custom_mcp_github_urls' in columns:
            print("  ✓ Verified: custom_mcp_github_urls column is present in the database")
        else:
            print("  ⚠ Warning: Column may not have been added successfully")
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
    print("Database Migration: Add Custom MCP GitHub Import Support")
    print("=" * 60)
    print()

    success = migrate_database()

    print()
    print("=" * 60)
    if success:
        print("Migration completed successfully!")
        print("You can now import custom MCP tools from GitHub URLs.")
    else:
        print("Migration failed. Please check the errors above.")
        sys.exit(1)
    print("=" * 60)

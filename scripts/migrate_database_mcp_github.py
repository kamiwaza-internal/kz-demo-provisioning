#!/usr/bin/env python3
"""
Database Migration Script - Add MCP GitHub Import Field

This script adds the custom_mcp_github_urls field to the jobs table
for tracking GitHub MCP tools to import.

Usage:
    python3 scripts/migrate_database_mcp_github.py
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import engine
from sqlalchemy import text

def migrate():
    """Add custom_mcp_github_urls field to jobs table"""

    print("=" * 60)
    print("Database Migration: Adding MCP GitHub Import Field")
    print("=" * 60)

    with engine.connect() as conn:
        # Check if column already exists
        result = conn.execute(text("PRAGMA table_info(jobs)"))
        columns = {row[1] for row in result}

        # Add custom_mcp_github_urls column if it doesn't exist
        if 'custom_mcp_github_urls' not in columns:
            print("✓ Adding custom_mcp_github_urls column...")
            conn.execute(text(
                "ALTER TABLE jobs ADD COLUMN custom_mcp_github_urls JSON"
            ))
            conn.commit()
            print("✓ Migration applied successfully")
        else:
            print("• custom_mcp_github_urls column already exists")
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

#!/usr/bin/env python3
"""
Database Migration Script - Add AMI Creation Fields

This script adds the new AMI creation tracking fields to the jobs table
for existing databases.

Usage:
    python3 scripts/migrate_database_ami_fields.py
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import engine
from sqlalchemy import text

def migrate():
    """Add AMI creation fields to jobs table"""

    print("=" * 60)
    print("Database Migration: Adding AMI Creation Fields")
    print("=" * 60)

    with engine.connect() as conn:
        # Check if columns already exist
        result = conn.execute(text("PRAGMA table_info(jobs)"))
        columns = {row[1] for row in result}

        migrations = []

        # Add created_ami_id column if it doesn't exist
        if 'created_ami_id' not in columns:
            migrations.append(
                "ALTER TABLE jobs ADD COLUMN created_ami_id VARCHAR(100)"
            )
            print("✓ Will add: created_ami_id")
        else:
            print("• created_ami_id already exists")

        # Add ami_creation_status column if it doesn't exist
        if 'ami_creation_status' not in columns:
            migrations.append(
                "ALTER TABLE jobs ADD COLUMN ami_creation_status VARCHAR(20)"
            )
            print("✓ Will add: ami_creation_status")
        else:
            print("• ami_creation_status already exists")

        # Add ami_created_at column if it doesn't exist
        if 'ami_created_at' not in columns:
            migrations.append(
                "ALTER TABLE jobs ADD COLUMN ami_created_at DATETIME"
            )
            print("✓ Will add: ami_created_at")
        else:
            print("• ami_created_at already exists")

        # Add ami_creation_error column if it doesn't exist
        if 'ami_creation_error' not in columns:
            migrations.append(
                "ALTER TABLE jobs ADD COLUMN ami_creation_error TEXT"
            )
            print("✓ Will add: ami_creation_error")
        else:
            print("• ami_creation_error already exists")

        # Execute migrations
        if migrations:
            print("\nApplying migrations...")
            for migration in migrations:
                conn.execute(text(migration))
                conn.commit()
            print(f"✓ Applied {len(migrations)} migration(s)")
        else:
            print("\n✓ Database is already up to date")

        print("=" * 60)
        print("Migration completed successfully!")
        print("=" * 60)

if __name__ == "__main__":
    try:
        migrate()
    except Exception as e:
        print(f"ERROR: Migration failed: {str(e)}")
        sys.exit(1)

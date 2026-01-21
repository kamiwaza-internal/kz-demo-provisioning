-- Migration: Add use_cached_ami column to jobs table
-- Date: 2026-01-21
-- Description: Adds a boolean flag to allow users to specify whether to use cached AMI for provisioning

-- SQLite doesn't support adding columns with defaults in all cases, so we do it in two steps
ALTER TABLE jobs ADD COLUMN use_cached_ami BOOLEAN DEFAULT 0;

-- Update existing rows to have the default value
UPDATE jobs SET use_cached_ami = 0 WHERE use_cached_ami IS NULL;

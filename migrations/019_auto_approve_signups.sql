-- Auto-approve new signups (was manual approval gate).
-- Eric sends notification email instead of blocking at edge.
ALTER TABLE agents ALTER COLUMN admin_approved SET DEFAULT TRUE;

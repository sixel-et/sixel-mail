-- Admin approval gate: new accounts disabled by default, admin must approve
-- Users cannot override this flag — only the admin panel can change it

ALTER TABLE agents ADD COLUMN IF NOT EXISTS admin_approved BOOLEAN NOT NULL DEFAULT FALSE;

-- Approve all existing agents (they were already vetted)
UPDATE agents SET admin_approved = TRUE;

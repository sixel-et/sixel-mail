-- Add nonce_enabled column (opt-in Door Knock verification)
-- Default FALSE: new agents get simple email relay
-- Users can enable from account page for nonce-based reply-to validation

ALTER TABLE agents ADD COLUMN IF NOT EXISTS nonce_enabled BOOLEAN DEFAULT FALSE;

-- Enable nonce for existing agents that have active (unburned, unexpired) nonces
UPDATE agents SET nonce_enabled = TRUE WHERE id IN (
    SELECT DISTINCT agent_id FROM nonces WHERE burned = FALSE AND expires_at > now()
);

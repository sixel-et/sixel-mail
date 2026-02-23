-- Add heartbeat_enabled toggle for agents that don't need monitoring
ALTER TABLE agents ADD COLUMN IF NOT EXISTS heartbeat_enabled BOOLEAN DEFAULT TRUE;

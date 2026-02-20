-- Door Knock nonce authentication system
-- Replaces TOTP with reply-to nonce validation

-- Nonces table: tracks issued nonces for reply-to validation
CREATE TABLE IF NOT EXISTS nonces (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id UUID NOT NULL REFERENCES agents(id),
    nonce TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    burned BOOLEAN DEFAULT FALSE,
    burned_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_nonces_nonce ON nonces(nonce);
CREATE INDEX IF NOT EXISTS idx_nonces_agent_expires ON nonces(agent_id, expires_at);

-- Channel kill switch: can be deactivated via /allstop endpoint
ALTER TABLE agents ADD COLUMN IF NOT EXISTS channel_active BOOLEAN DEFAULT TRUE;

-- All-stop key hash (pre-shared out-of-band, stored as SHA-256 hash)
ALTER TABLE agents ADD COLUMN IF NOT EXISTS allstop_key_hash TEXT;

-- Cleanup: expire old burned/expired nonces (run periodically or let DB handle)
-- For now, the app will skip expired nonces during validation.

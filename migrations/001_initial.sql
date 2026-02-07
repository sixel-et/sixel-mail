CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    github_id BIGINT UNIQUE NOT NULL,
    github_username TEXT NOT NULL,
    email TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS agents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) NOT NULL,
    address TEXT UNIQUE NOT NULL,
    allowed_contact TEXT NOT NULL,
    credit_balance INTEGER DEFAULT 0,
    last_seen_at TIMESTAMPTZ,
    heartbeat_timeout INTEGER DEFAULT 300,
    alert_status TEXT DEFAULT 'active',
    alert_mute_until TIMESTAMPTZ,
    agent_down_notified BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id UUID REFERENCES agents(id) NOT NULL,
    direction TEXT NOT NULL,
    subject TEXT,
    body TEXT NOT NULL,
    is_read BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id UUID REFERENCES agents(id) NOT NULL,
    key_hash TEXT NOT NULL,
    key_prefix TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS credit_transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id UUID REFERENCES agents(id) NOT NULL,
    amount INTEGER NOT NULL,
    reason TEXT NOT NULL,
    stripe_session_id TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_messages_agent_unread ON messages(agent_id, is_read) WHERE direction = 'inbound';
CREATE INDEX IF NOT EXISTS idx_agents_heartbeat ON agents(last_seen_at) WHERE alert_status = 'active';
CREATE INDEX IF NOT EXISTS idx_agents_address ON agents(address);
CREATE INDEX IF NOT EXISTS idx_api_keys_prefix ON api_keys(key_prefix);

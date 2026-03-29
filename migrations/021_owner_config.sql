-- Per-owner configuration (replaces hardcoded limits)
CREATE TABLE IF NOT EXISTS owner_config (
    user_id UUID PRIMARY KEY REFERENCES users(id),
    max_agents INTEGER NOT NULL DEFAULT 5,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

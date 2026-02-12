-- Seed 5000 credits for astral agent
DO $$
DECLARE
    v_agent_id UUID;
BEGIN
    SELECT id INTO v_agent_id FROM agents WHERE address = 'astral';
    IF v_agent_id IS NOT NULL THEN
        UPDATE agents SET credit_balance = credit_balance + 5000 WHERE id = v_agent_id;
        INSERT INTO credit_transactions (agent_id, amount, reason)
        VALUES (v_agent_id, 5000, 'admin_grant');
    END IF;
END $$;

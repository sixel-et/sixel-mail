-- Agent-to-agent pipe: cc_email for monitoring tee
-- When set, copies of sent/received messages are forwarded to this address via Resend
ALTER TABLE agents ADD COLUMN IF NOT EXISTS cc_email TEXT;

-- Enable RLS on nonces table (missed in migration 008 which created it after 003)
-- Also enable on attachments table (created in migration 010, also after 003)
ALTER TABLE nonces ENABLE ROW LEVEL SECURITY;
ALTER TABLE attachments ENABLE ROW LEVEL SECURITY;

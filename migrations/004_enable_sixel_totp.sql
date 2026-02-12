-- Enable TOTP encryption for the sixel agent
UPDATE agents SET has_totp = true WHERE address = 'sixel';

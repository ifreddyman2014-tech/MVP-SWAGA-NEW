-- Add location field to servers table
-- Run this migration to fix "transport method cannot be empty" error

-- Add location column if it doesn't exist
ALTER TABLE servers
ADD COLUMN IF NOT EXISTS location VARCHAR(10) DEFAULT '' NOT NULL;

-- Update existing servers with default location
-- You can manually update these later with correct country codes (FI, DE, LV, NL, etc.)
UPDATE servers SET location = '' WHERE location IS NULL;

-- Also ensure network_type is never empty
UPDATE servers SET network_type = 'xhttp' WHERE network_type IS NULL OR network_type = '';

-- Ensure other critical fields have defaults
UPDATE servers SET security = 'reality' WHERE security IS NULL OR security = '';
UPDATE servers SET flow = 'xtls-rprx-vision' WHERE flow IS NULL OR flow = '';
UPDATE servers SET fingerprint = 'chrome' WHERE fingerprint IS NULL OR fingerprint = '';
UPDATE servers SET spider_x = '/' WHERE spider_x IS NULL OR spider_x = '';

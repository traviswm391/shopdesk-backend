-- ShopDesk AI: Backend Feature Migration
-- Features: #10 missed-call SMS, #11 weekly digest, #12 booking SMS, #13 multi-location
-- Run this in the Supabase SQL editor

-- 1. Add new columns to shops table
ALTER TABLE shops
  ADD COLUMN IF NOT EXISTS tone text,
  ADD COLUMN IF NOT EXISTS agent_active boolean DEFAULT true,
  ADD COLUMN IF NOT EXISTS location_name text,
  ADD COLUMN IF NOT EXISTS notification_phone text;

-- 2. Drop the unique constraint that blocked multi-location (#13)
--    (clerk_user_id is kept as a foreign-key-style field but is no longer unique)
ALTER TABLE shops
  DROP CONSTRAINT IF EXISTS shops_clerk_user_id_key;

-- 3. Add index for multi-location queries (one user â many shops)
CREATE INDEX IF NOT EXISTS idx_shops_clerk_user_id ON shops(clerk_user_id);

-- 4. Optional: enforce unique location_name per user (app-level check handles it too,
--    but this is an extra DB safety net)
CREATE UNIQUE INDEX IF NOT EXISTS idx_shops_user_location
  ON shops(clerk_user_id, location_name)
  WHERE location_name IS NOT NULL;

-- Verify
SELECT column_name, data_type, column_default
FROM information_schema.columns
WHERE table_name = 'shops'
  AND column_name IN ('tone','agent_active','location_name','notification_phone')
ORDER BY column_name;

-- ShopDesk AI - Supabase Schema
-- Run this in your Supabase SQL Editor

-- Enable UUID extension
create extension if not exists "uuid-ossp";

-- =====================
-- SHOPS TABLE
-- =====================
create table if not exists shops (
  id uuid primary key default uuid_generate_v4(),
  clerk_user_id text not null unique,
  name text not null,
  address text,
  phone_display text,
  phone_number text,           -- Twilio AI phone number provisioned
  greeting text,
  services text[] default '{}',
  business_hours jsonb default '{}'::jsonb,
  retell_agent_id text,        -- Retell AI agent ID
  retell_llm_id text,          -- Retell LLM ID
  twilio_phone_sid text,       -- Twilio phone number SID
  stripe_customer_id text,
  stripe_subscription_id text,
  subscription_status text default 'inactive',  -- active | inactive | canceled
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

-- Index for fast lookups by clerk user
create index if not exists shops_clerk_user_id_idx on shops(clerk_user_id);

-- =====================
-- CALLS TABLE
-- =====================
create table if not exists calls (
  id uuid primary key default uuid_generate_v4(),
  shop_id uuid not null references shops(id) on delete cascade,
  retell_call_id text unique,    -- Retell's internal call ID
  caller_number text,
  called_number text,
  status text default 'in_progress',  -- in_progress | completed | failed
  transcript text,
  summary text,
  duration_seconds integer,
  appointment_booked boolean default false,
  created_at timestamptz default now(),
  ended_at timestamptz
);

-- Indexes for fast queries
create index if not exists calls_shop_id_idx on calls(shop_id);
create index if not exists calls_retell_call_id_idx on calls(retell_call_id);
create index if not exists calls_created_at_idx on calls(created_at desc);

-- =====================
-- APPOINTMENTS TABLE
-- =====================
create table if not exists appointments (
  id uuid primary key default uuid_generate_v4(),
  shop_id uuid not null references shops(id) on delete cascade,
  call_id uuid references calls(id) on delete set null,
  customer_name text,
  customer_phone text,
  vehicle_info text,
  service_requested text,
  preferred_date text,
  preferred_time text,
  notes text,
  sms_sent boolean default false,
  sms_sid text,
  created_at timestamptz default now()
);

-- Index for shop lookups
create index if not exists appointments_shop_id_idx on appointments(shop_id);
create index if not exists appointments_call_id_idx on appointments(call_id);

-- =====================
-- ROW LEVEL SECURITY
-- =====================
-- We use service role key from backend, so RLS is informational here
-- but good practice to enable for future direct client access

alter table shops enable row level security;
alter table calls enable row level security;
alter table appointments enable row level security;

-- Service role bypasses RLS automatically, so backend always has full access.
-- If you want to add user-level policies in the future, add them here.

-- =====================
-- UPDATED_AT TRIGGER
-- =====================
create or replace function update_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

create trigger shops_updated_at
  before update on shops
  for each row execute function update_updated_at();

-- =====================
-- HELPFUL VIEWS
-- =====================

-- Call stats per shop
create or replace view shop_call_stats as
select
  shop_id,
  count(*) as total_calls,
  count(*) filter (where appointment_booked = true) as appointments_booked,
  round(
    count(*) filter (where appointment_booked = true)::numeric
    / nullif(count(*), 0) * 100,
    1
  ) as conversion_rate,
  round(avg(duration_seconds)) as avg_duration_seconds
from calls
where status = 'completed'
group by shop_id;

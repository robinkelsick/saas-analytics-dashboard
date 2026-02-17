-- infra/db/init.sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Customers (accounts)
CREATE TABLE IF NOT EXISTS customers (
  customer_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name        TEXT NOT NULL,
  industry    TEXT NOT NULL,
  plan        TEXT NOT NULL CHECK (plan IN ('Starter','Growth','Enterprise')),
  created_at  DATE NOT NULL
);

-- Subscription revenue events (MRR changes)
CREATE TABLE IF NOT EXISTS subscription_events (
  event_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  customer_id UUID NOT NULL REFERENCES customers(customer_id) ON DELETE CASCADE,
  event_date  DATE NOT NULL,
  event_type  TEXT NOT NULL CHECK (event_type IN ('new','expansion','contraction','churn','reactivation')),
  mrr_delta   NUMERIC(12,2) NOT NULL
);

-- Optional but recommended: usage leading indicators
CREATE TABLE IF NOT EXISTS product_usage_daily (
  usage_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  customer_id     UUID NOT NULL REFERENCES customers(customer_id) ON DELETE CASCADE,
  usage_date      DATE NOT NULL,
  active_seats    INT NOT NULL CHECK (active_seats >= 0),
  events          INT NOT NULL CHECK (events >= 0),
  feature_actions INT NOT NULL CHECK (feature_actions >= 0),
  UNIQUE(customer_id, usage_date)
);

CREATE INDEX IF NOT EXISTS idx_events_date ON subscription_events(event_date);
CREATE INDEX IF NOT EXISTS idx_events_customer_date ON subscription_events(customer_id, event_date);
CREATE INDEX IF NOT EXISTS idx_usage_customer_date ON product_usage_daily(customer_id, usage_date);

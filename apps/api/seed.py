import os
import random
from datetime import date, timedelta
from dataclasses import dataclass
from typing import Dict, List, Tuple

import psycopg
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@db:5432/saas")

INDUSTRIES = ["SaaS", "FinTech", "Health", "E-commerce", "Logistics", "EdTech", "Media"]
PLANS = ["Starter", "Growth", "Enterprise"]

B2B_NAMES_1 = ["North", "Bright", "Vertex", "Summit", "Pine", "Cobalt", "Silver", "Atlas", "Signal", "Rocket"]
B2B_NAMES_2 = ["Labs", "Works", "Systems", "Cloud", "Analytics", "Partners", "Holdings", "Solutions", "Software", "Group"]

@dataclass
class Customer:
  customer_id: str
  plan: str
  industry: str
  start_mrr: float
  churned: bool = False
  current_mrr: float = 0.0

def month_start(d: date) -> date:
  return date(d.year, d.month, 1)

def add_months(d: date, months: int) -> date:
  y = d.year + (d.month - 1 + months) // 12
  m = (d.month - 1 + months) % 12 + 1
  return date(y, m, 1)

def daterange(d0: date, d1: date) -> List[date]:
  out = []
  cur = d0
  while cur <= d1:
    out.append(cur)
    cur += timedelta(days=1)
  return out

def rand_company_name() -> str:
  return f"{random.choice(B2B_NAMES_1)} {random.choice(B2B_NAMES_2)}"

def choose_plan() -> str:
  # B2B startup skew: many Starter, fewer Enterprise
  r = random.random()
  if r < 0.70:
    return "Starter"
  if r < 0.93:
    return "Growth"
  return "Enterprise"

def starting_mrr(plan: str) -> float:
  if plan == "Starter":
    return random.choice([49, 79, 99, 129])
  if plan == "Growth":
    return random.choice([299, 399, 499, 599, 799])
  return random.choice([1500, 2000, 2500, 3500, 5000])

def churn_probability(plan: str, tenure_months: int, usage_ratio: float) -> float:
  # Higher churn on Starter; churn decreases with tenure; low usage increases churn.
  base = {"Starter": 0.040, "Growth": 0.020, "Enterprise": 0.010}[plan]
  tenure_factor = max(0.55, 1.15 - 0.03 * min(tenure_months, 18))
  usage_factor = 1.0 + (0.9 - usage_ratio) * 0.9  # if usage_ratio < 0.9 => higher churn
  return min(0.18, max(0.001, base * tenure_factor * usage_factor))

def expansion_probability(plan: str) -> float:
  return {"Starter": 0.06, "Growth": 0.10, "Enterprise": 0.08}[plan]

def contraction_probability(plan: str) -> float:
  return {"Starter": 0.03, "Growth": 0.04, "Enterprise": 0.05}[plan]

def usage_baseline(plan: str) -> Tuple[int, int, int]:
  # active_seats, events, feature_actions
  if plan == "Starter":
    return (random.randint(3, 12), random.randint(20, 120), random.randint(10, 80))
  if plan == "Growth":
    return (random.randint(10, 60), random.randint(120, 900), random.randint(80, 600))
  return (random.randint(40, 200), random.randint(800, 4000), random.randint(600, 3000))

def main():
  random.seed(7)

  end = month_start(date.today())
  start = add_months(end, -24)

  # Acquisition ramps up over time
  months = [add_months(start, i) for i in range(24)]
  new_per_month = [max(6, int(10 + i * 0.6 + random.randint(-2, 3))) for i in range(24)]

  print(f"Seeding from {start} to {end} ...")

  with psycopg.connect(DATABASE_URL) as conn:
    conn.execute("TRUNCATE TABLE product_usage_daily, subscription_events, customers RESTART IDENTITY CASCADE;")

    customers: List[Customer] = []

    # Create customers and "new" events
    for m, n_new in zip(months, new_per_month):
      for _ in range(n_new):
        plan = choose_plan()
        industry = random.choice(INDUSTRIES)
        name = rand_company_name()
        created_at = m + timedelta(days=random.randint(0, 27))
        mrr = float(starting_mrr(plan))

        row = conn.execute(
          "INSERT INTO customers (name, industry, plan, created_at) VALUES (%s,%s,%s,%s) RETURNING customer_id",
          (name, industry, plan, created_at),
        ).fetchone()
        cid = row[0]
        c = Customer(customer_id=str(cid), plan=plan, industry=industry, start_mrr=mrr, current_mrr=mrr)
        customers.append(c)

        # New subscription event
        conn.execute(
          "INSERT INTO subscription_events (customer_id, event_date, event_type, mrr_delta) VALUES (%s,%s,%s,%s)",
          (cid, created_at, "new", mrr),
        )

    # Simulate daily usage + monthly events
    all_days = daterange(start, end + timedelta(days=27))

    # Store per-customer baseline usage and a moving "usage_ratio" (drops before churn)
    usage_state: Dict[str, Dict[str, float]] = {}
    for c in customers:
      seats, events, actions = usage_baseline(c.plan)
      usage_state[c.customer_id] = {
        "seats": float(seats),
        "events": float(events),
        "actions": float(actions),
        "ratio": 1.0,
      }

    for day in all_days:
      # Monthly event day: pick the 1st of month for simplicity
      is_month_tick = (day.day == 1)

      for c in customers:
        if c.churned:
          continue

        st = usage_state[c.customer_id]

        # Usage ratio random walk, with occasional dips (leading indicator)
        drift = random.uniform(-0.03, 0.02)
        st["ratio"] = min(1.15, max(0.25, st["ratio"] + drift))

        # On month ticks, decide churn/expansion/contraction
        if is_month_tick and day >= start:
          tenure_months = (day.year - start.year) * 12 + (day.month - start.month) + 1
          u = st["ratio"]

          # Churn decision
          p_churn = churn_probability(c.plan, tenure_months, u)
          if random.random() < p_churn:
            # Force usage drop before churn (make story consistent)
            st["ratio"] = max(0.15, st["ratio"] - random.uniform(0.25, 0.55))

            # Churned MRR delta is -current_mrr
            conn.execute(
              "INSERT INTO subscription_events (customer_id, event_date, event_type, mrr_delta) VALUES (%s,%s,%s,%s)",
              (c.customer_id, day, "churn", -c.current_mrr),
            )
            c.current_mrr = 0.0
            c.churned = True
            continue

          # Expansion / contraction
          if random.random() < expansion_probability(c.plan):
            delta = round(c.current_mrr * random.uniform(0.08, 0.25), 2)
            conn.execute(
              "INSERT INTO subscription_events (customer_id, event_date, event_type, mrr_delta) VALUES (%s,%s,%s,%s)",
              (c.customer_id, day, "expansion", delta),
            )
            c.current_mrr += float(delta)

          elif random.random() < contraction_probability(c.plan):
            delta = round(c.current_mrr * random.uniform(0.05, 0.18), 2)
            conn.execute(
              "INSERT INTO subscription_events (customer_id, event_date, event_type, mrr_delta) VALUES (%s,%s,%s,%s)",
              (c.customer_id, day, "contraction", -delta),
            )
            c.current_mrr = max(0.0, c.current_mrr - float(delta))

        # Insert usage row (even if low)
        seats = int(max(0, st["seats"] * st["ratio"] + random.uniform(-1, 2)))
        ev = int(max(0, st["events"] * st["ratio"] + random.uniform(-10, 20)))
        act = int(max(0, st["actions"] * st["ratio"] + random.uniform(-10, 20)))

        conn.execute(
          "INSERT INTO product_usage_daily (customer_id, usage_date, active_seats, events, feature_actions) "
          "VALUES (%s,%s,%s,%s,%s) "
          "ON CONFLICT (customer_id, usage_date) DO UPDATE SET "
          "active_seats=EXCLUDED.active_seats, events=EXCLUDED.events, feature_actions=EXCLUDED.feature_actions",
          (c.customer_id, day, seats, ev, act),
        )

    conn.commit()

  print("✅ Seed complete.")

if __name__ == "__main__":
  main()

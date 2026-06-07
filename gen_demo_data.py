#!/usr/bin/env python3
"""Generate realistic fake data for the Net Worth Tracker manual mode."""
import json
import uuid
from pathlib import Path
from datetime import date, timedelta
import random

random.seed(42)

OUT = Path.home() / ".local" / "share" / "home_os" / "networth_manual.json"
OUT.parent.mkdir(parents=True, exist_ok=True)

def uid():
    return str(uuid.uuid4())

# ── Accounts ──────────────────────────────────────────────────────────────────
accounts = [
    {"id": uid(), "name": "Gringotts Checking",    "type": "CHECKING",    "balance": 6_942.00,  "is_liability": False, "color": "#4ade80"},
    {"id": uid(), "name": "Scrooge McDuck HYSA",   "type": "SAVINGS",     "balance": 24_000.00, "is_liability": False, "color": "#60a5fa"},
    {"id": uid(), "name": "Acme Brokerage",        "type": "BROKERAGE",   "balance": 51_337.00, "is_liability": False, "color": "#a78bfa"},
    {"id": uid(), "name": "Vandelay 401(k)",       "type": "401K",        "balance": 98_765.00, "is_liability": False, "color": "#f472b6"},
    {"id": uid(), "name": "Prestige Roth IRA",     "type": "ROTH",        "balance": 31_415.00, "is_liability": False, "color": "#34d399"},
    {"id": uid(), "name": "Fake Bank Mortgage",    "type": "MORTGAGE",    "balance": 188_000.00,"is_liability": True,  "color": "#f87171"},
    {"id": uid(), "name": "Placeholder Visa",      "type": "CREDIT_CARD", "balance":    420.00, "is_liability": True,  "color": "#fb923c"},
]
# Assets: ~212,459  Liabilities: ~188,420  Net worth: ~$24,039

# ── Sinking funds ─────────────────────────────────────────────────────────────
sinking_funds = [
    {"id": uid(), "name": "Emergency Fund",  "color": "#4ade80", "current_cents": 1_800_000, "target_cents": 2_000_000},
    {"id": uid(), "name": "New Car",         "color": "#60a5fa", "current_cents":   920_000, "target_cents": 3_500_000},
    {"id": uid(), "name": "Vacation Fund",   "color": "#f472b6", "current_cents":   450_000, "target_cents":   500_000},
    {"id": uid(), "name": "Home Repairs",    "color": "#fb923c", "current_cents":   310_000, "target_cents":   800_000},
]

# ── Transactions ──────────────────────────────────────────────────────────────
acct_names = [a["name"] for a in accounts if not a["is_liability"]]
checking   = accounts[0]["name"]
savings    = accounts[1]["name"]

expense_cats = [
    ("Fake Grocery Co",      "Food & Dining",    40,  200),
    ("NotNetflix",           "Subscriptions",    15,   20),
    ("PowerCo Electric",     "Utilities",        80,  140),
    ("GasMart",              "Auto & Transport", 40,   80),
    ("Example Restaurant",   "Food & Dining",    20,   90),
    ("lorem ipsum store",    "Shopping",         15,  120),
    ("Totally Real Gym",     "Health",           40,   55),
    ("Coffee Placeholder",   "Food & Dining",     5,   20),
    ("ISP Corp",             "Utilities",        60,   80),
    ("Dr. Placeholder MD",   "Health",           30,  200),
]

transactions = []
today = date.today()

# Six months of history
for months_back in range(5, -1, -1):
    month_start = today.replace(day=1) - timedelta(days=months_back * 30)

    # Salary (1st and 15th)
    for day in (1, 15):
        d = month_start.replace(day=day)
        transactions.append({
            "id": uid(), "date": str(d),
            "note": "Fake Employer Inc - Payroll", "category": "Income",
            "amount": 4_250.00, "type": "INCOME",
            "account": checking, "to_account": "",
            "category_color": "#4ade80", "account_color": "#4ade80",
        })

    # 8–12 expenses spread across the month
    for _ in range(random.randint(8, 12)):
        note, cat, lo, hi = random.choice(expense_cats)
        amt = round(random.uniform(lo, hi), 2)
        day = random.randint(1, 28)
        d = month_start.replace(day=day)
        transactions.append({
            "id": uid(), "date": str(d),
            "note": note, "category": cat,
            "amount": amt, "type": "EXPENSE",
            "account": checking, "to_account": "",
            "category_color": "#888888", "account_color": "#4ade80",
        })

    # Savings transfer mid-month
    d = month_start.replace(day=random.randint(14, 18))
    transactions.append({
        "id": uid(), "date": str(d),
        "note": "Transfer to Savings", "category": "Transfer",
        "amount": 500.00, "type": "TRANSFER",
        "account": checking, "to_account": savings,
        "category_color": "#888888", "account_color": "#4ade80",
    })

# ── History (6 months of snapshots with gentle upward trend) ─────────────────
base_nw = 18_000   # start ~$18k, grow to ~$24k — positive the whole way
history = []
for i in range(180):
    d = today - timedelta(days=179 - i)
    noise = random.gauss(0, 250)
    nw = base_nw + i * 33 + noise   # ~$6k growth over 6 months
    history.append([str(d), round(nw, 2)])
    base_nw = nw

OUT.write_text(json.dumps({
    "accounts":     accounts,
    "transactions": sorted(transactions, key=lambda t: t["date"], reverse=True),
    "sinking_funds": sinking_funds,
    "history":      history,
}, indent=2))

# Also set QSettings source to 'manual'
from PyQt6.QtCore import QSettings
QSettings("HomeOS", "NetWorth").setValue("networth_source", "manual")

print(f"Demo data written to {OUT}")
print(f"  {len(accounts)} accounts")
print(f"  {len(sinking_funds)} sinking funds")
print(f"  {len(transactions)} transactions")
print(f"  {len(history)} history points")
print("QSettings source set to 'manual'")

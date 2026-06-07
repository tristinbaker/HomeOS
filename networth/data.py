import json
import sqlite3
import subprocess
import tempfile
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

BACKUP_DIR_DEVICE = "/storage/emulated/0/Backups/LifeOS"
DB_NAME = "lifeos_financetracker.db"
CACHE_PATH = Path.home() / ".local" / "share" / "home_os" / "networth.json"

_LIABILITY_TYPES = frozenset({'MORTGAGE', 'LOAN', 'CREDIT_CARD', 'CREDIT', 'DEBT'})


@dataclass
class AccountBalance:
    id: int
    name: str
    type: str
    color: str
    balance: float
    is_liability: bool


@dataclass
class SinkingFund:
    name: str
    color: str
    current_cents: int
    target_cents: int


@dataclass
class MortgageInfo:
    current_balance: float
    apr_percent: float
    remaining_months: int
    monthly_payment: float


@dataclass
class Transaction:
    date: str           # "YYYY-MM-DD"
    note: str
    category: str
    amount: float
    type: str           # INCOME | EXPENSE | TRANSFER
    account: str
    to_account: str     # "" if not a transfer
    category_color: str
    account_color: str


@dataclass
class NetWorthSnapshot:
    fetched_at: str
    net_worth: float
    total_assets: float
    total_liabilities: float
    accounts: list          # list[AccountBalance]
    history: list           # list of (date_str, net_worth_float)
    sinking_funds: list     # list[SinkingFund]
    mortgage: object        # MortgageInfo | None
    transactions: list      # list[Transaction]


def _find_latest_backup() -> str:
    r = subprocess.run(
        ["adb", "-d", "shell", f"ls -t {BACKUP_DIR_DEVICE}/*.zip"],
        capture_output=True, text=True,
    )
    if r.returncode != 0 or not r.stdout.strip():
        raise RuntimeError(f"Could not list backups: {r.stderr.strip()}")
    return r.stdout.strip().splitlines()[0].strip()


def pull_db() -> Path:
    tmp_zip = Path(tempfile.mktemp(suffix=".zip", prefix="lifeos_backup_"))
    tmp_db  = Path(tempfile.mktemp(suffix=".db",  prefix="lifeos_finance_"))

    backup_path = _find_latest_backup()
    r = subprocess.run(["adb", "-d", "pull", backup_path, str(tmp_zip)], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"adb pull failed: {r.stderr.strip()}")

    with zipfile.ZipFile(tmp_zip) as zf:
        match = next((n for n in zf.namelist() if DB_NAME in n), None)
        if match is None:
            raise RuntimeError(f"{DB_NAME} not found in backup ZIP")
        tmp_db.write_bytes(zf.read(match))

    tmp_zip.unlink(missing_ok=True)
    return tmp_db


def fetch_snapshot(db_path: Path) -> NetWorthSnapshot:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    accounts_raw = {
        r["id"]: dict(r)
        for r in conn.execute(
            "SELECT * FROM lifeos_financetracker_accounts WHERE isActive = 1"
        )
    }

    # Latest snapshot balance per account
    snapshots: dict[int, float] = {}
    for r in conn.execute(
        """
        SELECT accountId, balance
        FROM lifeos_financetracker_account_snapshots
        WHERE (accountId, date) IN (
            SELECT accountId, MAX(date)
            FROM lifeos_financetracker_account_snapshots
            GROUP BY accountId
        )
        """
    ):
        snapshots[r["accountId"]] = r["balance"]

    # Mortgage details keyed by accountId
    mortgages: dict[int, dict] = {
        r["accountId"]: dict(r)
        for r in conn.execute("SELECT * FROM lifeos_financetracker_mortgage_details")
    }

    # Transaction-derived balance per account
    computed: dict[int, float] = {}
    for r in conn.execute(
        """
        SELECT
            a.id,
            a.startingBalance + COALESCE(SUM(
                CASE
                    WHEN t.type = 'INCOME'   AND t.accountId   = a.id THEN  t.amount
                    WHEN t.type = 'EXPENSE'  AND t.accountId   = a.id THEN -t.amount
                    WHEN t.type = 'TRANSFER' AND t.toAccountId = a.id THEN  t.amount
                    WHEN t.type = 'TRANSFER' AND t.accountId   = a.id THEN -t.amount
                    ELSE 0
                END
            ), 0) AS balance
        FROM lifeos_financetracker_accounts a
        LEFT JOIN lifeos_financetracker_transactions t
            ON t.accountId = a.id OR t.toAccountId = a.id
        WHERE a.isActive = 1
        GROUP BY a.id
        """
    ):
        computed[r["id"]] = r["balance"]

    accounts: list[AccountBalance] = []
    for acct_id, acct in accounts_raw.items():
        acct_type = acct["type"].upper()
        is_liability = acct_type in _LIABILITY_TYPES

        if acct_id in mortgages:
            balance = mortgages[acct_id]["currentBalance"]
            is_liability = True
        elif acct_id in snapshots:
            balance = snapshots[acct_id]
        else:
            balance = computed.get(acct_id, acct["startingBalance"])

        accounts.append(AccountBalance(
            id=acct_id,
            name=acct["name"],
            type=acct_type,
            color=acct["colorHex"],
            balance=balance,
            is_liability=is_liability,
        ))

    # Net worth totals from app's own history — skip rows where app wrote zeros (app bug)
    latest = conn.execute(
        """
        SELECT totalAssets, totalLiabilities, netWorth
        FROM lifeos_financetracker_networth_history
        WHERE totalAssets != 0
        ORDER BY date DESC LIMIT 1
        """
    ).fetchone()

    total_assets      = latest["totalAssets"]      if latest else sum(a.balance for a in accounts if not a.is_liability)
    total_liabilities = latest["totalLiabilities"] if latest else sum(a.balance for a in accounts if a.is_liability)
    net_worth         = latest["netWorth"]          if latest else total_assets - total_liabilities

    # Chart history — exclude zero-asset rows (app bug: records 0/0/0 on some days)
    history = [
        (r["date"], r["netWorth"])
        for r in conn.execute(
            """
            SELECT date, netWorth
            FROM lifeos_financetracker_networth_history
            WHERE totalAssets != 0
            ORDER BY date ASC
            """
        )
    ]

    # Sinking funds
    contributions: dict[int, int] = {}
    for r in conn.execute(
        "SELECT fundId, SUM(amountCents) AS total FROM lifeos_financetracker_sinking_contributions GROUP BY fundId"
    ):
        contributions[r["fundId"]] = r["total"]

    sinking_funds: list[SinkingFund] = []
    for r in conn.execute(
        "SELECT * FROM lifeos_financetracker_sinking_funds WHERE isActive = 1 ORDER BY targetDate ASC"
    ):
        current = r["initialBalanceCents"] + contributions.get(r["id"], 0)
        sinking_funds.append(SinkingFund(
            name=r["name"],
            color=r["colorHex"],
            current_cents=current,
            target_cents=r["targetAmountCents"],
        ))

    mortgage = None
    if mortgages:
        m = next(iter(mortgages.values()))
        mortgage = MortgageInfo(
            current_balance=m["currentBalance"],
            apr_percent=m["aprPercent"],
            remaining_months=m["remainingMonths"],
            monthly_payment=m["monthlyPayment"],
        )

    # All transactions, newest first
    transactions: list[Transaction] = []
    for r in conn.execute(
        """
        SELECT
            t.date,
            COALESCE(NULLIF(t.note, ''),
                CASE t.type
                    WHEN 'TRANSFER' THEN 'Transfer'
                    WHEN 'INCOME'   THEN 'Income'
                    ELSE 'Expense'
                END
            ) AS note,
            COALESCE(c.name, 'Uncategorized') AS category,
            t.amount,
            t.type,
            a.name  AS account,
            COALESCE(ta.name, '') AS to_account,
            COALESCE(c.colorHex,  '#888888') AS category_color,
            a.colorHex AS account_color
        FROM lifeos_financetracker_transactions t
        LEFT JOIN lifeos_financetracker_categories c  ON t.categoryId  = c.id
        JOIN  lifeos_financetracker_accounts      a   ON t.accountId   = a.id
        LEFT JOIN lifeos_financetracker_accounts  ta  ON t.toAccountId = ta.id
        ORDER BY t.date DESC, t.createdAt DESC
        """
    ):
        transactions.append(Transaction(
            date=r["date"],
            note=r["note"],
            category=r["category"],
            amount=r["amount"],
            type=r["type"],
            account=r["account"],
            to_account=r["to_account"],
            category_color=r["category_color"],
            account_color=r["account_color"],
        ))

    conn.close()

    return NetWorthSnapshot(
        fetched_at=datetime.now().isoformat(),
        net_worth=net_worth,
        total_assets=total_assets,
        total_liabilities=total_liabilities,
        accounts=accounts,
        history=history,
        sinking_funds=sinking_funds,
        mortgage=mortgage,
        transactions=transactions,
    )


def save_cache(snapshot: NetWorthSnapshot) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "fetched_at": snapshot.fetched_at,
        "net_worth": snapshot.net_worth,
        "total_assets": snapshot.total_assets,
        "total_liabilities": snapshot.total_liabilities,
        "accounts": [
            {
                "id": a.id, "name": a.name, "type": a.type,
                "color": a.color, "balance": a.balance, "is_liability": a.is_liability,
            }
            for a in snapshot.accounts
        ],
        "history": [[d, v] for d, v in snapshot.history],
        "sinking_funds": [
            {"name": f.name, "color": f.color,
             "current_cents": f.current_cents, "target_cents": f.target_cents}
            for f in snapshot.sinking_funds
        ],
        "mortgage": (
            {
                "current_balance": snapshot.mortgage.current_balance,
                "apr_percent": snapshot.mortgage.apr_percent,
                "remaining_months": snapshot.mortgage.remaining_months,
                "monthly_payment": snapshot.mortgage.monthly_payment,
            }
            if snapshot.mortgage else None
        ),
        "transactions": [
            {
                "date": t.date, "note": t.note, "category": t.category,
                "amount": t.amount, "type": t.type, "account": t.account,
                "to_account": t.to_account, "category_color": t.category_color,
                "account_color": t.account_color,
            }
            for t in snapshot.transactions
        ],
    }
    CACHE_PATH.write_text(json.dumps(data, indent=2))


# ── Manual mode data ──────────────────────────────────────────────────────────

MANUAL_PATH = Path.home() / ".local" / "share" / "home_os" / "networth_manual.json"


@dataclass
class ManualAccount:
    id: str
    name: str
    type: str
    balance: float
    is_liability: bool
    color: str


@dataclass
class ManualTransaction:
    id: str
    date: str           # "YYYY-MM-DD"
    note: str
    category: str
    amount: float
    type: str           # INCOME | EXPENSE | TRANSFER
    account: str
    to_account: str
    category_color: str
    account_color: str


@dataclass
class ManualSinkingFund:
    id: str
    name: str
    color: str
    current_cents: int
    target_cents: int


@dataclass
class ManualData:
    accounts: list = field(default_factory=list)        # list[ManualAccount]
    transactions: list = field(default_factory=list)    # list[ManualTransaction]
    sinking_funds: list = field(default_factory=list)   # list[ManualSinkingFund]
    history: list = field(default_factory=list)         # list of [date_str, float]


def load_manual() -> ManualData:
    if not MANUAL_PATH.exists():
        return ManualData()
    try:
        d = json.loads(MANUAL_PATH.read_text())
        return ManualData(
            accounts=[ManualAccount(**a) for a in d.get('accounts', [])],
            transactions=[ManualTransaction(**t) for t in d.get('transactions', [])],
            sinking_funds=[ManualSinkingFund(**f) for f in d.get('sinking_funds', [])],
            history=[[r[0], r[1]] for r in d.get('history', [])],
        )
    except Exception:
        return ManualData()


def save_manual(data: ManualData) -> None:
    MANUAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANUAL_PATH.write_text(json.dumps({
        'accounts': [
            {'id': a.id, 'name': a.name, 'type': a.type, 'balance': a.balance,
             'is_liability': a.is_liability, 'color': a.color}
            for a in data.accounts
        ],
        'transactions': [
            {'id': t.id, 'date': t.date, 'note': t.note, 'category': t.category,
             'amount': t.amount, 'type': t.type, 'account': t.account,
             'to_account': t.to_account, 'category_color': t.category_color,
             'account_color': t.account_color}
            for t in data.transactions
        ],
        'sinking_funds': [
            {'id': f.id, 'name': f.name, 'color': f.color,
             'current_cents': f.current_cents, 'target_cents': f.target_cents}
            for f in data.sinking_funds
        ],
        'history': [[d, v] for d, v in data.history],
    }, indent=2))


def manual_record_snapshot(data: ManualData) -> None:
    """Upsert today's net worth into the history list."""
    today = datetime.now().strftime('%Y-%m-%d')
    assets = sum(a.balance for a in data.accounts if not a.is_liability)
    debts  = sum(a.balance for a in data.accounts if a.is_liability)
    nw = assets - debts
    for i, (d, _) in enumerate(data.history):
        if d == today:
            data.history[i] = [today, nw]
            return
    data.history.append([today, nw])
    data.history.sort(key=lambda r: r[0])


def manual_to_snapshot(data: ManualData) -> NetWorthSnapshot:
    accounts = [
        AccountBalance(id=i, name=a.name, type=a.type, color=a.color,
                       balance=a.balance, is_liability=a.is_liability)
        for i, a in enumerate(data.accounts)
    ]
    total_assets      = sum(a.balance for a in data.accounts if not a.is_liability)
    total_liabilities = sum(a.balance for a in data.accounts if a.is_liability)
    net_worth = total_assets - total_liabilities

    sinking_funds = [
        SinkingFund(name=f.name, color=f.color,
                    current_cents=f.current_cents, target_cents=f.target_cents)
        for f in data.sinking_funds
    ]
    transactions = sorted(
        [Transaction(date=t.date, note=t.note, category=t.category,
                     amount=t.amount, type=t.type, account=t.account,
                     to_account=t.to_account, category_color=t.category_color,
                     account_color=t.account_color)
         for t in data.transactions],
        key=lambda t: t.date, reverse=True,
    )
    return NetWorthSnapshot(
        fetched_at=datetime.now().isoformat(),
        net_worth=net_worth,
        total_assets=total_assets,
        total_liabilities=total_liabilities,
        accounts=accounts,
        history=[(r[0], r[1]) for r in data.history],
        sinking_funds=sinking_funds,
        mortgage=None,
        transactions=transactions,
    )


def new_manual_id() -> str:
    return str(uuid.uuid4())


def load_cache() -> NetWorthSnapshot | None:
    if not CACHE_PATH.exists():
        return None
    try:
        d = json.loads(CACHE_PATH.read_text())
        return NetWorthSnapshot(
            fetched_at=d["fetched_at"],
            net_worth=d["net_worth"],
            total_assets=d["total_assets"],
            total_liabilities=d["total_liabilities"],
            accounts=[AccountBalance(**a) for a in d["accounts"]],
            history=[(row[0], row[1]) for row in d["history"]],
            sinking_funds=[SinkingFund(**f) for f in d["sinking_funds"]],
            mortgage=MortgageInfo(**d["mortgage"]) if d["mortgage"] else None,
            transactions=[Transaction(**t) for t in d.get("transactions", [])],
        )
    except Exception:
        return None

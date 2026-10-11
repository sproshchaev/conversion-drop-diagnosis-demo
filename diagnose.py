#!/usr/bin/env python3
"""Diagnoses an overnight conversion drop step by step.

1. What the dashboard shows: conversion by analytics `purchase` events.
2. Is the metric counted correctly: events reconciled with billing.
3. Honest conversion on billing orders.
4. Mix shift vs segment rates decomposition.

Standard library only: csv + sqlite3.
"""
import csv
import sqlite3
from pathlib import Path

DATA = Path(__file__).parent / "data"
TUE, WED = "2026-10-06", "2026-10-07"
PLATFORMS = ["web", "android", "ios"]
USER_TYPES = ["new", "returning"]

# The reconciliation query from the article, SQLite dialect
# (date_trunc('hour', ...) becomes substr(..., 1, 13)).
RECONCILE_SQL = """
SELECT b.platform,
       substr(b.paid_at, 1, 13)  AS hour,
       count(*)                  AS orders_billing,
       count(e.order_id)         AS purchase_events,
       round(1 - count(e.order_id) * 1.0 / count(*), 3) AS gap
FROM billing_orders b
LEFT JOIN purchase_events e ON e.order_id = b.order_id
WHERE b.paid_at >= :since
GROUP BY 1, 2
ORDER BY 1, 2
"""


def load():
    db = sqlite3.connect(":memory:")
    for name in ["sessions", "billing_orders", "purchase_events"]:
        with open(DATA / f"{name}.csv", newline="") as f:
            rows = list(csv.reader(f))
        cols = ", ".join(rows[0])
        marks = ", ".join("?" * len(rows[0]))
        db.execute(f"CREATE TABLE {name} ({cols})")
        db.executemany(f"INSERT INTO {name} VALUES ({marks})", rows[1:])
    return db


def counts(db):
    """(day, platform, user_type) -> [sessions, events, billing orders]"""
    out = {}
    for d, p, u, s in db.execute("SELECT date, platform, user_type, sessions FROM sessions"):
        out[(d, p, u)] = [int(s), 0, 0]
    for d, p, u, n in db.execute(
            "SELECT substr(event_time, 1, 10), platform, user_type, count(*) "
            "FROM purchase_events GROUP BY 1, 2, 3"):
        out[(d, p, u)][1] = n
    for d, p, u, n in db.execute(
            "SELECT substr(paid_at, 1, 10), platform, user_type, count(*) "
            "FROM billing_orders GROUP BY 1, 2, 3"):
        out[(d, p, u)][2] = n
    return out


def agg(c, day, platforms=PLATFORMS, user_types=USER_TYPES):
    s = e = b = 0
    for p in platforms:
        for u in user_types:
            row = c[(day, p, u)]
            s, e, b = s + row[0], e + row[1], b + row[2]
    return s, e, b


def pct(x):
    return f"{x * 100:.2f}%"


def num(x):
    return f"{x:,}".replace(",", " ")


def table_dashboard(c):
    print("Table 1. Dashboard: conversion by purchase events")
    print(f"{'platform':<10}{'sess tue':>10}{'buy tue':>9}{'CR tue':>8}"
          f"{'sess wed':>10}{'buy wed':>9}{'CR wed':>8}{'change':>9}")
    for label, plats in [(p, [p]) for p in PLATFORMS] + [("total", PLATFORMS)]:
        s1, e1, _ = agg(c, TUE, plats)
        s2, e2, _ = agg(c, WED, plats)
        r1, r2 = e1 / s1, e2 / s2
        print(f"{label:<10}{num(s1):>10}{num(e1):>9}{pct(r1):>8}"
              f"{num(s2):>10}{num(e2):>9}{pct(r2):>8}{(r2 / r1 - 1) * 100:>+8.1f}%")


def table_segments(c):
    print("Table 2. Dashboard by new and returning users (purchase events)")
    print(f"{'segment':<20}{'sess tue':>10}{'buy tue':>9}{'CR tue':>8}"
          f"{'sess wed':>10}{'buy wed':>9}{'CR wed':>8}")
    for p in PLATFORMS:
        for u in USER_TYPES:
            s1, e1, _ = c[(TUE, p, u)]
            s2, e2, _ = c[(WED, p, u)]
            print(f"{p + ', ' + u:<20}{num(s1):>10}{num(e1):>9}{pct(e1 / s1):>8}"
                  f"{num(s2):>10}{num(e2):>9}{pct(e2 / s2):>8}")


def table_billing(c):
    print("Table 3. Paid orders in billing")
    print(f"{'platform':<10}{'tue':>8}{'wed':>8}")
    for label, plats in [(p, [p]) for p in PLATFORMS] + [("total", PLATFORMS)]:
        print(f"{label:<10}{num(agg(c, TUE, plats)[2]):>8}{num(agg(c, WED, plats)[2]):>8}")


def reconcile(db):
    print("Step 1. Events vs billing, Wednesday")
    rows = db.execute(RECONCILE_SQL, {"since": WED}).fetchall()
    for p in PLATFORMS:
        mine = [r for r in rows if r[0] == p]
        bill = sum(r[2] for r in mine)
        ev = sum(r[3] for r in mine)
        before = [r for r in mine if int(r[1][-2:]) < 6]
        after = [r for r in mine if int(r[1][-2:]) >= 6]
        gb = 1 - sum(r[3] for r in before) / sum(r[2] for r in before)
        ga = 1 - sum(r[3] for r in after) / sum(r[2] for r in after)
        print(f"  {p:<8} billing {num(bill):>6}  events {num(ev):>6}  "
              f"gap day {(1 - ev / bill) * 100:5.1f}%  "
              f"before 06:00 {gb * 100:5.1f}%  from 06:00 {ga * 100:5.1f}%")
    print("  ios by app version, Wednesday:")
    for v, b, e in db.execute(
            "SELECT b.app_version, count(*), count(e.order_id) FROM billing_orders b "
            "LEFT JOIN purchase_events e ON e.order_id = b.order_id "
            "WHERE b.platform = 'ios' AND b.paid_at >= :since GROUP BY 1 ORDER BY 1",
            {"since": WED}):
        print(f"    {v}: billing {num(b)}  events {num(e)}  gap {(1 - e / b) * 100:.1f}%")


def honest(c):
    s1, e1, b1 = agg(c, TUE)
    s2, e2, b2 = agg(c, WED)
    print("Step 2. Honest conversion on billing orders")
    print(f"  tue {pct(b1 / s1)}  wed {pct(b2 / s2)}  change {(b2 / s2 / (b1 / s1) - 1) * 100:+.1f}%")
    print(f"  sessions {(s2 / s1 - 1) * 100:+.1f}%  billing orders {(b2 / b1 - 1) * 100:+.1f}%")
    n1 = agg(c, TUE, user_types=["new"])[0] / s1
    n2 = agg(c, WED, user_types=["new"])[0] / s2
    print(f"  share of new users {n1 * 100:.1f}% -> {n2 * 100:.1f}%")


def decompose(c):
    keys = [(p, u) for p in PLATFORMS for u in USER_TYPES]
    s1, e1, b1 = agg(c, TUE)
    s2, e2, b2 = agg(c, WED)
    w1 = {k: c[(TUE, *k)][0] / s1 for k in keys}
    w2 = {k: c[(WED, *k)][0] / s2 for k in keys}
    r1 = {k: c[(TUE, *k)][2] / c[(TUE, *k)][0] for k in keys}
    r2 = {k: c[(WED, *k)][2] / c[(WED, *k)][0] for k in keys}
    mix = sum((w2[k] - w1[k]) * r1[k] for k in keys)
    rate = sum(w1[k] * (r2[k] - r1[k]) for k in keys)
    cross = (b2 / s2 - b1 / s1) - mix - rate
    tracking = e2 / s2 - b2 / s2
    grown = sum(r2[k] > r1[k] for k in keys)
    print("Step 3. Where the -0.52 pp came from")
    print(f"  dashboard           {pct(e1 / s1)} -> {pct(e2 / s2)}  {(e2 / s2 - e1 / s1) * 100:+.2f} pp")
    print(f"  broken iOS tracking {tracking * 100:+.2f} pp")
    print(f"  mix shift           {mix * 100:+.2f} pp")
    print(f"  segment rates       {rate * 100:+.2f} pp  (grew in {grown} of {len(keys)} segments)")
    print(f"  cross term          {cross * 100:+.2f} pp")


def main():
    db = load()
    c = counts(db)
    for step in (table_dashboard, table_segments, table_billing):
        step(c)
        print()
    reconcile(db)
    print()
    honest(c)
    print()
    decompose(c)


if __name__ == "__main__":
    main()

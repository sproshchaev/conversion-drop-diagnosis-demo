#!/usr/bin/env python3
"""Generates the demo dataset with a fixed seed.

Two days of an online store: Tuesday 2026-10-06 and Wednesday 2026-10-07.
On Wednesday two things happen at once:
  * at 06:00 iOS app 5.2 ships a new payment screen that does not always
    send the `purchase` analytics event (billing still records every order);
  * a Telegram campaign brings many new users to web and Android.

Usage:
  python3 gen_data.py            # write data/*.csv
  python3 gen_data.py --check    # regenerate in memory and compare with data/
"""
import csv
import io
import random
import sys
from pathlib import Path

SEED = 144
DATA = Path(__file__).parent / "data"
DAYS = {"tue": "2026-10-06", "wed": "2026-10-07"}

# (platform, user_type) -> (sessions, paid orders in billing)
SEGMENTS = {
    "tue": {
        ("web", "new"): (20000, 300), ("web", "returning"): (30000, 1350),
        ("android", "new"): (10000, 150), ("android", "returning"): (20000, 900),
        ("ios", "new"): (8000, 160), ("ios", "returning"): (22000, 1210),
    },
    "wed": {
        ("web", "new"): (31000, 496), ("web", "returning"): (30500, 1403),
        ("android", "new"): (17000, 272), ("android", "returning"): (20200, 929),
        ("ios", "new"): (9000, 189), ("ios", "returning"): (22300, 1249),
    },
}

# sessions by platform and traffic source; per-platform totals match SEGMENTS.
# Web uses UTM tags, app sessions rely on install attribution (Universal Links / App Links).
SOURCES = {
    "tue": {
        "web": {"direct": 20000, "search": 20000, "other": 10000, "telegram": 0},
        "android": {"direct": 12000, "search": 10000, "other": 8000, "telegram": 0},
        "ios": {"direct": 13000, "search": 10000, "other": 7000, "telegram": 0},
    },
    "wed": {
        "web": {"direct": 20300, "search": 20200, "other": 10000, "telegram": 11000},
        "android": {"direct": 12100, "search": 10000, "other": 8100, "telegram": 7000},
        "ios": {"direct": 13100, "search": 10100, "other": 7100, "telegram": 1000},
    },
}

# orders on iOS 5.2 that never reach analytics, per user type
LOST_EVENTS = {("ios", "new"): 53, ("ios", "returning"): 350}

RELEASE_HOUR = 6
APP_VERSION = {"web": "", "android": "8.14"}

# relative order volume by hour of day
HOUR_WEIGHTS = [2, 1, 1, 1, 1, 2, 3, 4, 5, 6, 6, 6,
                7, 7, 6, 6, 6, 7, 8, 9, 9, 8, 6, 3]


def ios_version(day, hour):
    return "5.2" if day == "wed" and hour >= RELEASE_HOUR else "5.1"


def build():
    rnd = random.Random(SEED)
    sessions, orders, events = [], [], []
    seq = 0
    for day, date in DAYS.items():
        day_orders = []
        for (platform, user_type), (n_sessions, n_orders) in SEGMENTS[day].items():
            sessions.append([date, platform, user_type, n_sessions])
            for _ in range(n_orders):
                hour = rnd.choices(range(24), weights=HOUR_WEIGHTS)[0]
                minute, second = rnd.randrange(60), rnd.randrange(60)
                version = (ios_version(day, hour) if platform == "ios"
                           else APP_VERSION[platform])
                day_orders.append([f"{date} {hour:02d}:{minute:02d}:{second:02d}",
                                   platform, version, user_type])
        day_orders.sort()
        lost = set()
        if day == "wed":
            for seg, k in LOST_EVENTS.items():
                pool = [i for i, o in enumerate(day_orders)
                        if (o[1], o[3]) == seg and o[2] == "5.2"]
                lost.update(rnd.sample(pool, k))
        for i, (paid_at, platform, version, user_type) in enumerate(day_orders):
            seq += 1
            order_id = f"o{seq:06d}"
            orders.append([order_id, paid_at, platform, version, user_type])
            if i not in lost:
                events.append([order_id, paid_at, platform, user_type])
    by_source = [[DAYS[d], p, src, n] for d in DAYS
                 for p, srcs in SOURCES[d].items() for src, n in srcs.items()]
    for d in DAYS:
        for p in SOURCES[d]:
            total = sum(SEGMENTS[d][(p, u)][0] for u in ("new", "returning"))
            assert sum(SOURCES[d][p].values()) == total, (d, p)
    return {
        "sessions_by_source.csv": (["date", "platform", "source", "sessions"],
                                   by_source),
        "sessions.csv": (["date", "platform", "user_type", "sessions"], sessions),
        "billing_orders.csv": (["order_id", "paid_at", "platform", "app_version",
                                "user_type"], orders),
        "purchase_events.csv": (["order_id", "event_time", "platform",
                                 "user_type"], events),
    }


def render(header, rows):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    w.writerows(rows)
    return buf.getvalue()


def main():
    files = {name: render(*spec) for name, spec in build().items()}
    if "--check" in sys.argv:
        bad = [n for n, text in files.items()
               if not (DATA / n).exists() or (DATA / n).read_text() != text]
        if bad:
            print("data differs from generator:", ", ".join(bad))
            sys.exit(1)
        print("data matches generator")
        return
    DATA.mkdir(exist_ok=True)
    for name, text in files.items():
        (DATA / name).write_text(text)
        print("written", DATA / name)


if __name__ == "__main__":
    main()

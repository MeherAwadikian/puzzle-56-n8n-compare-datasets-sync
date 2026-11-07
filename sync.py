#!/usr/bin/env python3
"""
Puzzle 56 - sync two databases (standalone substitute for the n8n
Compare Datasets node).

This reproduces the EXACT mechanic of n8n's Compare Datasets node against two
real SQLite databases:

  * read every row from the SOURCE db (authoritative / desired state) and the
    TARGET db (the copy being kept in sync),
  * compare them keyed on a chosen field (`sku`), splitting rows into the same
    four buckets the node emits:
        - "In A only"  -> present in source, missing in target   -> INSERT
        - "In B only"  -> present in target, missing in source   -> DELETE
        - "Different"  -> key matches but a compared field differs -> UPDATE
        - "Same"       -> key matches and all fields equal        -> no-op
  * APPLY those changes to the target db (real INSERT / UPDATE / DELETE), and
  * VERIFY the target now equals the source, row-for-row.

Run:  python sync.py            (uses ./source.db and ./target.db, seeding a
                                 deliberately-drifted demo if they don't exist)
      python sync.py --reset    (rebuild the demo databases from scratch first)
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE_DB = HERE / "source.db"
TARGET_DB = HERE / "target.db"

KEY = "sku"
# Fields compared to decide "Different". `sku` is the key, so it is excluded.
COMPARE_FIELDS = ["name", "price", "stock"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    sku   TEXT PRIMARY KEY,
    name  TEXT NOT NULL,
    price INTEGER NOT NULL,
    stock INTEGER NOT NULL
);
"""

# Desired state (source of truth).
SOURCE_SEED = [
    ("SKU-1", "Widget", 10, 100),
    ("SKU-2", "Gadget", 25, 40),   # price 25
    ("SKU-3", "Gizmo", 15, 7),     # only in source -> must be INSERTed into target
]

# Current target state, deliberately drifted from source.
TARGET_SEED = [
    ("SKU-1", "Widget", 10, 100),      # identical           -> Same
    ("SKU-2", "Gadget", 20, 40),       # stale price 20      -> Different -> UPDATE
    ("SKU-4", "Doohickey", 30, 5),     # only in target      -> In B only -> DELETE
]


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def seed(path: Path, rows: list[tuple]) -> None:
    conn = connect(path)
    with conn:
        conn.executescript(SCHEMA)
        conn.execute("DELETE FROM products")
        conn.executemany(
            "INSERT INTO products (sku, name, price, stock) VALUES (?, ?, ?, ?)",
            rows,
        )
    conn.close()


def read_all(path: Path) -> dict[str, dict]:
    """Return {key_value: row_dict} for every row in the products table."""
    conn = connect(path)
    conn.executescript(SCHEMA)  # tolerate an empty db
    rows = {r[KEY]: dict(r) for r in conn.execute("SELECT * FROM products")}
    conn.close()
    return rows


def compare_datasets(source: dict[str, dict], target: dict[str, dict]):
    """The Compare Datasets mechanic. Returns the four buckets."""
    added, removed, changed, same = [], [], [], []
    for key, srow in source.items():
        if key not in target:
            added.append(srow)                       # In A only
        elif any(srow[f] != target[key][f] for f in COMPARE_FIELDS):
            changed.append(srow)                     # Different (prefer source)
        else:
            same.append(srow)                        # Same
    for key, trow in target.items():
        if key not in source:
            removed.append(trow)                     # In B only
    return added, removed, changed, same


def apply_sync(target_path: Path, added, removed, changed) -> None:
    """Write the detected diff to the real target database."""
    conn = connect(target_path)
    with conn:
        for row in removed:
            conn.execute("DELETE FROM products WHERE sku = ?", (row[KEY],))
        for row in changed:
            conn.execute(
                "UPDATE products SET name=?, price=?, stock=? WHERE sku=?",
                (row["name"], row["price"], row["stock"], row[KEY]),
            )
        for row in added:
            conn.execute(
                "INSERT INTO products (sku, name, price, stock) VALUES (?, ?, ?, ?)",
                (row[KEY], row["name"], row["price"], row["stock"]),
            )
    conn.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true",
                    help="rebuild the demo databases before syncing")
    args = ap.parse_args()

    if args.reset or not SOURCE_DB.exists() or not TARGET_DB.exists():
        seed(SOURCE_DB, SOURCE_SEED)
        seed(TARGET_DB, TARGET_SEED)

    source = read_all(SOURCE_DB)
    target_before = read_all(TARGET_DB)

    added, removed, changed, same = compare_datasets(source, target_before)

    print("Compare Datasets (keyed on %s):" % KEY)
    print("  In A only (added)      ->", sorted(r[KEY] for r in added))
    print("  In B only (removed)    ->", sorted(r[KEY] for r in removed))
    print("  Different (changed)    ->", sorted(r[KEY] for r in changed))
    print("  Same (unchanged)       ->", sorted(r[KEY] for r in same))

    apply_sync(TARGET_DB, added, removed, changed)

    target_after = read_all(TARGET_DB)
    in_sync = target_after == source

    print()
    print("target rows before:", len(target_before), "->  after:", len(target_after))
    print("applied: INSERT=%d  UPDATE=%d  DELETE=%d  NOOP=%d"
          % (len(added), len(changed), len(removed), len(same)))
    print("target == source after sync:", in_sync)
    if not in_sync:
        print("MISMATCH! target_after:", target_after, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

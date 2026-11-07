# Puzzle 56 - Sync two databases with n8n's Compare Datasets node

**Brief (2026-03-12):** build an n8n workflow that syncs two databases using the
**Compare Datasets** node, detecting added / removed / changed rows and applying
them so the target ends up matching the source.

This repo ships two faithful implementations of the same mechanic:

1. **`workflow.json`** - a real, schema-correct n8n workflow built around
   `n8n-nodes-base.compareDatasets` (typeVersion **2.3**), validated against the
   live container's compiled node source.
2. **`sync.py`** - a runnable standalone substitute that performs the identical
   compare-and-sync against two **real SQLite databases**, applying real
   `INSERT` / `UPDATE` / `DELETE` and verifying the target equals the source
   afterward.

Both produce the same four-way split, and the standalone run cross-validates the
live n8n node output.

---

## The Compare Datasets mechanic

The node takes **two inputs** and matches rows on a key you choose (`field1` of
input A vs `field2` of input B). It has **four outputs**, confirmed from the
compiled node source in the running container:

```
outputNames: ['In A only', 'Same', 'Different', 'In B only']
```

Mapped to a one-directional sync (Input A = source/desired, Input B = target/current):

| Output        | Meaning                              | Sync action        |
|---------------|--------------------------------------|--------------------|
| `In A only`   | in source, not in target             | **INSERT** target  |
| `Same`        | key matches, all compared fields equal | no-op            |
| `Different`   | key matches, a field differs         | **UPDATE** target  |
| `In B only`   | in target, not in source             | **DELETE** target  |

`resolve: "preferInput1"` makes the `Different` output carry the **source**
(desired) values, which is exactly what you write back on update. This is the
same pattern n8n's own "sync users" templates use (each output drives its own
independent write; the outputs are not re-merged).

---

## The n8n workflow (`workflow.json`)

```
Manual Trigger
   |-> Source DB (desired)  --\
   |                           >-- Compare Datasets --+-- In A only  -> INSERT into target
   |-> Target DB (current)  --/   (merge on sku,      +-- Same       -> No change
                                   resolve preferInput1)+-- Different -> UPDATE target
                                                        +-- In B only -> DELETE from target
```

- `Source DB` / `Target DB` are `Code` nodes seeding a deliberately-drifted demo
  (in production these would be Postgres / Supabase / HTTP / n8n Data Table
  reads). Replace them with your real reads; the Compare Datasets node and its
  wiring do not change.
- The two source branches feed **input 0 and input 1** of Compare Datasets
  (set via the `index` field on the connections).

### Node schema used (verified against n8n 2.21.7 compiled source)

```json
{
  "type": "n8n-nodes-base.compareDatasets",
  "typeVersion": 2.3,
  "parameters": {
    "mergeByFields": { "values": [ { "field1": "sku", "field2": "sku" } ] },
    "resolve": "preferInput1",
    "options": {}
  }
}
```
Valid `resolve` values: `preferInput1`, `preferInput2`, `mix`, `includeBoth`.

### Live import + run status (honest)

The local n8n Docker container runs on the machine's flaky D: drive (see the
recurring Docker/D: note across prior n8n puzzles #29/#34/#42/#53). **This
session the container actually came up** (n8n `2.21.7`, reachable at
`localhost:5678`), which let an earlier revision of this workflow be **really
imported** (`Successfully imported 1 workflow`, confirmed via
`n8n list:workflow`) and **really executed** (`n8n execute --id ... --rawOutput`
-> `status: success`). The Compare Datasets node routed the demo data correctly,
live:

```
In A only (added) => ['SKU-3']
Same              => ['SKU-1']
Different         => ['SKU-2']
In B only (removed) => ['SKU-4']
```

Shortly after, the Docker overlay (on D:) began throwing I/O errors
(`openat etc/passwd: input/output error`) and the daemon went down - the same
recurring flakiness - so the current `workflow.json` (which differs only by
replacing one reconciliation node with four trivial per-branch pass-through
`Code` nodes; the Compare Datasets node, its config, and its four-output wiring
are identical) was **not re-imported after the crash**. Per the documented
lesson, Docker was not hammered once the drive started flapping.

To import + run it yourself once the container is up:

```bash
docker cp workflow.json n8n:/tmp/puzzle56.json
docker exec n8n n8n import:workflow --input=/tmp/puzzle56.json
# CLI execute starts its own task broker; move it off the busy 5679:
docker exec -e N8N_RUNNERS_BROKER_PORT=5699 n8n \
  n8n execute --id=puzzle56comparesync --rawOutput
```

---

## Standalone substitute (`sync.py`) - fully verified live

Two real SQLite databases, the same compare-and-sync, with a post-sync equality
check:

```bash
python sync.py --reset   # build drifted demo dbs, then sync
python sync.py           # run again: proves idempotency (0 changes)
```

Verified output (real run):

```
RUN 1 (drifted):
  In A only (added)   -> ['SKU-3']
  In B only (removed) -> ['SKU-4']
  Different (changed) -> ['SKU-2']
  Same (unchanged)    -> ['SKU-1']
  applied: INSERT=1  UPDATE=1  DELETE=1  NOOP=1
  target == source after sync: True

RUN 2 (already synced):
  all 3 rows Same; INSERT=0 UPDATE=0 DELETE=0 NOOP=3
  target == source after sync: True
```

An independent `sqlite3` query confirms `source.db` and `target.db` hold the
identical three rows after sync. These buckets match the live n8n node's output
exactly, cross-validating the two implementations.

---

## Files

| File            | What it is                                                        |
|-----------------|-------------------------------------------------------------------|
| `workflow.json` | the n8n workflow (Compare Datasets v2.3, 4 outputs -> 4 actions)  |
| `sync.py`       | standalone two-SQLite-database compare-and-sync, with verify      |
| `.gitignore`    | excludes generated `*.db` demo files                              |

No secrets are committed; the demo needs no credentials.

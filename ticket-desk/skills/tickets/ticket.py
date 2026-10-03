#!/usr/bin/env python3
"""ticket.py - tiny local ticket store for the desk (SQLite, stdlib only).
Runs as an OpenClaw skill: agents call it through OpenClaw's exec tool.

Two loops:
  versions  the requester iterates: v1 -> "make it bluer" -> v2 -> "back to v1 but bigger" -> v3 ...
            (revise; unlimited unless TICKET_MAX_VERSIONS is set)
  attempts  inside one version the reviewer can send work back up to TICKET_MAX_ATTEMPTS times (default 3)

Lifecycle:  new -> in_progress -> review -> resolved -> closed
                       ^-- reject (attempt+1) --'        |
                       ^-- revise (version+1, attempt=1) -'   (also from failed)
  create   desk files a ticket from an incoming message and assigns a worker
  start    worker picks it up
  note     anyone adds a progress note
  submit   worker hands in work for review (result + artifact path); recorded as vN attempt M
  accept   reviewer approves -> resolved
  reject   reviewer sends it back with a reason -> in_progress, attempt+1 (fails past the limit)
  resolve  worker finishes directly (no review needed, e.g. text answers)
  close    desk confirms the result was delivered back to the requester
  revise   requester wants changes -> new version (--change "...", optional --from-version N)
           ('reopen' is an alias)
  fail     anyone marks it failed with a reason
Read:      show <id> | history <id> | list [--status S] [--channel C] [--requester R] [--md] | stats

DB: $TICKET_DB (default ~/.openclaw/tickets.db). Every command prints JSON except --md / history.
"""
import argparse, json, os, sqlite3, sys
from datetime import datetime, timezone

DB = os.path.expanduser(os.environ.get("TICKET_DB", "~/.openclaw/tickets.db"))
FLOW = {"start": ({"new"}, "in_progress"),
        "submit": ({"new", "in_progress"}, "review"),
        "accept": ({"review"}, "resolved"),
        "reject": ({"review"}, "in_progress"),
        "resolve": ({"new", "in_progress"}, "resolved"),
        "close": ({"resolved"}, "closed"),
        "revise": ({"resolved", "closed", "failed"}, "in_progress"),
        "fail": ({"new", "in_progress", "review", "resolved"}, "failed")}
MAX_ATTEMPTS = int(os.environ.get("TICKET_MAX_ATTEMPTS", "3"))
MAX_VERSIONS = int(os.environ.get("TICKET_MAX_VERSIONS", "0"))  # 0 = unlimited


def now():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def db():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.executescript("""
    CREATE TABLE IF NOT EXISTS tickets(
      id TEXT PRIMARY KEY, status TEXT, category TEXT, priority TEXT, assignee TEXT,
      source TEXT, channel TEXT, requester TEXT, summary TEXT, request TEXT,
      result TEXT, artifact TEXT, reason TEXT, attempt INTEGER DEFAULT 1, review TEXT,
      version INTEGER DEFAULT 1, base_version INTEGER, changes TEXT DEFAULT '[]',
      created_at TEXT, started_at TEXT, resolved_at TEXT, closed_at TEXT);
    CREATE TABLE IF NOT EXISTS events(ticket TEXT, at TEXT, actor TEXT, kind TEXT, text TEXT);
    CREATE TABLE IF NOT EXISTS versions(ticket TEXT, version INTEGER, attempt INTEGER, prompt TEXT,
      artifact TEXT, verdict TEXT, notes TEXT, at TEXT);""")
    cols = {r[1] for r in c.execute("PRAGMA table_info(tickets)")}
    for col, typ in (("attempt", "INTEGER DEFAULT 1"), ("review", "TEXT"), ("version", "INTEGER DEFAULT 1"),
                     ("base_version", "INTEGER"), ("changes", "TEXT DEFAULT '[]'")):
        if col not in cols:
            c.execute(f"ALTER TABLE tickets ADD COLUMN {col} {typ}")
    return c


def versions(c, tid):
    return [dict(v) for v in c.execute(
        "SELECT version,attempt,verdict,notes,prompt,artifact,at FROM versions WHERE ticket=? ORDER BY rowid", (tid,))]


def best_of(vs, version):
    """The image that represents a version: its accepted attempt, else its latest submission."""
    rows = [v for v in vs if v["version"] == version]
    acc = [v for v in rows if v["verdict"] == "accepted"]
    return (acc or rows or [None])[-1]


def row(c, tid):
    r = c.execute("SELECT * FROM tickets WHERE id=?", (tid,)).fetchone()
    if not r:
        die(f"no ticket {tid}")
    t = dict(r)
    t["changes"] = json.loads(t.get("changes") or "[]")
    t["versions"] = versions(c, tid)
    b = best_of(t["versions"], t["base_version"]) if t.get("base_version") else None
    t["base"] = {"version": t["base_version"], "prompt": b["prompt"], "artifact": b["artifact"]} if b else None
    t["events"] = [dict(e) for e in c.execute("SELECT at,actor,kind,text FROM events WHERE ticket=? ORDER BY rowid", (tid,))]
    return t


def die(msg):
    print(json.dumps({"ok": False, "error": msg}))
    sys.exit(1)


def out(obj):
    print(json.dumps({"ok": True, **obj}, ensure_ascii=False, indent=1))


def log(c, tid, actor, kind, text=""):
    c.execute("INSERT INTO events VALUES(?,?,?,?,?)", (tid, now(), actor or "", kind, text or ""))


def new_id(c):
    day = datetime.now().strftime("%Y%m%d")
    n = c.execute("SELECT COUNT(*) FROM tickets WHERE id LIKE ?", (f"T-{day}-%",)).fetchone()[0] + 1
    return f"T-{day}-{n:03d}"


def minutes(a, b):
    if not a or not b:
        return None
    return round((datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() / 60, 1)


def set_last_verdict(c, tid, verdict, notes):
    c.execute("UPDATE versions SET verdict=?, notes=? WHERE rowid=(SELECT MAX(rowid) FROM versions WHERE ticket=?)",
              (verdict, notes, tid))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    s = p.add_subparsers(dest="cmd", required=True)
    s.add_parser("init")
    a = s.add_parser("create")
    a.add_argument("--summary", required=True); a.add_argument("--request", required=True)
    a.add_argument("--assignee", required=True); a.add_argument("--category", default="general")
    a.add_argument("--priority", default="normal", choices=["low", "normal", "high", "urgent"])
    a.add_argument("--source", default="discord"); a.add_argument("--channel", default="")
    a.add_argument("--requester", default="")
    for name in ("start", "note", "submit", "accept", "reject", "resolve", "close", "revise", "reopen", "fail"):
        x = s.add_parser(name); x.add_argument("id"); x.add_argument("--agent", default="")
        if name == "note": x.add_argument("--text", required=True)
        if name in ("resolve", "submit"): x.add_argument("--result", required=True); x.add_argument("--artifact", default="")
        if name in ("fail", "reject"): x.add_argument("--reason", required=True)
        if name in ("revise", "reopen"):
            x.add_argument("--change", "--reason", dest="change", required=True)
            x.add_argument("--from-version", dest="from_version", type=int, default=0)
        if name == "accept": x.add_argument("--notes", default="")
    x = s.add_parser("show"); x.add_argument("id")
    x = s.add_parser("history"); x.add_argument("id")
    x = s.add_parser("list"); x.add_argument("--status", default=""); x.add_argument("--md", action="store_true")
    x.add_argument("--channel", default=""); x.add_argument("--requester", default="")
    s.add_parser("stats")
    o = p.parse_args()
    if o.cmd == "reopen":
        o.cmd = "revise"
    c = db()

    if o.cmd == "init":
        out({"db": DB, "max_attempts": MAX_ATTEMPTS, "max_versions": MAX_VERSIONS or "unlimited"})
    elif o.cmd == "create":
        tid = new_id(c)
        c.execute("INSERT INTO tickets(id,status,category,priority,assignee,source,channel,requester,summary,request,"
                  "attempt,version,changes,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,1,1,'[]',?)",
                  (tid, "new", o.category, o.priority, o.assignee, o.source, o.channel, o.requester, o.summary, o.request, now()))
        log(c, tid, "desk", "created", f"assigned to {o.assignee}")
        c.commit(); out({"ticket": row(c, tid)})
    elif o.cmd in FLOW or o.cmd == "note":
        t = row(c, o.id)
        v, att = t["version"] or 1, t["attempt"] or 1
        text = ""
        if o.cmd == "note":
            log(c, o.id, o.agent, "note", o.text)
        else:
            allowed, to = FLOW[o.cmd]
            if t["status"] not in allowed:
                die(f"{o.id} is '{t['status']}', cannot {o.cmd} (allowed from: {sorted(allowed)})")
            sets = {"status": to}
            if o.cmd == "start": sets.update(started_at=now(), assignee=o.agent or t["assignee"])
            if o.cmd in ("resolve", "submit"):
                sets.update(result=o.result, artifact=o.artifact); text = f"v{v} try {att}: {o.result}"
            if o.cmd == "submit":
                c.execute("INSERT INTO versions VALUES(?,?,?,?,?,?,?,?)", (o.id, v, att, o.result, o.artifact, "pending", "", now()))
            if o.cmd == "resolve": sets.update(resolved_at=now())
            if o.cmd == "accept":
                sets.update(resolved_at=now(), review="accepted: " + o.notes)
                set_last_verdict(c, o.id, "accepted", o.notes); text = f"v{v} try {att}: {o.notes}"
            if o.cmd == "reject":
                set_last_verdict(c, o.id, "rejected", o.reason); text = f"v{v} try {att}: {o.reason}"
                sets.update(attempt=att + 1, review="rejected: " + o.reason)
                if att + 1 > MAX_ATTEMPTS:
                    sets = {"status": "failed", "closed_at": now(),
                            "reason": f"v{v}: reviewer rejected {MAX_ATTEMPTS} attempts; last: {o.reason}"}
            if o.cmd == "revise":
                nv = v + 1
                if MAX_VERSIONS and nv > MAX_VERSIONS:
                    die(f"{o.id} already has {v} versions (TICKET_MAX_VERSIONS={MAX_VERSIONS}); file a new ticket")
                base = o.from_version or v
                if o.from_version and not best_of(t["versions"], base):
                    die(f"{o.id} has no submitted image for v{base}; versions: {sorted({x['version'] for x in t['versions']})}")
                changes = t["changes"] + [{"version": nv, "from": base, "change": o.change}]
                sets.update(version=nv, attempt=1, base_version=base, changes=json.dumps(changes, ensure_ascii=False),
                            review="", reason="", resolved_at=None, closed_at=None)
                text = f"v{nv} from v{base}: {o.change}"
            if o.cmd == "close": sets.update(closed_at=now())
            if o.cmd == "fail": sets.update(reason=o.reason, closed_at=now()); text = o.reason
            c.execute(f"UPDATE tickets SET {', '.join(k + '=?' for k in sets)} WHERE id=?", (*sets.values(), o.id))
            log(c, o.id, o.agent, o.cmd, text)
        c.commit(); out({"ticket": row(c, o.id)})
    elif o.cmd == "show":
        out({"ticket": row(c, o.id)})
    elif o.cmd == "history":
        t = row(c, o.id)
        print(f"**{t['id']}** - {t['summary']} - now v{t['version']} ({t['status']})\n")
        print("| v | try | verdict | notes | file |\n|---|---|---|---|---|")
        for x in t["versions"]:
            print(f"| v{x['version']} | {x['attempt']} | {x['verdict']} | {(x['notes'] or '')[:60]} | {x['artifact']} |")
        if t["changes"]:
            print("\nChanges requested:")
        for ch in t["changes"]:
            print(f"- v{ch['version']} (from v{ch['from']}): {ch['change']}")
    elif o.cmd == "list":
        q, where, args = "SELECT id,status,version,attempt,priority,assignee,summary,channel,requester,created_at FROM tickets", [], []
        for col in ("status", "channel", "requester"):
            if getattr(o, col): where.append(f"{col}=?"); args.append(getattr(o, col))
        if where: q += " WHERE " + " AND ".join(where)
        rows = [dict(r) for r in c.execute(q + " ORDER BY created_at DESC LIMIT 50", args)]
        if o.md:
            print("| id | status | ver | try | agent | summary |\n|---|---|---|---|---|---|")
            for r in rows:
                print(f"| {r['id']} | {r['status']} | v{r['version']} | {r['attempt']} | {r['assignee']} | {r['summary'][:60]} |")
        else:
            out({"tickets": rows})
    elif o.cmd == "stats":
        rows = [dict(r) for r in c.execute("SELECT * FROM tickets")]
        by_status, by_agent, turn = {}, {}, []
        for r in rows:
            by_status[r["status"]] = by_status.get(r["status"], 0) + 1
            by_agent[r["assignee"]] = by_agent.get(r["assignee"], 0) + 1
            m = minutes(r["created_at"], r["resolved_at"])
            if m is not None: turn.append(m)
        acc = [dict(r) for r in c.execute("SELECT attempt FROM versions WHERE verdict='accepted'")]
        reviewed = c.execute("SELECT COUNT(*) FROM versions WHERE verdict IN ('accepted','rejected')").fetchone()[0]
        rejected = c.execute("SELECT COUNT(*) FROM versions WHERE verdict='rejected'").fetchone()[0]
        out({"total": len(rows), "by_status": by_status, "by_agent": by_agent,
             "avg_minutes_to_resolve": round(sum(turn) / len(turn), 1) if turn else None,
             "images_reviewed": reviewed, "images_rejected": rejected,
             "first_try_acceptance": round(sum(1 for x in acc if x["attempt"] == 1) / len(acc), 2) if acc else None,
             "avg_attempts_per_accepted_version": round(sum(x["attempt"] for x in acc) / len(acc), 2) if acc else None,
             "avg_versions_per_ticket": round(sum((r["version"] or 1) for r in rows) / len(rows), 2) if rows else None,
             "resolved_or_closed": by_status.get("resolved", 0) + by_status.get("closed", 0)})


if __name__ == "__main__":
    main()

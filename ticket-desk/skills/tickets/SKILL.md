---
name: tickets
description: File, update, iterate and return tickets in the local ticket store (create, start, submit, accept, reject, revise, close, fail, show, history, list, stats). Use for every incoming request, every iteration and every hand-off.
---

# Ticket store

All ticket operations go through one script. Run it with the `exec` tool:

`python3 {baseDir}/ticket.py <command> ...`

It always prints JSON. Check that `"ok": true` before you continue.

| Step | Who | Command |
|---|---|---|
| File a new ticket | desk | `python3 {baseDir}/ticket.py create --summary "<one line>" --request "<original message, verbatim>" --assignee <agent id> --category <image\|text> --priority <low\|normal\|high\|urgent> --source <discord\|whatsapp> --channel "<id>" --requester "<name>"` |
| Pick it up | worker | `python3 {baseDir}/ticket.py start <ID> --agent <id>` |
| Progress note | anyone | `python3 {baseDir}/ticket.py note <ID> --agent <id> --text "<what happened>"` |
| Hand in for review | artist | `python3 {baseDir}/ticket.py submit <ID> --agent artist --result "<prompt used>" --artifact /abs/path.png` |
| Approve | reviewer | `python3 {baseDir}/ticket.py accept <ID> --agent reviewer --notes "<one line>"` |
| Send back | reviewer | `python3 {baseDir}/ticket.py reject <ID> --agent reviewer --reason "<fixes>"` (attempt +1; this version fails after 3 rejects) |
| Finish without review | worker | `python3 {baseDir}/ticket.py resolve <ID> --agent <id> --result "<short result>"` |
| Delivered to requester | desk | `python3 {baseDir}/ticket.py close <ID>` |
| Requester iterates | desk | `python3 {baseDir}/ticket.py revise <ID> --change "<their words>" [--from-version N]` (new version, resets attempts; JSON `base` = prompt + image to build from) |
| Could not be done | anyone | `python3 {baseDir}/ticket.py fail <ID> --agent <id> --reason "<why>"` |
| Look up | anyone | `show <ID>` (JSON incl. versions, changes, base) · `history <ID>` (markdown table of every version) |
| Board / metrics | desk | `list --md [--channel "<id>"]` · `stats` |

## Rules

- Allowed transitions: `new → in_progress → review → resolved → closed`; `reject` goes from review back to in_progress (attempt +1); `revise` goes from resolved, closed or failed to in_progress (version +1, attempt reset to 1); `fail` works from any open state. The script rejects anything else; don't work around it.
- Versions are the requester's iterations (unlimited by default). Attempts are the reviewer's retries within one version (max 3).
- Quote values that contain spaces. Keep `--summary` under 80 characters.
- Ticket ids look like `T-YYYYMMDD-NNN`. Always include the id in anything you post.

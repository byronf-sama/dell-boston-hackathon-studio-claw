# Image desk (OpenClaw 2026.7.1, fully local on the GB10)

Three OpenClaw agents. People chat on Discord or WhatsApp (text, or text + a reference image), get images back, and iterate on them in conversation. Every image passes an independent reviewer before anyone sees it.

```
Discord / WhatsApp ─► DESK  new request? → ticket.py create (v1) → "Filed T-… → artist"
                        │  iteration?  → ticket.py revise --change "…" (v2, v3, … ; "back to v2" works)
                        │  writes a spec: must-haves + avoid list (+ reference, or base image + change)
                        ├─► ARTIST   image_generate (ComfyUI) → self-check → ticket.py submit
                        ├─► REVIEWER checks the image against the spec (and, on an iteration, against the base)
                        │      ACCEPT → ticket.py accept
                        │      REJECT → ticket.py reject --reason "fix 1; fix 2"   (attempt +1)
                        │                 └─► desk re-spawns the artist with the feedback
                        │                      (3 rejects on one version → post best attempt, person can keep iterating)
                        └─► posts "T-… v2" + image → ticket.py close → "Reply with changes to iterate"
"history" → every version with its verdict · "stats" → first-try acceptance, attempts, versions per ticket
```

There are two loops:

- **Versions:** the person iterates as many times as they like ("make it bluer", "go back to v2 but bigger"). Each round is a new version on the same ticket, built from the previous prompt and image so the object stays recognisable. Set `TICKET_MAX_VERSIONS` to cap it.
- **Attempts:** inside one version, the reviewer can send work back up to 3 times (`TICKET_MAX_ATTEMPTS`). That cap resets on every new version.

## What OpenClaw does here (the required stack)

All of it runs inside one `openclaw gateway` process:

| OpenClaw feature | Used for |
|---|---|
| **Channels** (`channels.discord`, WhatsApp plugin) | Receiving messages and attachments, and posting images back |
| **Multi-agent** (`agents.list`, per-agent workspace `AGENTS.md`, tool allow/deny) | The desk, artist and reviewer, each with only the tools it needs |
| **Sub-agents** (`sessions_spawn` / `sessions_yield`) | The desk orchestrating artist → reviewer → retry |
| **Sessions** (one per channel) | Remembering the conversation, so "make it bluer" knows what "it" is |
| **Skills** (`~/.openclaw/skills/tickets`) + `exec` | The ticket store the agents operate |
| **Image generation provider** (`plugins.entries.comfy`, `image_generate`) | Local ComfyUI on the GB10 |
| **Model provider** (`models.providers.vllm`) | Local Qwen3.6 on vLLM for reasoning and vision (the `image` tool) |

| Agent | Job | Tools |
|---|---|---|
| `desk` (default) | Talks to people, owns tickets, orchestrates. Never draws or judges. | `read`, `exec`, `image`, `message`, `sessions_spawn`, `sessions_yield` |
| `artist` | Turns a spec into an image via ComfyUI | `read`, `exec`, `image`, `image_generate` |
| `reviewer` | Independent ACCEPT/REJECT against the spec | `read`, `exec`, `image` |

The minimum viable version is desk + artist. The reviewer is the quality loop and the demo story.

All LLM calls go to vLLM on `127.0.0.1:8000` (Qwen3.6-35B NVFP4, which also handles vision). Images come from ComfyUI on `127.0.0.1:8188`. No cloud models; Discord/WhatsApp are just the transport.

## Install (on the GB10, about 5 min)

1. **Bring up the local model and ComfyUI.**
   - `bash ~/kit/restore.sh vllm`
   - Start ComfyUI too, and check that `curl localhost:8188/system_stats` answers.
2. **Install OpenClaw:** `npm i -g openclaw@2026.7.1`.
3. **Add your Discord bot token.** Put `DISCORD_BOT_TOKEN=...` in `~/.openclaw/.env`.
   - Turn on the bot's **Message Content Intent**.
   - Invite it with the `bot` + `applications.commands` scopes.
4. **Run setup:** `GUILD_ID=<server id> bash setup.sh`. It installs the skill and the 3 workspaces, initialises the DB, and applies the config.
5. **Start the gateway:** `set -a; . ~/.openclaw/.env; set +a; openclaw gateway`.
6. **Test:**
   - "make a cozy mushroom lantern, pink cap, warm glow"
   - Then iterate: "make the cap blue", then "bigger glow", then "go back to v1 but make it blue".
   - Then "history", "status" and "stats".
   - Then attach a reference image and ask for something in that style (a new ticket).

## Files

| File | What it is |
|---|---|
| `openclaw.patch.json5` | Config template: vLLM provider, ComfyUI image provider (`workflows/sdxl_api.json`, prompt node 6, output node 9), the 3 agents, Discord |
| `workspaces/{desk,artist,reviewer}/AGENTS.md` | Each agent's instructions. Tune the spec format in desk, the prompt recipe in artist, and the checklist in reviewer. |
| `skills/tickets/ticket.py` | SQLite ticket store: `create/start/note/submit/accept/reject/resolve/close/revise/fail/show/history/list/stats`. `TICKET_MAX_ATTEMPTS` (default 3) sets the reviewer retries per version; `TICKET_MAX_VERSIONS` (default unlimited) caps iterations. |
| `skills/tickets/SKILL.md` | Teaches the agents the commands |

## Tuning

- **Stricter or looser reviewer.** Edit the checklist in `workspaces/reviewer/AGENTS.md`.
- **Change the retry limit.** Add `TICKET_MAX_ATTEMPTS=2` to `~/.openclaw/.env`.
- **Switch to Z-Image.** In the patch, set `workflowPath` to `zit_api.json` and `promptNodeId` to `"27"`, then re-run setup.
- **Iterations drifting too much?**
  - Fix the KSampler seed in the workflow JSON (`"seed": 12345`) so the same prompt plus a small change gives a similar image.
  - Or add the img2img workflow below, fed with the base image.
- **Reference images.** By default the reference is *described* and its traits are carried into the prompt. True img2img (stretch goal) needs a second ComfyUI workflow: LoadImage → VAEEncode → KSampler with denoise ≈ 0.6.

## WhatsApp (optional; needs a phone you can link)

```bash
openclaw plugins install clawhub:@openclaw/whatsapp
openclaw config set channels.whatsapp.dmPolicy pairing
openclaw channels login --channel whatsapp     # scan the QR from the phone (WhatsApp > Linked devices)
openclaw pairing list whatsapp && openclaw pairing approve whatsapp <CODE>
```

Messages go to the default agent (desk); it files those tickets with `--source whatsapp`.

## Debugging

| Symptom | Check |
|---|---|
| No reply | `openclaw gateway` log; `openclaw agents list --bindings`; bot in the server with Message Content Intent on? |
| Model errors | `curl localhost:8000/v1/models`; `openclaw models list --provider vllm` |
| Tool calls come back as text, or with empty arguments | Restart vLLM with `VLLM_TOOL_PARSER=qwen3_xml bash ~/kit/restore.sh vllm` |
| `image_generate` fails | Is ComfyUI up? Does `workflowPath` exist? Are the node ids right? (`jq 'keys' sdxl_api.json`) |
| Spawn refused | `agentId` must be in desk's `subagents.allowAgents` |
| Loop never ends | `ticket.py history <ID>` (every attempt and verdict); 3 rejects on a version force `failed` |
| "make it bluer" opened a new ticket | The desk missed the iteration: tighten the cue list in `workspaces/desk/AGENTS.md`, or have people reply to the image message |
| See tool calls in chat | Send `/verbose on` in the channel |

Config keys come from the OpenClaw 2026.7.1 docs on the kit (`docs/openclaw.tar.zst`). They haven't been run against a live gateway yet. If a key is rejected, `openclaw config patch --dry-run` names it.

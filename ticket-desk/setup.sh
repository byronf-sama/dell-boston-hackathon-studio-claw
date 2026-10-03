#!/usr/bin/env bash
# setup.sh - install the desk/artist/reviewer agents into OpenClaw on this machine (the GB10).
#   GUILD_ID=<discord server id> bash setup.sh
# Prereqs: vLLM running (bash ~/kit/restore.sh vllm), openclaw 2026.7.1 installed,
#          DISCORD_BOT_TOKEN in ~/.openclaw/.env (you add it; this script never asks for it).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
OC="$HOME/.openclaw"; KIT="${KIT:-$HOME/kit}"
: "${GUILD_ID:?set GUILD_ID=<your Discord server id> (Discord: Developer Mode on, right-click server, Copy Server ID)}"
command -v openclaw >/dev/null || { echo "openclaw not found: npm i -g openclaw@2026.7.1"; exit 1; }
curl -sf http://127.0.0.1:8000/v1/models >/dev/null || echo "WARN: vLLM not answering on :8000 yet (bash ~/kit/restore.sh vllm)"

mkdir -p "$OC/skills" "$HOME/desk-out"
cp -r "$HERE/skills/tickets" "$OC/skills/"
for a in desk artist reviewer; do
  mkdir -p "$OC/workspace-$a"; cp "$HERE/workspaces/$a/AGENTS.md" "$OC/workspace-$a/AGENTS.md"
done
python3 "$OC/skills/tickets/ticket.py" init

touch "$OC/.env"
grep -q '^VLLM_API_KEY=' "$OC/.env" || echo 'VLLM_API_KEY=vllm-local' >> "$OC/.env"
grep -q '^DISCORD_BOT_TOKEN=' "$OC/.env" || echo "NOTE: add DISCORD_BOT_TOKEN=... to $OC/.env (Message Content Intent must be ON for the bot)"

sed -e "s|__HOME__|$HOME|g" -e "s|__KIT__|$KIT|g" -e "s|__GUILD_ID__|$GUILD_ID|g" \
  "$HERE/openclaw.patch.json5" > "$HERE/openclaw.patch.generated.json5"
openclaw config patch --file "$HERE/openclaw.patch.generated.json5" --dry-run
openclaw config patch --file "$HERE/openclaw.patch.generated.json5"
openclaw skills list 2>/dev/null | grep -i tickets || echo "WARN: tickets skill not listed - check ~/.openclaw/skills/tickets/SKILL.md"
openclaw agents list --bindings 2>/dev/null || true

cat <<EOF

Installed. Next:
  1. ComfyUI up (required: the artist generates through it):  bash ~/kit/restore.sh comfy  then start it on :8188
  2. Start the gateway:   set -a; . $OC/.env; set +a; openclaw gateway
  3. In Discord, post:    "make a cozy mushroom lantern, pink cap, warm glow"  (or attach a reference image)
  4. Watch:               python3 $OC/skills/tickets/ticket.py list --md   |   ... stats
EOF

#!/usr/bin/env python3
"""
god_recon_bot — Telegram bot for on-demand bug bounty scope lookup.

Trigger: /target <name>   (or just <name>)
Sources: arkadiyt/bounty-targets-data (H1, Bugcrowd, YesWeHack)
Hosting: GitHub Actions cron every 1 min, long-poll via getUpdates with persisted offset.
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

BOT_TOKEN = os.environ["BOT_TOKEN"]
ALLOWED_CHAT_ID = int(os.environ.get("ALLOWED_CHAT_ID", "8215972072"))
API = f"https://api.telegram.org/bot{BOT_TOKEN}"
STATE = Path(__file__).parent / "state.json"
TG_LIMIT = 4000  # leave headroom under 4096

DATA_URLS = {
    "HackerOne":  "https://raw.githubusercontent.com/arkadiyt/bounty-targets-data/main/data/hackerone_data.json",
    "Bugcrowd":   "https://raw.githubusercontent.com/arkadiyt/bounty-targets-data/main/data/bugcrowd_data.json",
    "YesWeHack":  "https://raw.githubusercontent.com/arkadiyt/bounty-targets-data/main/data/yeswehack_data.json",
}

def http_get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "god-recon-bot/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

def tg(method, **params):
    data = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None}).encode()
    req = urllib.request.Request(f"{API}/{method}", data=data)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"tg error {method}: {e}", file=sys.stderr)
        return None

def send(chat_id, text):
    # chunk to TG_LIMIT
    while text:
        chunk, text = text[:TG_LIMIT], text[TG_LIMIT:]
        tg("sendMessage", chat_id=chat_id, text=chunk, disable_web_page_preview="true")

def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {"offset": 0}

def save_state(s):
    STATE.write_text(json.dumps(s, indent=2))

# ---------- platform parsers ----------
def fetch_all():
    out = {}
    for plat, url in DATA_URLS.items():
        try:
            out[plat] = json.loads(http_get(url))
        except Exception as e:
            print(f"fetch {plat} failed: {e}", file=sys.stderr)
            out[plat] = []
    return out

def search(data, query):
    q = query.lower().strip()
    hits = []
    for plat, programs in data.items():
        for p in programs:
            name = (p.get("name") or "").lower()
            handle = (p.get("handle") or p.get("slug") or "").lower()
            url = (p.get("url") or "").lower()
            if q == handle or q == name or q in handle or q in name or q in url:
                hits.append((plat, p, _rank(q, handle, name)))
    hits.sort(key=lambda x: x[2])
    return [(plat, p) for plat, p, _ in hits]

def _rank(q, handle, name):
    if q == handle: return 0
    if q == name: return 1
    if handle.startswith(q): return 2
    if name.startswith(q): return 3
    return 4

def fmt_program(plat, p):
    name = p.get("name") or p.get("handle") or "?"
    handle = p.get("handle") or p.get("slug") or ""
    url = p.get("url") or ""
    offers_bounty = p.get("offers_bounties") or p.get("offers_swag")
    bounty = "Bounty" if p.get("offers_bounties") else ("VDP/Swag" if not p.get("offers_bounties") else "?")
    in_scope, out_scope = [], []

    # HackerOne format
    if "targets" in p and isinstance(p["targets"], dict):
        for t in p["targets"].get("in_scope", []):
            ident = t.get("asset_identifier") or t.get("asset_type") or ""
            atype = t.get("asset_type") or ""
            elig = " (bounty)" if t.get("eligible_for_bounty") else ""
            in_scope.append(f"[{atype}] {ident}{elig}")
        for t in p["targets"].get("out_of_scope", []):
            ident = t.get("asset_identifier") or ""
            atype = t.get("asset_type") or ""
            out_scope.append(f"[{atype}] {ident}")
    # Bugcrowd format
    elif "target_groups" in p:
        for g in p["target_groups"]:
            label = "in" if g.get("in_scope") else "out"
            for t in g.get("targets", []):
                line = f"[{t.get('category','')}] {t.get('target') or t.get('name','')}"
                (in_scope if label == "in" else out_scope).append(line)
    # YesWeHack format
    elif "scopes" in p:
        for s in p.get("scopes", []):
            line = f"[{s.get('scope_type','')}] {s.get('scope','')}"
            in_scope.append(line)
        for s in p.get("out_of_scopes", []) or []:
            out_scope.append(f"[{s.get('scope_type','')}] {s.get('scope','')}")

    lines = [
        f"🎯 {name}",
        f"Platform: {plat}",
        f"Handle: {handle}",
        f"Type: {bounty}",
        f"URL: {url}",
        f"In-scope: {len(in_scope)} | Out-of-scope: {len(out_scope)}",
        "",
        "IN-SCOPE:",
    ]
    lines += [f"- {x}" for x in in_scope] or ["(none listed)"]
    lines += ["", "OUT-OF-SCOPE:"]
    lines += [f"- {x}" for x in out_scope] or ["(none listed)"]
    return "\n".join(lines)

# ---------- main loop ----------
def handle_update(upd, data_cache):
    msg = upd.get("message") or upd.get("edited_message")
    if not msg: return
    chat = msg.get("chat", {})
    chat_id = chat.get("id")
    if chat_id != ALLOWED_CHAT_ID:
        print(f"reject chat_id={chat_id}", file=sys.stderr)
        return
    text = (msg.get("text") or "").strip()
    if not text: return

    if text in ("/start", "/help"):
        send(chat_id,
             "god_recon_bot\n\n"
             "Usage:\n"
             "  /target <name>   — lookup scope across H1 / Bugcrowd / YesWeHack\n"
             "  <name>           — same, no slash\n\n"
             "Sources: arkadiyt/bounty-targets-data (refreshed hourly)")
        return

    query = text
    if text.startswith("/target"):
        query = text[len("/target"):].strip()
    if not query:
        send(chat_id, "Usage: /target <name>")
        return

    if data_cache[0] is None:
        send(chat_id, f"⏳ fetching scope data for `{query}` ...")
        data_cache[0] = fetch_all()

    hits = search(data_cache[0], query)
    if not hits:
        send(chat_id, f"❌ no match for `{query}` across H1 / Bugcrowd / YesWeHack")
        return

    if len(hits) > 5:
        send(chat_id, f"⚠️ {len(hits)} hits, showing top 5. Be more specific.")
        hits = hits[:5]

    for plat, p in hits:
        send(chat_id, fmt_program(plat, p))

def main():
    state = load_state()
    offset = state.get("offset", 0)
    data_cache = [None]  # lazy fetch on first lookup

    resp = tg("getUpdates", offset=offset, timeout=0, allowed_updates='["message"]')
    if not resp or not resp.get("ok"):
        print(f"getUpdates failed: {resp}", file=sys.stderr)
        return 1

    updates = resp.get("result", [])
    print(f"got {len(updates)} updates")
    for upd in updates:
        try:
            handle_update(upd, data_cache)
        except Exception as e:
            print(f"handle error: {e}", file=sys.stderr)
        offset = max(offset, upd["update_id"] + 1)

    state["offset"] = offset
    save_state(state)
    return 0

if __name__ == "__main__":
    sys.exit(main())

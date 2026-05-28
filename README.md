# god_recon_bot

Telegram bot — on-demand bug bounty scope lookup across HackerOne, Bugcrowd, YesWeHack.

Bot: [@god_recon_bot](https://t.me/god_recon_bot)

## Usage
```
/target uber
/target coupang_tw
uber          # works without slash too
```
Returns: platform, handle, bounty/VDP, full in-scope + out-of-scope list, URL.

Sources: [arkadiyt/bounty-targets-data](https://github.com/arkadiyt/bounty-targets-data) (refreshed hourly upstream).

## Setup
1. Create repo on GitHub, push this folder.
2. Repo Settings → Secrets → Actions, add:
   - `BOT_TOKEN` = your @BotFather token
   - `ALLOWED_CHAT_ID` = your Telegram chat_id (`8215972072`)
3. Enable Actions. Cron runs every 1 min — latency ~1–2 min per command.

## Local test
```
BOT_TOKEN=xxx ALLOWED_CHAT_ID=8215972072 python bot.py
```

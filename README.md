# LinkedIn Daily Auto-Poster

Fully automated pipeline:
`topics.txt` → Claude writes a caption → posts to LinkedIn at the same time every day.

---

## 1. Install

```bash
pip install -r requirements.txt
```

## 2. Configure

```bash
cp .env.example .env
```

Fill in `.env`:

| Variable | Where to get it |
|---|---|
| `ANTHROPIC_API_KEY` | console.anthropic.com → API Keys |
| `LINKEDIN_ACCESS_TOKEN` | Your LinkedIn Developer App, OAuth 2.0 token with `w_member_social` scope (personal) or `w_organization_social` (company page) — you said you already have this |
| `LINKEDIN_AUTHOR_URN` | `urn:li:person:XXXXXXXX` (personal) or `urn:li:organization:XXXXXXXX` (company page) |
| `LINKEDIN_API_VERSION` | Format `YYYYMM`, e.g. `202504`. Bump every few months. |
| `POST_HOUR` / `POST_MINUTE` | 24-hour time to post daily |
| `TIMEZONE` | e.g. `Asia/Kolkata` |

## 3. Add your topics

Edit `topics.txt` — one topic per line. The script rotates through them in order
and loops back to the top when it reaches the end. Edit this file any time;
changes are picked up automatically.

## 4. Test before trusting it

```bash
# Generate a caption WITHOUT posting, just to check quality/tone
python main.py --dry-run

# Generate AND actually publish one post right now
python main.py --now
```

Check `poster.log` and your LinkedIn feed to confirm it worked.

## 5. Run it automated, every day, forever

You need something to run continuously (or on a recurring trigger) since
LinkedIn's API has no built-in "schedule for later" feature — the timing
logic lives entirely in this script.

**Option 0 — GitHub Actions (recommended: free, no server to manage)**

This repo already includes `.github/workflows/daily-post.yml`, which runs
`python main.py --now` on a daily schedule using GitHub's free compute —
you don't need to host anything yourself.

1. Push this repo to GitHub (see main chat for upload steps).
2. In your repo: **Settings → Secrets and variables → Actions → New repository secret**.
   Add these 4 secrets (same values as your `.env` file):
   - `ANTHROPIC_API_KEY`
   - `LINKEDIN_ACCESS_TOKEN`
   - `LINKEDIN_AUTHOR_URN`
   - `LINKEDIN_API_VERSION`
3. In `.github/workflows/daily-post.yml`, adjust the `cron` line to your
   desired posting time — cron times are in **UTC**, so convert from your
   local time (e.g. IST is UTC+5:30 → 9:00 AM IST = `30 3 * * *`).
4. Test it immediately: go to the **Actions** tab → "Daily LinkedIn Post" →
   **Run workflow** button. Check the run log, then check LinkedIn.
5. Once confirmed working, it will run automatically every day at the
   scheduled UTC time — no server, no `.env` file needed on GitHub (secrets
   replace it), nothing left running on your machine.

Note: GitHub disables scheduled workflows automatically after ~60 days
of repo inactivity. If posts stop, open the Actions tab and re-enable it
(one click) — this is a GitHub limitation, not a bug in the script.

**Option A — keep the script running as a background process on your own machine/server**

```bash
nohup python main.py > /dev/null 2>&1 &
```

This starts the internal scheduler, which sleeps and wakes up daily at
`POST_HOUR:POST_MINUTE` to post. Leave the process running (a small VPS,
a Raspberry Pi, or a cloud instance all work).

**Option B — systemd service (recommended for a real server, auto-restarts on crash/reboot)**

Create `/etc/systemd/system/linkedin-poster.service`:

```ini
[Unit]
Description=LinkedIn Daily Auto-Poster
After=network.target

[Service]
Type=simple
WorkingDirectory=/path/to/linkedin_auto_poster
ExecStart=/usr/bin/python3 /path/to/linkedin_auto_poster/main.py
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now linkedin-poster
sudo systemctl status linkedin-poster
```

**Option C — plain cron (no long-running process needed)**

Skip the internal scheduler and just call `--now` once a day via cron:

```
0 9 * * * cd /path/to/linkedin_auto_poster && /usr/bin/python3 main.py --now >> cron.log 2>&1
```

(Set the cron time in your server's local timezone.)

---

## Keeping it running unattended — things that WILL need occasional attention

- **LinkedIn access tokens expire every 60 days.** There is no way around this
  on LinkedIn's side. When you see repeated `401 Unauthorized` errors in
  `poster.log`, go back to your LinkedIn Developer App and re-authorize to
  get a fresh `LINKEDIN_ACCESS_TOKEN`, then update `.env` (or restart the
  systemd service after editing it). If your app requested `offline_access`
  scope, you can implement refresh-token rotation instead — ask me and I'll
  add that.
- **LinkedIn-Version header**: bump `LINKEDIN_API_VERSION` in `.env` every
  few months to a recent `YYYYMM` value.
- **Rate limits**: LinkedIn allows roughly 100 API calls/day/user for posting
  — one post a day is nowhere near that, so this isn't a concern at this
  volume.

## Files

- `main.py` — the automation (caption generation + posting + scheduler)
- `topics.txt` — your rotating topic list
- `state.json` — auto-generated; tracks which topic is next and post history
- `poster.log` — auto-generated; full run log, check this first if something fails
- `.env` — your credentials (never commit this)

## Extending

- **Images**: LinkedIn posts can include images via a two-step upload
  (`/rest/images` register → upload binary → reference URN in the post).
  Ask me and I'll add an `add_image()` step.
- **Multiple accounts / company pages**: duplicate the LinkedIn env vars per
  account and loop over them in `run_daily_post()`.
- **Approval step before posting**: swap `--now` posting for a Slack/email
  notification with the draft caption, and only post after a thumbs-up.

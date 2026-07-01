"""
LinkedIn Daily Auto-Poster
--------------------------
Generates a caption with Claude from a rotating list of topics, then
publishes it to LinkedIn at the same time every day.

Run it once to test:
    python main.py --now

Run it as the always-on scheduler (does the daily posting):
    python main.py

See README.md for setup (LinkedIn app, tokens, cron/systemd options).
"""

import os
import sys
import json
import logging
import argparse
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv
from anthropic import Anthropic
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(BASE_DIR / "poster.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("linkedin_poster")

TOPICS_FILE = BASE_DIR / "topics.txt"
STATE_FILE = BASE_DIR / "state.json"

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
LINKEDIN_ACCESS_TOKEN = os.getenv("LINKEDIN_ACCESS_TOKEN")
LINKEDIN_AUTHOR_URN = os.getenv("LINKEDIN_AUTHOR_URN")
LINKEDIN_API_VERSION = os.getenv("LINKEDIN_API_VERSION", "202504")
POST_HOUR = int(os.getenv("POST_HOUR", "9"))
POST_MINUTE = int(os.getenv("POST_MINUTE", "0"))
TIMEZONE = os.getenv("TIMEZONE", "Asia/Kolkata")

REQUIRED_ENV = {
    "ANTHROPIC_API_KEY": ANTHROPIC_API_KEY,
    "LINKEDIN_ACCESS_TOKEN": LINKEDIN_ACCESS_TOKEN,
    "LINKEDIN_AUTHOR_URN": LINKEDIN_AUTHOR_URN,
}


def check_env():
    missing = [k for k, v in REQUIRED_ENV.items() if not v]
    if missing:
        log.error("Missing required environment variables: %s", ", ".join(missing))
        log.error("Copy .env.example to .env and fill in your credentials.")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Topic rotation (keeps track of which topic is next, across restarts)
# ---------------------------------------------------------------------------

def load_topics():
    if not TOPICS_FILE.exists():
        raise FileNotFoundError(f"Topics file not found: {TOPICS_FILE}")
    lines = TOPICS_FILE.read_text(encoding="utf-8").splitlines()
    topics = [l.strip() for l in lines if l.strip() and not l.strip().startswith("#")]
    if not topics:
        raise ValueError("topics.txt has no usable topics.")
    return topics


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"next_index": 0, "history": []}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def get_next_topic():
    topics = load_topics()
    state = load_state()
    idx = state["next_index"] % len(topics)
    topic = topics[idx]
    state["next_index"] = (idx + 1) % len(topics)
    save_state(state)
    return topic


# ---------------------------------------------------------------------------
# Caption generation (Claude)
# ---------------------------------------------------------------------------

def generate_caption(topic: str) -> str:
    client = Anthropic(api_key=ANTHROPIC_API_KEY)

    prompt = f"""Write a LinkedIn post about: "{topic}"

Requirements:
- Hook in the first line that makes people want to read more
- Short paragraphs (1-3 sentences each), easy to skim on mobile
- Conversational, first-person, professional but not corporate-sounding
- 100-180 words
- End with a light question or call to action to invite comments
- Include 3-5 relevant hashtags on the final line
- Do NOT use markdown formatting (no #, *, ** etc.) since LinkedIn renders plain text
- Output ONLY the post text, nothing else (no preamble, no explanation)"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )
    caption = "".join(
        block.text for block in response.content if block.type == "text"
    ).strip()
    return caption


# ---------------------------------------------------------------------------
# LinkedIn posting (Posts API — /rest/posts)
# ---------------------------------------------------------------------------

def post_to_linkedin(text: str) -> dict:
    url = "https://api.linkedin.com/rest/posts"
    headers = {
        "Authorization": f"Bearer {LINKEDIN_ACCESS_TOKEN}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
        "LinkedIn-Version": LINKEDIN_API_VERSION,
    }
    payload = {
        "author": LINKEDIN_AUTHOR_URN,
        "commentary": text,
        "visibility": "PUBLIC",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": [],
        },
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=30)

    if resp.status_code == 201:
        post_urn = resp.headers.get("x-restli-id", "unknown")
        log.info("Posted successfully. Post URN: %s", post_urn)
        return {"success": True, "post_urn": post_urn}

    log.error("LinkedIn post failed [%s]: %s", resp.status_code, resp.text)
    if resp.status_code == 401:
        log.error(
            "401 Unauthorized -- your LINKEDIN_ACCESS_TOKEN has likely expired "
            "(tokens expire every 60 days). See README.md to refresh it."
        )
    return {"success": False, "status_code": resp.status_code, "body": resp.text}


# ---------------------------------------------------------------------------
# Daily job
# ---------------------------------------------------------------------------

def run_daily_post():
    log.info("=== Starting daily post job ===")
    try:
        topic = get_next_topic()
        log.info("Topic selected: %s", topic)

        caption = generate_caption(topic)
        log.info("Caption generated (%d chars)", len(caption))

        result = post_to_linkedin(caption)

        state = load_state()
        state["history"].append(
            {
                "timestamp": datetime.now().isoformat(),
                "topic": topic,
                "caption": caption,
                "result": result,
            }
        )
        save_state(state)

        if result.get("success"):
            log.info("=== Daily post job completed successfully ===")
        else:
            log.error("=== Daily post job completed WITH ERRORS ===")

    except Exception:
        log.exception("Daily post job crashed")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="LinkedIn daily auto-poster")
    parser.add_argument(
        "--now", action="store_true",
        help="Run one post immediately instead of starting the scheduler",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Generate a caption but do NOT post it to LinkedIn (prints instead)",
    )
    args = parser.parse_args()

    check_env()

    if args.dry_run:
        topic = get_next_topic()
        caption = generate_caption(topic)
        print(f"\n--- TOPIC ---\n{topic}\n\n--- CAPTION ---\n{caption}\n")
        return

    if args.now:
        run_daily_post()
        return

    log.info(
        "Starting scheduler. Will post daily at %02d:%02d (%s).",
        POST_HOUR, POST_MINUTE, TIMEZONE,
    )
    scheduler = BlockingScheduler(timezone=TIMEZONE)
    scheduler.add_job(
        run_daily_post,
        trigger=CronTrigger(hour=POST_HOUR, minute=POST_MINUTE),
        id="daily_linkedin_post",
        misfire_grace_time=3600,  # still run if the machine was asleep, within 1hr
    )
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Scheduler stopped.")


if __name__ == "__main__":
    main()

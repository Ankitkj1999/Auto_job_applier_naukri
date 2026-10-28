import os
import sys
import json
import logging
from browser import get_chrome_driver, ensure_login
from profile_booster import boost_profile, quick_boost_profile
from job_applier import apply_to_naukri_jobs
from job_agent_client import run_job_apply_agent_stage
from external_job_tracker import (
    backfill_external_jobs_from_applied_csv,
    load_external_jobs,
    EXTERNAL_JOBS_MD,
    EXTERNAL_JOBS_CSV,
)

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "naukri_bot.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
    force=True,
)
logger = logging.getLogger("NaukriBot")

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


def load_config() -> dict:
    if not os.path.isfile(CONFIG_PATH):
        raise FileNotFoundError(f"Configuration file not found at: {CONFIG_PATH}")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def print_banner():
    print(r"""
========================================================================
   _  __           __       _     ___       __         ___               ___         
  / |/ /___ _ __ __/ /__ ____(_)   / _ | __ __/ /____    / _ | ___  ___   / (_)__ ____
 /    // _ `// // //  '_// __/ /   / __ |/ // // __/ _ \  / __ |/ _ \/ _ \ / / / -_) __/
/_/|_/ \_,_/ \_,_//_/\_\/_/ /_/   /_/ |_|\_,_/ \__/\___/ /_/ |_/ .__/ .__//_/_/\__/_/   
                                                               /_/  /_/                   
========================================================================
  Auto Job Applier & Daily Profile Booster for Naukri.com
  Configured for: Data Engineer | AWS | PySpark | Delhi NCR
========================================================================
""")


def main():
    print_banner()
    config = load_config()

    # If an argument is provided (e.g. `python main.py boost` or `python main.py apply`)
    arg = sys.argv[1].lower() if len(sys.argv) > 1 else None

    if not arg:
        print("Choose an action:")
        print("  1) Full Profile Booster (Resume sync, headline rotation, notifications, recruiter actions)")
        print("  2) Quick Profile Freshness Boost (Smart headline keyword rotation & Resdex touch ~30s)")
        print("  3) Auto-Apply to Jobs (Search Data Engineer roles & apply)")
        print("  4) Full Automation (Full Booster + Native Neo Agent + Search Auto-Apply)")
        print("  5) External Jobs Tracker (View / Sync Priority External Jobs)")
        print("  6) Generate Insights Dashboard (Build insights.html)")
        print("  7) Run Naukri Native Job Agent (Neo AI Job Agent Auto-Apply)")
        print("  8) Exit")
        choice = input("\nEnter choice [1-8] (default 4): ").strip() or "4"
    else:
        if "quick" in arg or "headline" in arg:
            choice = "2"
        elif "boost" in arg or "refresh" in arg:
            choice = "1"
        elif "agent" in arg or "neo" in arg:
            choice = "7"
        elif "apply" in arg:
            choice = "3"
        elif "tracker" in arg or "external" in arg:
            choice = "5"
        elif "insight" in arg or "dashboard" in arg or "html" in arg:
            choice = "6"
        else:
            choice = "4"

    if choice == "5":
        logger.info("Syncing and updating External Jobs Tracker...")
        backfilled = backfill_external_jobs_from_applied_csv(config)
        jobs = load_external_jobs()
        tier1 = sum(1 for j in jobs if "tier 1" in (j.get("Priority Tier") or "").lower())
        tier2 = sum(1 for j in jobs if "tier 2" in (j.get("Priority Tier") or "").lower())
        tier3 = sum(1 for j in jobs if "tier 3" in (j.get("Priority Tier") or "").lower())
        pending = sum(1 for j in jobs if "pending" in (j.get("Status") or "").lower())
        print("\n" + "=" * 65)
        print("            🌐 EXTERNAL PRIORITY JOBS DASHBOARD            ")
        print("=" * 65)
        print(f"Total External Jobs Tracked: {len(jobs)}")
        print(f"  🌟 Tier 1 (High Priority):   {tier1}")
        print(f"  🔷 Tier 2 (Medium Priority): {tier2}")
        print(f"  ⚪ Tier 3 (Standard):        {tier3}")
        print(f"Pending Applications:        {pending}")
        if backfilled > 0:
            print(f"Newly Indexed from Past Runs: {backfilled}")
        print("-" * 65)
        print(f"📄 Markdown Dashboard: {EXTERNAL_JOBS_MD}")
        print(f"📊 CSV Data File:     {EXTERNAL_JOBS_CSV}")
        print("=" * 65 + "\n")
        return

    if choice == "6":
        logger.info("Building standalone insights dashboard...")
        from insights_generator import generate_insights_html, INSIGHTS_HTML
        path = generate_insights_html()
        print("\n" + "=" * 65)
        print("            📊 NAUKRI BOT INSIGHTS DASHBOARD GENERATED     ")
        print("=" * 65)
        print(f"✓ File created: {path}")
        print("Open this file directly in any browser (Chrome, Firefox, Edge, etc.)")
        print("=" * 65 + "\n")
        return

    if choice == "8":
        print("Exiting.")
        return

    settings = config.get("settings", {})
    profile_dir = settings.get("chrome_profile_dir", "~/.naukri-bot-profile")
    headless = settings.get("headless", False)

    logger.info("Initializing browser with dedicated profile...")
    driver = get_chrome_driver(profile_dir=profile_dir, headless=headless)

    try:
        ensure_login(driver)

        if choice == "1":
            boost_profile(driver, config)
        elif choice == "2":
            quick_boost_profile(driver, config)
        elif choice == "4":
            boost_profile(driver, config)

        if choice == "7":
            # Dedicated run of Naukri Native Job Agent (Neo)
            agent_applied = 0
            try:
                agent_applied = run_job_apply_agent_stage(driver, config)
            except Exception as e:
                logger.warning(f"Native Job Apply Agent encountered an error: {e}")

            if agent_applied > 0:
                logger.info(f"\n★ SUCCESS: Native Neo Agent applied to {agent_applied} recommended jobs!")
            else:
                logger.info(
                    "\n✓ Native Neo Agent stage completed (0 new applications submitted - "
                    "recommendations may already be applied or non-matching)."
                )

        if choice == "4":
            logger.info("\n☕ Candidate break: Browsing homepage naturally before searching jobs (12-20s)...")
            try:
                import random
                import time
                from browser import human_scroll
                driver.get("https://www.naukri.com/mnjuser/homepage")
                time.sleep(random.uniform(5.0, 8.0))
                human_scroll(driver, distance=350, steps=3)
                time.sleep(random.uniform(3.0, 6.0))
                human_scroll(driver, distance=-350, steps=2)
                time.sleep(random.uniform(4.0, 7.0))
            except Exception:
                import time
                time.sleep(10)

            # In Full Automation, first run the native Neo Job Apply Agent
            try:
                run_job_apply_agent_stage(driver, config)
            except Exception as e:
                logger.warning(f"Native Job Apply Agent stage skipped due to: {e}")

        if choice in ["3", "4"]:
            apply_to_naukri_jobs(driver, config)

    except KeyboardInterrupt:
        logger.info("\nExecution interrupted by user.")
    except Exception as e:
        logger.error(f"Error during execution: {e}", exc_info=True)
    finally:
        logger.info("Closing browser session...")
        try:
            driver.quit()
        except Exception:
            pass
        logger.info("Done!")


if __name__ == "__main__":
    main()

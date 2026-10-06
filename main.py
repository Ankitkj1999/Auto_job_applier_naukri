import os
import sys
import json
import logging
from browser import get_chrome_driver, ensure_login
from profile_booster import boost_profile
from job_applier import apply_to_naukri_jobs
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
        print("  1) Boost Profile (Re-upload resume & touch headline for Resdex ranking)")
        print("  2) Auto-Apply to Jobs (Search Data Engineer roles & apply)")
        print("  3) Full Automation (Boost Profile + Auto-Apply)")
        print("  4) External Jobs Tracker (View / Sync Priority External Jobs)")
        print("  5) Generate Insights Dashboard (Build insights.html)")
        print("  6) Exit")
        choice = input("\nEnter choice [1-6] (default 3): ").strip() or "3"
    else:
        if "boost" in arg or "refresh" in arg:
            choice = "1"
        elif "apply" in arg:
            choice = "2"
        elif "tracker" in arg or "external" in arg:
            choice = "4"
        elif "insight" in arg or "dashboard" in arg or "html" in arg:
            choice = "5"
        else:
            choice = "3"

    if choice == "4":
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

    if choice == "5":
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

    if choice == "6":
        print("Exiting.")
        return

    settings = config.get("settings", {})
    profile_dir = settings.get("chrome_profile_dir", "~/.naukri-bot-profile")
    headless = settings.get("headless", False)

    logger.info("Initializing browser with dedicated profile...")
    driver = get_chrome_driver(profile_dir=profile_dir, headless=headless)

    try:
        ensure_login(driver)

        if choice in ["1", "3"]:
            boost_profile(driver, config)

        if choice in ["2", "3"]:
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

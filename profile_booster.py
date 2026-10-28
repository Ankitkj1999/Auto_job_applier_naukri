import os
import re
import json
import time
import random
import logging
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from job_applier import (
    is_title_relevant,
    is_location_match,
    is_experience_suitable,
    find_naukri_apply_button,
    record_applied_job,
    load_applied_job_ids,
)
from chatbot_handler import handle_naukri_chatbot_drawer, check_apply_success, check_apply_error
from external_job_tracker import (
    record_external_job,
    resolve_external_url,
    backfill_external_jobs_from_applied_csv,
)

from datetime import datetime, timedelta
from browser import (
    human_dwell,
    human_scroll,
    human_click,
    human_type_into_element,
)

logger = logging.getLogger("NaukriBot")

INSIGHTS_JSON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "application_insights.json")
BOOSTER_STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "profile_booster_state.json")

from keyword_optimizer import (
    OPTIMIZED_KEYWORD_CLUSTERS,
    evaluate_headline_quality,
    select_best_dynamic_headline,
    save_recruiter_search_keywords,
    load_recruiter_search_keywords,
    OPTIMIZED_PROFILE_SUMMARY,
)

DEFAULT_RESUME_HEADLINES = [c["headline"] for c in OPTIMIZED_KEYWORD_CLUSTERS]


def load_booster_state(state_file: str = BOOSTER_STATE_FILE) -> dict:
    """Loads profile booster history and timestamps from JSON state file."""
    if os.path.isfile(state_file):
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "last_boost_time": None,
        "last_resume_upload_time": None,
        "last_headline_update_time": None,
        "last_profile_summary_update_time": None,
        "current_headline": "",
        "current_profile_summary": "",
        "headline_history": [],
    }


def save_booster_state(state: dict, state_file: str = BOOSTER_STATE_FILE) -> None:
    """Saves profile booster state to JSON file."""
    try:
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        logger.debug(f"Could not save booster state: {e}")


def normalize_headline_for_comparison(text: str) -> str:
    """Strips punctuation, trailing dots, and extra whitespace for fuzzy comparison."""
    if not text:
        return ""
    return re.sub(r"[\s\.\,\;\|\-\/]+", " ", text.lower()).strip()


def select_next_resume_headline(current_headline: str, config: dict) -> str:
    """
    Selects the next diverse, high-impact resume headline from the configured pool.
    Guarantees that the chosen headline is distinctly different from the current headline,
    preventing robotic daily repetition or trivial period-toggling.
    """
    personals = config.get("personals", {})
    configured_headlines = personals.get("resume_headlines")
    single_headline = personals.get("resume_headline", "").strip()

    if configured_headlines and isinstance(configured_headlines, list) and len(configured_headlines) > 0:
        candidates = [h.strip() for h in configured_headlines if h and h.strip()]
    elif single_headline:
        if single_headline not in DEFAULT_RESUME_HEADLINES:
            candidates = [single_headline] + [h for h in DEFAULT_RESUME_HEADLINES if h != single_headline]
        else:
            candidates = DEFAULT_RESUME_HEADLINES
    else:
        candidates = DEFAULT_RESUME_HEADLINES

    if not candidates:
        candidates = DEFAULT_RESUME_HEADLINES

    norm_current = normalize_headline_for_comparison(current_headline)

    # Find candidate that matches current (if any)
    match_idx = -1
    for idx, c in enumerate(candidates):
        if normalize_headline_for_comparison(c) == norm_current:
            match_idx = idx
            break

    if match_idx != -1:
        # Move to next headline in rotation
        next_idx = (match_idx + 1) % len(candidates)
        return candidates[next_idx]

    # If current headline does not match any candidate, pick the first distinct candidate
    for c in candidates:
        if normalize_headline_for_comparison(c) != norm_current:
            return c

    # Fallback if only 1 candidate exists: subtle phrasing variation
    base = candidates[0].rstrip(". ")
    if "with 3+ years" in base:
        return base.replace("with 3+ years", "with 3.5+ years")
    elif "with 3.5+ years" in base:
        return base.replace("with 3.5+ years", "with 3+ years")
    return base



def handle_nvite_application(driver: WebDriver, config: dict = None) -> bool:
    """
    Evaluates and applies to a Job NVite (Recruiter Invitation to Apply)
    when opened from the notification drawer or invite link.
    """
    try:
        current_url = getattr(driver, "current_url", "") or ""
        time.sleep(2)

        # Scrape job title and company if available
        title = "Recruiter Invited Role"
        company = "Unknown Company"
        job_id = ""

        title_elems = driver.find_elements(
            By.XPATH,
            "//h1[contains(@class, 'title') or contains(@class, 'jd-header-title')] | //*[contains(@class, 'styles_jd-header-title')] | //h1"
        )
        if title_elems:
            title = title_elems[0].text.strip()

        comp_elems = driver.find_elements(
            By.XPATH,
            "//div[contains(@class, 'company-name') or contains(@class, 'styles_company-name')] | //*[contains(@class, 'jd-header-comp-name')]//a | //a[contains(@class, 'comp-name')]"
        )
        if comp_elems:
            company = comp_elems[0].text.strip().split("\n")[0]

        id_match = re.search(r'-(\d{10,14})(?:\?|$)', current_url)
        if id_match:
            job_id = id_match.group(1)

        applied_set = load_applied_job_ids()
        if job_id and job_id in applied_set:
            logger.info(f"    [Skip] Already applied to NVite job '{title}' at '{company}' (ID: {job_id}).")
            return False

        apply_btn = find_naukri_apply_button(driver)
        if not apply_btn:
            # Check for alternative invite acceptance buttons
            invite_btns = driver.find_elements(
                By.XPATH,
                "//button[contains(translate(., 'INTERESTED', 'interested'), 'interested')] | "
                "//button[contains(translate(., 'APPLY', 'apply'), 'apply')] | "
                "//button[contains(translate(., 'ACCEPT', 'accept'), 'accept')] | "
                "//a[contains(translate(., 'APPLY', 'apply'), 'apply') and contains(@class, 'apply')]"
            )
            visible_btns = [b for b in invite_btns if b.is_displayed()]
            if visible_btns:
                apply_btn = visible_btns[0]

        if not apply_btn:
            logger.info(f"    No apply/accept button found on NVite page ({current_url[:65]}).")
            return False

        btn_text = (apply_btn.text or "").strip().lower()
        if "already applied" in btn_text or btn_text == "applied":
            logger.info(f"    Already applied to NVite: {title} at {company}")
            if job_id:
                applied_set.add(job_id)
            return False

        logger.info(f"    -> Clicking '{apply_btn.text}' on NVite for \"{title}\" at \"{company}\"...")
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", apply_btn)
        time.sleep(0.5)
        driver.execute_script("arguments[0].click();", apply_btn)
        time.sleep(2.5)

        has_err, _ = check_apply_error(driver)
        if has_err:
            logger.warning(f"    Error reported during NVite apply for {title}")
            return False

        applied_success = False
        if check_apply_success(driver, apply_btn=apply_btn):
            logger.info(f"    ✓ 1-Click apply succeeded for NVite: {title}!")
            applied_success = True
        else:
            applied_success = handle_naukri_chatbot_drawer(driver, config or {}, job_title=title, company=company)

        if applied_success:
            record_applied_job(job_id or "nvite", title, company, "NVite", current_url, status="Applied (NVite)")
            if job_id:
                applied_set.add(job_id)
            logger.info(f"  ★ SUCCESS: Applied to Recruiter NVite: \"{title}\" at \"{company}\"!")
            return True

    except Exception as e:
        logger.warning(f"Error handling NVite application: {e}")

    return False


def engage_header_notifications(driver: WebDriver, config: dict = None, max_taps: int = 2) -> int:
    """
    Opens the Naukri Header Notification Bell (/html/body/div[3]/div[2]/div[4]/button/span),
    locates the right-side notification drawer list, iterates through all notification items,
    scans and prioritizes Job NVites (Recruiter Invitations to Apply), auto-applies to them,
    taps on recent notifications to mark them read and signal active engagement,
    and returns cleanly to the homepage.
    Returns the count of notifications processed.
    """
    logger.info("--------------------------------------------------")
    logger.info("  [1/5] Notification Bell & Activity Feed         ")
    logger.info("--------------------------------------------------")
    count = 0
    tapped_count = 0
    try:
        # Ensure header with notification bell is accessible
        if "mnjuser/homepage" not in (getattr(driver, "current_url", "") or ""):
            driver.get("https://www.naukri.com/mnjuser/homepage")
            time.sleep(3.5)

        bell_selectors = [
            "/html/body/div[3]/div[2]/div[4]/button/span",
            "/html/body/div[3]/div[2]/div[4]/button",
            "//button[contains(@class, 'nI-gNb-ncr__icon-wrapper')]",
            "//button[@aria-label='Notifications']",
        ]

        def get_bell_button():
            for sel in bell_selectors:
                elems = driver.find_elements(By.XPATH, sel)
                if elems and elems[0].is_displayed():
                    return elems[0]
            return None

        bell_btn = get_bell_button()
        if not bell_btn:
            logger.info("Notification Bell button not found on header.")
            return 0

        logger.info("✓ Clicking Notification Bell button...")
        driver.execute_script("arguments[0].click();", bell_btn)
        time.sleep(2.5)

        ul_selectors = [
            "/html/body/div[3]/div[2]/div[4]/div/div[2]/div[2]/div[1]/div/div/ul",
            "//div[contains(@class, 'naukri-drawer')]//ul",
            "//div[contains(@class, 'notif')]//ul",
        ]

        def get_notif_items():
            for sel in ul_selectors:
                elems = driver.find_elements(By.XPATH, sel)
                if elems:
                    return elems[0].find_elements(By.XPATH, "./li")
            return []

        items = get_notif_items()
        count = len(items)
        if not items:
            logger.info("Notification drawer list not located.")
        else:
            logger.info(f"Found {count} notifications in drawer. Interacting with notifications...")

            nvite_indices = []
            regular_indices = []

            for idx, it in enumerate(items):
                try:
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center', behavior: 'smooth'});", it)
                    driver.execute_script("""
                        arguments[0].dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
                        arguments[0].dispatchEvent(new MouseEvent('mouseenter', { bubbles: true }));
                        if (arguments[0].focus) { arguments[0].focus(); }
                    """, it)

                    classes = it.get_attribute("class") or ""
                    is_unread = "unread" in classes
                    text_snippet = it.text.replace("\n", " | ").strip()[:80]
                    unread_tag = " [NEW]" if is_unread else ""

                    t_low = text_snippet.lower()
                    is_nvite = any(w in t_low for w in [
                        "invited you", "job nvite", "nvite", "hiring drive",
                        "invitation to apply", "invited to apply", "recruiter invited"
                    ])

                    if is_nvite:
                        nvite_tag = " 🌟 [JOB NVITE]"
                        nvite_indices.append(idx)
                    else:
                        nvite_tag = ""
                        regular_indices.append(idx)

                    logger.info(f"  [{idx+1}/{count}]{unread_tag}{nvite_tag} {text_snippet}")
                    time.sleep(0.3)
                except Exception:
                    continue

            # Prioritize all Job NVites first, then regular notifications up to max_taps
            indices_to_tap = nvite_indices + [i for i in regular_indices if i not in nvite_indices][:max_taps]
            logger.info(f"Processing {len(indices_to_tap)} priority notification(s) ({len(nvite_indices)} Job NVite(s), {min(max_taps, len(regular_indices))} regular)...")

            original_window = getattr(driver, "current_window_handle", "main")

            for tap_order, tap_idx in enumerate(indices_to_tap, 1):
                try:
                    current_items = get_notif_items()
                    if tap_idx >= len(current_items):
                        break
                    target_item = current_items[tap_idx]
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center', behavior: 'smooth'});", target_item)
                    time.sleep(0.5)

                    anchors = target_item.find_elements(By.XPATH, ".//a | .//*[@role='button']")
                    clickable = anchors[0] if anchors else target_item

                    item_title = target_item.text.replace("\n", " | ").strip()[:60]
                    is_nvite_item = tap_idx in nvite_indices

                    if is_nvite_item:
                        logger.info(f"  -> [NVite Action] Opening Recruiter Invitation: \"{item_title}\"...")
                    else:
                        logger.info(f"  -> Tapping notification [{tap_order}/{len(indices_to_tap)}]: \"{item_title}\"...")

                    windows_before = set(getattr(driver, "window_handles", ["main"]))
                    driver.execute_script("arguments[0].click();", clickable)
                    time.sleep(3)
                    tapped_count += 1

                    # Handle new window/tab if opened
                    new_windows = [h for h in getattr(driver, "window_handles", ["main"]) if h not in windows_before]
                    if new_windows and hasattr(driver, "switch_to"):
                        driver.switch_to.window(new_windows[0])
                        time.sleep(2)

                    target_url = getattr(driver, "current_url", "") or ""
                    logger.info(f"     ✓ Viewed notification update ({target_url[:65]})")

                    if is_nvite_item:
                        applied = handle_nvite_application(driver, config=config)
                        if applied:
                            logger.info(f"     ★ Successfully applied to recruiter invite!")

                    # If a new tab was opened, close it and return to original window
                    if new_windows and hasattr(driver, "switch_to"):
                        try:
                            if getattr(driver, "current_window_handle", "") != original_window:
                                driver.close()
                            driver.switch_to.window(original_window)
                            time.sleep(1)
                        except Exception:
                            try:
                                driver.switch_to.window(original_window)
                            except Exception:
                                pass
                    else:
                        # Return to homepage to tap the next
                        driver.get("https://www.naukri.com/mnjuser/homepage")
                        time.sleep(3)

                    if tap_order < len(indices_to_tap):
                        # Re-open bell drawer for the next notification tap
                        btn = get_bell_button()
                        if btn:
                            driver.execute_script("arguments[0].click();", btn)
                            time.sleep(2)
                except Exception as tap_err:
                    logger.warning(f"  Could not process notification {tap_idx+1}: {tap_err}")
                    try:
                        driver.switch_to.window(original_window)
                    except Exception:
                        pass
                    driver.get("https://www.naukri.com/mnjuser/homepage")
                    time.sleep(2.5)

        logger.info(f"✓ Completed notification engagement: reviewed {count} alerts, processed {tapped_count} priority updates.")

    except Exception as e:
        logger.warning(f"Error during header notifications engagement: {e}")

    return count


def hide_and_submit_recommendation_reason(driver: WebDriver, card, reason: str = "Job role") -> bool:
    """
    Clicks 'Hide' on a recommended job card, opens 'Tell Us Why', selects the
    appropriate feedback chip (e.g. 'Job role', 'Experience', 'Location', 'Skills'),
    and submits feedback to tune Naukri's recommendation algorithm.
    """
    try:
        # Step 1: Click Hide
        hide_spans = card.find_elements(By.XPATH, ".//span[normalize-space()='Hide' or contains(text(), 'Hide')]")
        if not hide_spans:
            return False
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", hide_spans[0])
        time.sleep(0.5)
        driver.execute_script("arguments[0].click();", hide_spans[0])
        time.sleep(1.2)

        # Step 2: Click Tell Us Why
        tell_why_btns = card.find_elements(By.XPATH, ".//*[contains(text(), 'Tell Us Why') or contains(text(), 'Tell us why')]")
        if not tell_why_btns:
            tell_why_btns = driver.find_elements(By.XPATH, "//*[contains(text(), 'Tell Us Why') or contains(text(), 'Tell us why')]")
        if not tell_why_btns:
            return True  # Job card is hidden

        driver.execute_script("arguments[0].click();", tell_why_btns[0])
        time.sleep(1)

        # Step 3: Select Reason chip
        reason_map = {
            "title": "Job role",
            "job role": "Job role",
            "experience": "Experience",
            "skills": "Skills",
            "location": "Location",
            "salary": "Salary",
            "company": "Company",
        }
        target_reason = reason_map.get(reason.lower(), "Job role")

        reason_chips = card.find_elements(By.XPATH, f".//span[contains(@class, 'check-item') and contains(text(), '{target_reason}')]")
        if not reason_chips:
            reason_chips = driver.find_elements(By.XPATH, f"//span[contains(@class, 'check-item') and contains(text(), '{target_reason}')]")

        if reason_chips:
            driver.execute_script("arguments[0].click();", reason_chips[0])
            time.sleep(0.5)

        # Step 4: Click Submit
        submit_btns = card.find_elements(By.XPATH, ".//button[contains(@class, 'submit-feedback')] | //button[normalize-space()='Submit']")
        if not submit_btns:
            submit_btns = driver.find_elements(By.XPATH, "//button[contains(@class, 'submit-feedback')] | //button[normalize-space()='Submit']")

        if submit_btns:
            driver.execute_script("arguments[0].click();", submit_btns[0])
            time.sleep(1)
            return True
        return True
    except Exception as e:
        logger.debug(f"Error hiding card with reason '{reason}': {e}")
        return False


def optimize_and_apply_recommended_jobs(
    driver: WebDriver,
    config: dict,
    max_cards_per_tab: int = None,
    applied_in_run: list = None
) -> dict:
    """
    Evaluates jobs under Naukri's 4 Recommended categories:
    1. Top Candidate (Highest Priority)
    2. Preferences
    3. Applies
    4. You might like

    For each job:
    - If relevant: Applies directly via 1-click or questionnaire drawer and logs success.
    - If irrelevant non-data role (e.g. Sales, Frontend, QA): Clicks 'Hide', opens 'Tell Us Why',
      selects 'Job role', and submits feedback to train Naukri's recommendation algorithm.
    - If in Data Engineering domain but not matching experience/location: Skips cleanly WITHOUT hiding
      to prevent poisoning or suppressing the candidate's core Data Engineering recommendations.
    """
    logger.info("--------------------------------------------------")
    logger.info("  [2/6] Recommended Jobs: Apply & Cleanse Suite   ")
    logger.info("--------------------------------------------------")
    summary = {
        "applied": 0,
        "hidden": 0,
        "reasons": {"Job role": 0, "Experience": 0, "Location": 0, "Skills": 0},
    }

    try:
        driver.get("https://www.naukri.com/mnjuser/recommendedjobs")
        time.sleep(4)

        search_cfg = config.get("search", {})
        personals = config.get("personals", {})
        settings = config.get("settings", {})
        skip_external = settings.get("skip_external_company_sites", True)
        pause_sec = settings.get("pause_between_applications_sec", 3)

        if max_cards_per_tab is None:
            max_cards_per_tab = settings.get("max_recommended_cards_per_tab", None)

        candidate_exp = personals.get("total_experience_years", 3.5)
        min_exp = search_cfg.get("min_experience", 1)
        max_exp = search_cfg.get("max_experience", 6)
        max_stretch = search_cfg.get("max_experience_stretch", 1.5)
        bad_words = search_cfg.get("title_bad_words", [])
        mandatory_words = search_cfg.get("title_mandatory_words", [])
        target_locations = search_cfg.get("locations", []) + search_cfg.get("fallback_locations", [])

        applied_set = load_applied_job_ids()
        backfill_external_jobs_from_applied_csv(config)

        tabs_to_process = ["Top Candidate", "Preferences", "Applies", "You might like"]

        for tab_name in tabs_to_process:
            logger.info(f"\n>>> Processing Recommended Tab: \"{tab_name}\" <<<")
            tab_elems = driver.find_elements(
                By.XPATH,
                f"//div[contains(@class, 'tab-wrapper')]//div[contains(text(), '{tab_name}')] | "
                f"//div[contains(@class, 'tab-list-item') and contains(text(), '{tab_name}')] | "
                f"//*[(contains(@class, 'tab') or contains(@class, 'tab-list') or contains(@class, 'chip')) and contains(normalize-space(), '{tab_name}')]"
            )
            if tab_elems:
                driver.execute_script("arguments[0].click();", tab_elems[0])
                time.sleep(2.5)

            # Scroll iteratively to load all lazy-rendered cards in the current tab
            try:
                last_card_count = 0
                for _ in range(6):
                    current_cards = driver.find_elements(By.XPATH, "//article[contains(@class, 'jobTuple')]")
                    count = len(current_cards)
                    if count == last_card_count and count > 0:
                        break
                    if max_cards_per_tab and count >= max_cards_per_tab:
                        break
                    last_card_count = count
                    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                    time.sleep(1.2)
                driver.execute_script("window.scrollTo(0, 0);")
                time.sleep(0.5)
            except Exception:
                pass

            cards = driver.find_elements(By.XPATH, "//article[contains(@class, 'jobTuple')]")
            if not cards:
                logger.info(f"  No cards found under tab '{tab_name}'.")
                continue

            total_to_eval = len(cards) if not max_cards_per_tab else min(len(cards), max_cards_per_tab)
            card_limit_str = f"all {total_to_eval}" if (not max_cards_per_tab or max_cards_per_tab >= len(cards)) else f"{total_to_eval} of {len(cards)}"
            logger.info(f"  Evaluating {card_limit_str} card(s) under '{tab_name}'...")

            for idx in range(total_to_eval):
                try:
                    current_cards = driver.find_elements(By.XPATH, "//article[contains(@class, 'jobTuple')]")
                    if idx >= len(current_cards):
                        break
                    card = current_cards[idx]

                    job_id = card.get_attribute("data-job-id") or ""
                    title_elem = card.find_elements(By.XPATH, ".//*[contains(@class, 'title')]")
                    title = title_elem[0].text.strip() if title_elem else "Unknown Title"

                    # Skip already hidden or undo state
                    card_text = card.text or ""
                    if "has been hidden" in card_text or "Undo" in card_text:
                        continue

                    company_elem = card.find_elements(By.XPATH, ".//*[contains(@class, 'subTitle') or contains(@class, 'company')]")
                    company = company_elem[0].text.strip().split("\n")[0] if company_elem else "Unknown Company"

                    # Extract exp, salary, and loc reliably
                    exp_str = ""
                    sal_str = ""
                    job_loc = ""
                    salary_indicators = ["lakh", "lac", "lacs", "pa", "p.a.", "disclosed", "₹", "cr", "crore", "per annum", "inr"]
                    detail_spans = card.find_elements(By.XPATH, ".//span[contains(@class, 'ellipsis') and contains(@class, 'valignM')]")
                    for s in detail_spans:
                        t = s.text.strip()
                        if not t:
                            continue
                        t_low = t.lower()
                        if any(w in t_low for w in ["yr", "year", "fresher"]) or re.search(r'\b\d+\s*-\s*\d+\s*(?:yrs?|years?)\b', t_low):
                            if not exp_str:
                                exp_str = t
                        elif any(c in t_low for c in salary_indicators) or re.search(r'\b(?:\d+\s*-\s*\d+|\d+)\s*(?:lacs?|lakhs?|cr)\b', t_low):
                            if not sal_str:
                                sal_str = t
                        else:
                            if not job_loc:
                                job_loc = t

                    # Fallback for location if still missing
                    if not job_loc:
                        loc_spans = card.find_elements(By.XPATH, ".//span[contains(@class, 'loc') or contains(@class, 'location')]")
                        for ls in loc_spans:
                            txt = ls.text.strip()
                            if txt and not any(c in txt.lower() for c in salary_indicators) and "yr" not in txt.lower():
                                job_loc = txt
                                break

                    # Check duplicate
                    if job_id and job_id in applied_set:
                        continue

                    # Evaluate filters
                    is_title_ok = is_title_relevant(title, bad_words, mandatory_words)
                    is_exp_ok, _ = is_experience_suitable(exp_str, candidate_exp, min_exp, max_exp, max_stretch) if exp_str else (True, "")
                    is_loc_ok = is_location_match(job_loc, target_locations) if job_loc else True

                    if not is_title_ok:
                        reason = "Job role"
                    elif not is_exp_ok:
                        reason = "Experience"
                    elif not is_loc_ok:
                        reason = "Location"
                    else:
                        reason = None

                    if reason:
                        # Safety check: NEVER hide jobs that belong to candidate's core Data Engineering domain!
                        is_data_domain = any(k in title.lower() for k in [
                            "data", "analytics", "etl", "spark", "pyspark", "databricks",
                            "snowflake", "big data", "dwh", "pipeline", "platform", "fabric",
                            "warehouse", "sql developer", "bi developer", "migration", "integration",
                            "data factory", "adf", "lakehouse", "informatica", "bigquery", "redshift"
                        ])

                        if is_data_domain:
                            # Skip without negative feedback to preserve Naukri's recommendation algorithm
                            logger.info(f"  [Skip - Domain Match] \"{title}\" at \"{company}\" [{exp_str}, {job_loc}] -> Reason: '{reason}' (Skipping without hiding to keep data recommendations intact)")
                            continue

                        max_hides = settings.get("max_hides_per_session", 3)
                        if summary["hidden"] >= max_hides:
                            logger.info(f"  [Skip - Hide Cap] \"{title}\" at \"{company}\" -> Reached session hide limit ({max_hides}). Skipping without further hiding.")
                            continue

                        # Only hide and train algorithm against TRULY irrelevant non-data jobs (QA, Sales, Frontend, Marketing, etc.)
                        logger.info(f"  ✕ [Hide & Feedback] \"{title}\" at \"{company}\" [{exp_str}, {job_loc}] -> Reason: '{reason}'")
                        human_dwell(1.5, 3.0)
                        hide_and_submit_recommendation_reason(driver, card, reason=reason)
                        summary["hidden"] += 1
                        summary["reasons"][reason] = summary["reasons"].get(reason, 0) + 1
                        human_dwell(1.5, 3.0)
                        continue
                    else:
                        # Match: Apply to this recommended job!
                        logger.info(f"  ★ [Recommended Match] \"{title}\" at \"{company}\" ({job_loc}) [{exp_str}]")

                        original_window = driver.current_window_handle
                        windows_before = set(driver.window_handles)
                        href = ""
                        try:
                            href = title_elem[0].get_attribute("href") or ""
                        except Exception:
                            pass

                        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", title_elem[0])
                        time.sleep(0.5)
                        driver.execute_script("arguments[0].click();", title_elem[0])
                        time.sleep(3)

                        new_windows = [h for h in driver.window_handles if h not in windows_before]
                        if not new_windows and href:
                            driver.execute_script("window.open(arguments[0], '_blank');", href)
                            time.sleep(2.5)
                            new_windows = [h for h in driver.window_handles if h not in windows_before]

                        if new_windows:
                            driver.switch_to.window(new_windows[0])
                            try:
                                job_url = driver.current_url
                                apply_btn = find_naukri_apply_button(driver)
                                if not apply_btn:
                                    logger.info("    [Skip] No Apply button found on job page.")
                                else:
                                    btn_text = (apply_btn.text or "").strip().lower()
                                    if "company site" in btn_text:
                                        logger.info(f"    [External] Found external application: '{title}' at '{company}'")
                                        ext_url = resolve_external_url(driver, apply_btn, default_url=job_url)
                                        record_external_job(
                                            config=config,
                                            job_id=job_id,
                                            title=title,
                                            company=company,
                                            location=job_loc,
                                            experience=exp_str or "",
                                            external_url=ext_url,
                                            naukri_url=job_url,
                                            status="Pending",
                                        )
                                        if skip_external:
                                            logger.info("    [Skip] External application recorded to tracker. Skipping.")
                                            record_applied_job(job_id, title, company, job_loc, job_url, status="External Skipped")
                                            applied_set.add(job_id)
                                        else:
                                            logger.info("    [External] Apply on Company Site recorded.")
                                            record_applied_job(job_id, title, company, job_loc, job_url, status="External Link")
                                            applied_set.add(job_id)
                                    elif "already applied" in btn_text or btn_text == "applied":
                                        logger.info("    [Skip] Already applied to this job.")
                                        applied_set.add(job_id)
                                    else:
                                        logger.info(f"    -> Clicking '{apply_btn.text}'...")
                                        driver.execute_script("arguments[0].click();", apply_btn)
                                        time.sleep(2)

                                        has_err, _ = check_apply_error(driver)
                                        if not has_err:
                                            if check_apply_success(driver, apply_btn=apply_btn):
                                                logger.info("    ✓ Instant 1-Click apply succeeded!")
                                                applied_successfully = True
                                            else:
                                                applied_successfully = handle_naukri_chatbot_drawer(driver, config, job_title=title, company=company)

                                            if applied_successfully:
                                                summary["applied"] += 1
                                                applied_set.add(job_id)
                                                record_applied_job(job_id, title, company, job_loc, job_url, status="Applied (Recommended)")
                                                if applied_in_run is not None:
                                                    applied_in_run.append({
                                                        "title": title,
                                                        "company": company,
                                                        "location": job_loc,
                                                        "url": job_url,
                                                    })
                                                logger.info(f"    ★ SUCCESS: Applied to {title} | {company}")
                                                actual_delay = max(5.0, round(random.uniform(pause_sec * 0.9, pause_sec * 1.5), 1))
                                                time.sleep(actual_delay)
                            except Exception as app_err:
                                logger.warning(f"    Error applying to recommended job: {app_err}")
                            finally:
                                try:
                                    if driver.current_window_handle != original_window:
                                        driver.close()
                                    driver.switch_to.window(original_window)
                                    time.sleep(1)
                                except Exception:
                                    try:
                                        driver.switch_to.window(original_window)
                                    except Exception:
                                        pass
                except Exception as card_err:
                    logger.debug(f"Card processing error: {card_err}")

        logger.info(f"\n★ Recommended Jobs Optimization Summary: Applied: {summary['applied']} | Hidden & Feedback Submitted: {summary['hidden']} (Reasons: {summary['reasons']})")

    except Exception as e:
        logger.warning(f"Error during recommended jobs optimization: {e}")

    return summary


def open_recruiter_menu_and_click_link(driver: WebDriver, link_xpath: str, fallback_url: str, link_label: str) -> bool:
    """
    Opens the header Recruiter/Profile Drawer Button (/html/body/div[3]/div[2]/div[5]/button)
    and clicks the specified sub-link (e.g. 2.1 Search Appearances or 2.2 Recruiter Actions),
    clearing the red notification badge on the button. Falls back to direct navigation if needed.
    """
    try:
        btn_selectors = [
            "/html/body/div[3]/div[2]/div[5]/button",
            "//button[contains(@class, 'nI-gNb-drawer__icon')]",
            "//button[@aria-label='Open profile menu']",
        ]
        btn2 = None
        for sel in btn_selectors:
            elems = driver.find_elements(By.XPATH, sel)
            if elems and elems[0].is_displayed():
                btn2 = elems[0]
                break

        if not btn2:
            driver.get("https://www.naukri.com/mnjuser/homepage")
            time.sleep(3.5)
            for sel in btn_selectors:
                elems = driver.find_elements(By.XPATH, sel)
                if elems and elems[0].is_displayed():
                    btn2 = elems[0]
                    break

        if btn2:
            badge_text = ""
            try:
                badges = btn2.find_elements(By.XPATH, ".//span[contains(@class, 'badge')]")
                if badges:
                    badge_text = badges[0].text.strip()
            except Exception:
                pass
            badge_info = f" (Active Badge: {badge_text})" if badge_text else ""
            logger.info(f"Opening Profile & Recruiter Menu Drawer{badge_info}...")
            driver.execute_script("arguments[0].click();", btn2)
            time.sleep(2)

            link_elems = driver.find_elements(By.XPATH, link_xpath)
            if link_elems and link_elems[0].is_displayed():
                logger.info(f"✓ Clicking '{link_label}' from drawer...")
                driver.execute_script("arguments[0].click();", link_elems[0])
                time.sleep(3.5)
                return True
            else:
                logger.info(f"Sub-link for '{link_label}' not directly visible in drawer. Navigating to fallback URL...")
    except Exception as e:
        logger.warning(f"Error opening recruiter menu for '{link_label}': {e}")

    # Fallback to direct URL navigation
    driver.get(fallback_url)
    time.sleep(3.5)
    return False


def engage_performance_and_search_appearances(driver: WebDriver) -> dict:
    """
    Visits https://www.naukri.com/mnjuser/performance (via Button 2 & Link 2.1 if available),
    expands the Search Appearances analysis dropdown, extracts top recruiter keywords/stats,
    and simulates active reading.
    """
    logger.info("--------------------------------------------------")
    logger.info("  [2/5] Performance & Search Appearances Analysis ")
    logger.info("--------------------------------------------------")
    stats = {}
    try:
        xp_2_1 = (
            "/html/body/div[3]/div[2]/div[5]/div/div[2]/div/div[3]/div[2]/div[1]/a | "
            "//a[contains(@href, '/mnjuser/performance') and not(contains(@href, '#'))] | "
            "//a[@aria-label='View all Search Appearances']"
        )
        open_recruiter_menu_and_click_link(
            driver,
            link_xpath=xp_2_1,
            fallback_url="https://www.naukri.com/mnjuser/performance",
            link_label="Search Appearances (2.1)"
        )

        # Expand Search Appearances dropdown
        dropdown_selectors = [
            "/html/body/div[1]/div[5]/div/div/div[2]/div[1]/div[2]/div/div/div[1]/div[2]/i",
            "//div[contains(@class, 'search-appearances')]//i[contains(@class, 'DownArrow') or contains(@class, 'arrow') or contains(@class, 'icon')]",
            "//i[contains(@class, 'naukicon-DownArrow')]",
        ]
        for sel in dropdown_selectors:
            elems = driver.find_elements(By.XPATH, sel)
            if elems and elems[0].is_displayed():
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", elems[0])
                time.sleep(0.5)
                driver.execute_script("arguments[0].click();", elems[0])
                logger.info("✓ Expanded Search Appearances breakdown.")
                break

        time.sleep(2)

        # Scrape overview cards
        summary_cards = driver.find_elements(
            By.XPATH,
            "//div[contains(@class, 'summary-card') or contains(@class, 'search-appearances-card')]"
        )
        for sc in summary_cards:
            text = sc.text.replace("\n", " | ").strip()
            if text:
                logger.info(f"  [Insight] {text[:140]}")
                stats["summary"] = text

        # Scrape actual recruiter search queries / keywords
        search_terms = []
        try:
            term_elems = driver.find_elements(
                By.XPATH,
                "//div[contains(@class, 'search-appearances')]//li | "
                "//div[contains(@class, 'search-appearances')]//span[contains(@class, 'chip') or contains(@class, 'keyword') or contains(@class, 'tag')] | "
                "//div[contains(@class, 'top-search')]//div | "
                "//div[contains(@class, 'keyword-section')]//span"
            )
            for te in term_elems:
                t_txt = te.text.strip()
                if t_txt and len(t_txt) < 50 and not any(ign in t_txt.lower() for ign in ["search appearances", "view all", "learn more", "close"]):
                    clean_term = re.sub(r'\s*\(\d+\)\s*', '', t_txt).strip()
                    if clean_term and clean_term not in search_terms:
                        search_terms.append(clean_term)

            if search_terms:
                logger.info(f"★ Extracted {len(search_terms)} Recruiter Search Terms: {', '.join(search_terms[:8])}")
                stats["search_terms"] = search_terms

                data = load_recruiter_search_keywords()
                data["last_updated"] = datetime.now().isoformat()
                data["search_terms"] = search_terms
                if "raw_insights" not in data or not isinstance(data["raw_insights"], list):
                    data["raw_insights"] = []
                data["raw_insights"].append({
                    "timestamp": datetime.now().isoformat(),
                    "terms": search_terms,
                    "summary": stats.get("summary", ""),
                })
                data["raw_insights"] = data["raw_insights"][-20:]
                save_recruiter_search_keywords(data)
        except Exception as st_err:
            logger.debug(f"Could not scrape detailed search terms: {st_err}")

        # Spend a couple seconds scrolling to simulate engagement
        driver.execute_script("window.scrollBy({top: 300, behavior: 'smooth'});")
        time.sleep(2.5)

    except Exception as e:
        logger.warning(f"Error during performance engagement: {e}")

    return stats


def engage_recruiter_actions(driver: WebDriver) -> None:
    """
    Navigates to Recruiter Actions section (via Button 2 & Link 2.2 if available),
    and clicks 'Load more' multiple times to review recruiter activity and signal high platform engagement.
    """
    logger.info("--------------------------------------------------")
    logger.info("  [3/5] Recruiter Actions Engagement              ")
    logger.info("--------------------------------------------------")
    try:
        xp_2_2 = (
            "/html/body/div[3]/div[2]/div[5]/div/div[2]/div/div[3]/div[2]/div[2]/a | "
            "//a[contains(@href, '/mnjuser/performance#recruiterActions')] | "
            "//a[@aria-label='View all Recruiter Actions']"
        )
        open_recruiter_menu_and_click_link(
            driver,
            link_xpath=xp_2_2,
            fallback_url="https://www.naukri.com/mnjuser/performance#recruiterActions",
            link_label="Recruiter Actions (2.2)"
        )

        # Smooth scroll down to recruiter actions
        driver.execute_script("window.scrollTo({top: document.body.scrollHeight / 2, behavior: 'smooth'});")
        time.sleep(2)

        load_more_selectors = [
            "/html/body/div[1]/div[5]/div/div/div[2]/div[1]/div[5]/div/div/div[2]/div[3]/div/span",
            "//span[contains(@class, 'load-more-button')]",
            "//*[contains(translate(text(), 'LOAD MORE', 'load more'), 'load more')]",
        ]

        clicks = 0
        for _ in range(2):
            for sel in load_more_selectors:
                elems = driver.find_elements(By.XPATH, sel)
                if elems and elems[0].is_displayed():
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", elems[0])
                    time.sleep(1)
                    driver.execute_script("arguments[0].click();", elems[0])
                    clicks += 1
                    logger.info(f"✓ Clicked 'Load more' recruiter actions (Batch {clicks})")
                    time.sleep(2)
                    break

        # Simulate candidate reviewing recruiter list
        driver.execute_script("window.scrollBy({top: 200, behavior: 'smooth'});")
        time.sleep(2.5)

    except Exception as e:
        logger.warning(f"Error during recruiter actions engagement: {e}")


def share_interest_early_access_roles(driver: WebDriver, max_shares: int = None) -> int:
    """
    Navigates to Early Access Roles (https://www.naukri.com/mnjuser/recommended-earjobs)
    and clicks 'Share Interest' on ALL available recommended roles from top companies.
    Also processes all recommended roles from the post-share confirmation screen
    (//*[@id="root"]/main/div[1]/div[1]/div[4]/div[2]).
    """
    logger.info("--------------------------------------------------")
    logger.info("  [3/4] Early Access Roles (Share Interest)       ")
    logger.info("--------------------------------------------------")
    shared_count = 0
    try:
        driver.get("https://www.naukri.com/mnjuser/recommended-earjobs")
        time.sleep(4)

        share_btn_xpaths = [
            "/html/body/main/div/div/div/section[1]/div//button[contains(translate(., 'SHARE INTEREST', 'share interest'), 'share interest')]",
            "/html/body/main/div/div/div/section[1]/div/div/div//button",
            "//section[1]//button[contains(translate(., 'SHARE INTEREST', 'share interest'), 'share interest')]",
            "//button[contains(translate(., 'SHARE INTEREST', 'share interest'), 'share interest')]",
            "//div[contains(@class, 'ear-jobs')]//button",
        ]

        def find_main_page_buttons():
            for xp in share_btn_xpaths:
                try:
                    btns = driver.find_elements(By.XPATH, xp)
                    visible = [b for b in btns if b.is_displayed() and "share" in (b.text or "").lower()]
                    if visible:
                        return visible
                except Exception:
                    continue
            return []

        buttons = find_main_page_buttons()

        if not buttons:
            logger.info("  No pending 'Share Interest' early access roles found.")
            return 0

        initial_count = len(buttons)
        logger.info(f"  Found {initial_count} Early Access role(s) available. Sharing interest for ALL...")

        while max_shares is None or shared_count < max_shares:
            buttons = find_main_page_buttons()
            if not buttons:
                break

            btn = buttons[0]
            try:
                card_text = ""
                try:
                    parent_card = btn.find_element(
                        By.XPATH,
                        "./ancestor::div[contains(@class, 'card') or contains(@class, 'tuple') or contains(@class, 'job') or parent::section][1]"
                    )
                    card_text = parent_card.text.split("\n")[0]
                except Exception:
                    pass

                role_label = card_text if card_text else f"Role #{shared_count + 1}"
                logger.info(f"  -> Clicking 'Share Interest' for: {role_label}...")

                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
                time.sleep(1)
                driver.execute_script("arguments[0].click();", btn)
                time.sleep(3.5)
                shared_count += 1
                logger.info(f"  ✓ Interest shared successfully! (Total shared: {shared_count})")

                # Check and exhaust any post-submission recommendation list
                while max_shares is None or shared_count < max_shares:
                    success_screen_buttons = driver.find_elements(
                        By.XPATH,
                        "//*[@id='root']/main/div[1]/div[1]/div[4]/div[2]//button[contains(translate(., 'SHARE INTEREST', 'share interest'), 'share interest')] | "
                        "//div[contains(@class, 'success') or contains(@class, 'confirm')]//button[contains(translate(., 'SHARE INTEREST', 'share interest'), 'share interest')]"
                    )
                    visible_succ_btns = [b for b in success_screen_buttons if b.is_displayed() and "share" in (b.text or "").lower()]

                    if not visible_succ_btns:
                        break

                    next_btn = visible_succ_btns[0]
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", next_btn)
                    time.sleep(1)
                    driver.execute_script("arguments[0].click();", next_btn)
                    time.sleep(3)
                    shared_count += 1
                    logger.info(f"  ✓ Additional interest shared from confirmation screen! (Total shared: {shared_count})")

                # Return to main recommended-earjobs page to check for remaining roles
                driver.get("https://www.naukri.com/mnjuser/recommended-earjobs")
                time.sleep(3)

            except Exception as e:
                logger.warning(f"  Could not click 'Share Interest' button: {e}")
                break

        logger.info(f"★ Completed Early Access sharing: successfully shared interest for all {shared_count} role(s).")

    except Exception as e:
        logger.warning(f"Error during early access roles engagement: {e}")

    return shared_count


def analyze_application_history_insights(driver: WebDriver, max_tiles: int = 10) -> list:
    """
    Navigates to https://www.naukri.com/myapply/historypage, iterates through recent
    application cards, opens their drawer, and extracts 'What may work for you'
    criteria (Keyskills, Location, Work Experience, Early Applicant, Industry, Department).
    Saves structured results to application_insights.json and logs a profile match breakdown.
    """
    logger.info("--------------------------------------------------")
    logger.info("  [4/4] Application History & Match Insights      ")
    logger.info("--------------------------------------------------")
    insights_list = []
    try:
        driver.get("https://www.naukri.com/myapply/historypage")
        time.sleep(4)

        container_xpath = "/html/body/div/div/div[4]/div[2]/div[1]/div[2]"
        containers = driver.find_elements(By.XPATH, container_xpath)
        if not containers:
            containers = driver.find_elements(
                By.XPATH,
                "//div[contains(@class, 'applied-jobs') or contains(@class, 'tuple-container')]"
            )

        if not containers:
            logger.warning("Could not locate application history list container.")
            return []

        tiles = containers[0].find_elements(By.XPATH, "./div")
        sample_size = min(len(tiles), max_tiles)
        logger.info(f"Found {len(tiles)} applied jobs in history. Analyzing first {sample_size}...")

        target_criteria = ["Early Applicant", "Keyskills", "Location", "Work Experience", "Industry", "Department"]

        for idx in range(sample_size):
            tile = tiles[idx]
            lines = [l.strip() for l in tile.text.split("\n") if l.strip()]
            job_title = lines[0] if lines else f"Job #{idx+1}"
            company = lines[1] if len(lines) > 1 else "Unknown"

            # Click tile to open drawer
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", tile)
            time.sleep(0.5)
            driver.execute_script("arguments[0].click();", tile)
            time.sleep(2)

            record = {
                "job_title": job_title,
                "company": company,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "criteria": {},
            }

            # Locate "What may work for you?" section in drawer
            headers = driver.find_elements(By.XPATH, "//*[contains(text(), 'What may work for you')]")
            for h in headers:
                try:
                    container_elem = h.find_element(By.XPATH, "./ancestor::div[3]")
                    items = container_elem.find_elements(
                        By.XPATH,
                        ".//li | .//div[.//i[contains(@class, 'naukicon')]]"
                    )
                    for item in items:
                        txt = item.text.strip()
                        for crit in target_criteria:
                            if crit.lower() in txt.lower() and crit not in record["criteria"]:
                                icons = item.find_elements(By.XPATH, ".//i | .//svg | .//span")
                                icon_classes = " ".join([ic.get_attribute("class") or "" for ic in icons])
                                if "check-circle" in icon_classes or "check" in icon_classes:
                                    record["criteria"][crit] = True
                                elif "crossed-circle" in icon_classes or "cross" in icon_classes:
                                    record["criteria"][crit] = False
                except Exception:
                    pass

            insights_list.append(record)
            logger.info(f"  [{idx+1}/{sample_size}] {job_title[:35]} | {company[:20]}")
            logger.info(f"        Criteria: {record['criteria']}")

        # Save structured JSON
        if insights_list:
            try:
                with open(INSIGHTS_JSON_PATH, "w", encoding="utf-8") as f:
                    json.dump(insights_list, f, indent=2)
                logger.info(f"✓ Saved application match insights to {INSIGHTS_JSON_PATH}")
            except Exception as e:
                logger.warning(f"Could not save application_insights.json: {e}")

            # Aggregate Summary
            logger.info("\n" + "=" * 65)
            logger.info("  APPLICATION HISTORY PROFILE MATCH SUMMARY (Last %d Jobs)", len(insights_list))
            logger.info("=" * 65)
            for c_name in target_criteria:
                matches = sum(1 for rec in insights_list if rec["criteria"].get(c_name) is True)
                total = sum(1 for rec in insights_list if c_name in rec["criteria"])
                pct = (matches / total * 100) if total > 0 else 0
                status_icon = "✓" if pct >= 70 else ("⚠️" if pct >= 40 else "❌")
                logger.info(f"  {status_icon} {c_name:<18} : {matches}/{total} ({pct:.0f}%)")
            logger.info("-" * 65)

            # Actionable Profile Recommendation
            ind_mismatches = sum(1 for rec in insights_list if rec["criteria"].get("Industry") is False)
            dept_mismatches = sum(1 for rec in insights_list if rec["criteria"].get("Department") is False)
            if ind_mismatches > 0 or dept_mismatches > 0:
                logger.info("💡 PROFILE INSIGHT TIP:")
                if ind_mismatches > 0:
                    logger.info("   - 'Industry' mismatch detected in applied jobs. Updating your Naukri Profile")
                    logger.info("     'Employment Details' -> Industry to 'IT Services & Consulting' or")
                    logger.info("     'Software Product' will increase your match score.")
                if dept_mismatches > 0:
                    logger.info("   - 'Department' mismatch detected. Align your Department to")
                    logger.info("     'Engineering - Software & QA' or 'Data Science & Analytics'.")
                logger.info("=" * 65)

    except Exception as e:
        logger.warning(f"Error during application history analysis: {e}")

    return insights_list


def update_resume_headline(driver: WebDriver, config: dict) -> bool:
    """
    Updates Resume Headline on Naukri profile with dynamic rotation,
    strategic keyword front-loading, and humanized typing.
    Evaluates headline quality on the 100-point Engaging Candidate Index.
    """
    try:
        logger.info("Updating Resume Headline to refresh candidate activity & keyword placement...")
        edit_buttons = driver.find_elements(
            By.XPATH,
            "//div[contains(@class, 'resumeHeadline')]//span[contains(text(), 'edit') or contains(@class, 'edit') or contains(text(), 'Edit')] | "
            "//span[normalize-space()='Edit' and ancestor::div[contains(@class, 'resumeHeadline')]] | "
            "//div[contains(@class, 'resumeHeadline')]//*[@class and contains(@class, 'icon')]"
        )
        if not edit_buttons:
            logger.warning("Could not find headline edit button.")
            return False

        human_click(driver, edit_buttons[0], pause_before=0.8, pause_after=1.8)

        try:
            ta = WebDriverWait(driver, 6).until(
                EC.visibility_of_element_located((
                    By.XPATH,
                    "//textarea[@id='resumeHeadlineTxt' or @name='resumeHeadline' or contains(@class, 'fue__text-area') or contains(@class, 'resumeHeadlineTxt') or contains(@class, 'headline')] | //form[@name='resumeHeadlineForm']//textarea | //form//textarea"
                ))
            )
        except Exception:
            tas = driver.find_elements(
                By.XPATH,
                "//textarea[@id='resumeHeadlineTxt' or @name='resumeHeadline' or contains(@class, 'fue__text-area') or contains(@class, 'resumeHeadlineTxt') or contains(@class, 'headline')] | //form//textarea"
            )
            ta = tas[0] if tas else None

        if not ta:
            logger.warning("Could not find headline textarea.")
            return False

        current_text = (ta.get_attribute("value") or "").strip()
        new_text = select_next_resume_headline(current_text, config)
        eval_res = evaluate_headline_quality(new_text)

        logger.info(f"  Current headline on profile: \"{current_text[:75]}...\"")
        logger.info(f"  Rotating to dynamic headline: \"{new_text[:75]}...\"")
        logger.info(f"  ★ Engaging Candidate Score: {eval_res['score']}/100 | Length: {eval_res['length']}/250 chars")
        logger.info(f"  ★ Front-Loaded Snippet (Mobile/Desktop): \"{eval_res['front_loaded_chars']}\"")

        human_type_into_element(driver, ta, new_text, clear_first=True)

        save_buttons = driver.find_elements(
            By.XPATH,
            "//form[@name='resumeHeadlineForm']//button[normalize-space()='Save' or contains(text(), 'Save')] | "
            "//div[contains(@class, 'lightbox') or contains(@class, 'modal') or contains(@class, 'drawer') or contains(@class, 'resumeHeadline')]//button[normalize-space()='Save'] | "
            "//button[normalize-space()='Save' and contains(@class, 'btn-dark-ot')]"
        )
        saved = False
        for btn in save_buttons:
            if btn.is_displayed():
                human_click(driver, btn, pause_before=0.8, pause_after=2.5)
                saved = True
                break

        if saved:
            time.sleep(2)
            state = load_booster_state()
            state["last_headline_update_time"] = datetime.now().isoformat()
            state["current_headline"] = new_text
            if "headline_history" not in state or not isinstance(state["headline_history"], list):
                state["headline_history"] = []
            state["headline_history"].append({
                "timestamp": datetime.now().isoformat(),
                "headline": new_text[:120],
                "score": eval_res["score"],
            })
            state["headline_history"] = state["headline_history"][-15:]
            save_booster_state(state)
            logger.info("✓ Resume headline successfully rotated and updated with human-like cadence!")

            human_dwell(4.0, 7.0, "Observing updated profile headline")
            human_scroll(driver, distance=300, steps=3)
            human_dwell(2.0, 3.5)
            human_scroll(driver, distance=-300, steps=2)
            return True
        else:
            logger.warning("Could not find visible Save button candidate in headline modal.")
            return False
    except Exception as e:
        logger.warning(f"Error during headline update: {e}")
        return False


def update_profile_summary(driver: WebDriver, config: dict, force: bool = False) -> bool:
    """
    Updates the 1,000-character Profile Summary on Naukri profile page
    (https://www.naukri.com/mnjuser/profile).
    Ensures high-density ATS keyword coverage (AWS, PySpark, Databricks, Redshift, Snowflake, Airflow, SQL)
    and quantifiable achievements to engage recruiters who click into the candidate profile.
    Updated with natural cadence (e.g. once every 7 days or when text changes).
    """
    personals = config.get("personals", {}) if config else {}
    target_summary = personals.get("profile_summary") or OPTIMIZED_PROFILE_SUMMARY
    target_summary = target_summary.strip()

    state = load_booster_state()
    last_update_str = state.get("last_profile_summary_update_time")
    if last_update_str and not force:
        try:
            last_dt = datetime.fromisoformat(last_update_str)
            days_since = (datetime.now() - last_dt).total_seconds() / 86400.0
            if days_since < 5.0 and state.get("current_profile_summary") == target_summary:
                logger.info(f"✓ Profile Summary was synced recently ({days_since:.1f} days ago). Skipping.")
                return False
        except Exception:
            pass

    logger.info("Syncing high-density ATS Profile Summary on Naukri...")
    try:
        edit_buttons = driver.find_elements(
            By.XPATH,
            "//div[contains(@class, 'profileSummary') or @id='lazyProfileSummary']//span[contains(text(), 'edit') or contains(@class, 'edit') or normalize-space()='Edit'] | "
            "//div[contains(@class, 'profile-summary')]//span[normalize-space()='Edit'] | "
            "//span[normalize-space()='Edit' and ancestor::div[contains(@class, 'profileSummary') or @id='lazyProfileSummary']]"
        )
        if not edit_buttons:
            add_buttons = driver.find_elements(
                By.XPATH,
                "//div[contains(@class, 'profileSummary') or @id='lazyProfileSummary']//span[contains(text(), 'Add') or contains(text(), 'add')] | "
                "//span[normalize-space()='Add Profile Summary']"
            )
            if add_buttons:
                edit_buttons = add_buttons

        if not edit_buttons:
            logger.info("Profile Summary edit/add button not found. Skipping summary update.")
            return False

        human_click(driver, edit_buttons[0], pause_before=0.8, pause_after=1.8)

        try:
            ta = WebDriverWait(driver, 5).until(
                EC.visibility_of_element_located((
                    By.XPATH,
                    "//textarea[@id='profileSummaryTxt' or @name='profileSummary' or contains(@class, 'profileSummary') or contains(@class, 'summary')] | "
                    "//form[@name='profileSummaryForm']//textarea | //form//textarea"
                ))
            )
        except Exception:
            tas = driver.find_elements(
                By.XPATH,
                "//textarea[@id='profileSummaryTxt' or @name='profileSummary' or contains(@class, 'profileSummary') or contains(@class, 'summary')] | //form//textarea"
            )
            ta = tas[0] if tas else None

        if not ta:
            logger.warning("Could not locate Profile Summary textarea.")
            return False

        current_val = (ta.get_attribute("value") or "").strip()
        if current_val == target_summary and not force:
            logger.info("✓ Profile Summary on profile already matches target summary. Preserving.")
            cancel_btns = driver.find_elements(By.XPATH, "//button[normalize-space()='Cancel'] | //span[contains(@class, 'crossIcon') or contains(@class, 'close')]")
            if cancel_btns and cancel_btns[0].is_displayed():
                driver.execute_script("arguments[0].click();", cancel_btns[0])
            return False

        logger.info(f"Typing optimized Profile Summary ({len(target_summary)} chars)...")
        human_type_into_element(driver, ta, target_summary, clear_first=True)

        save_buttons = driver.find_elements(
            By.XPATH,
            "//form[@name='profileSummaryForm']//button[normalize-space()='Save' or contains(text(), 'Save')] | "
            "//div[contains(@class, 'profileSummary')]//button[normalize-space()='Save'] | "
            "//button[normalize-space()='Save' and contains(@class, 'btn-dark-ot')]"
        )
        saved = False
        for btn in save_buttons:
            if btn.is_displayed():
                human_click(driver, btn, pause_before=0.8, pause_after=2.5)
                saved = True
                break

        if saved:
            time.sleep(2)
            state["last_profile_summary_update_time"] = datetime.now().isoformat()
            state["current_profile_summary"] = target_summary
            save_booster_state(state)
            logger.info("✓ High-impact Profile Summary successfully saved on Naukri!")
            human_dwell(3.0, 5.0, "Observing updated profile summary")
            return True

    except Exception as e:
        logger.warning(f"Error updating Profile Summary: {e}")

    return False


def boost_profile(driver: WebDriver, config: dict) -> bool:
    """
    Refreshes the candidate's Naukri profile and platform engagement by:
    1. Re-uploading the resume PDF (with natural 18h cadence checking)
    2. Dynamically rotating resume headline among diverse, high-impact variations with human typing
    3. Interacting with the Notification Bell drawer and activity feed (Button 1 & list)
    4. Opening Profile & Recruiter Menu Drawer -> Search Appearances (Button 2 & Link 2.1)
    5. Opening Profile & Recruiter Menu Drawer -> Recruiter Actions (Button 2 & Link 2.2)
    6. Sharing Interest in Recommended Early Access Roles
    7. Visiting Application History & scraping 'What may work for you' match insights
    All interactions include human-like dwell times and trusted browser events.
    """
    logger.info("==================================================")
    logger.info("  NAUKRI PROFILE BOOSTER & ENGAGEMENT SUITE       ")
    logger.info("==================================================")

    driver.get("https://www.naukri.com/mnjuser/profile")
    human_dwell(2.5, 4.0, "Loading candidate profile page")

    from resume_resolver import resolve_resume_path

    personals = config.get("personals", {})
    settings = config.get("settings", {})
    resume_path = resolve_resume_path(config)
    force_upload = settings.get("force_resume_upload", False)

    state = load_booster_state()

    resume_updated = False
    headline_updated = False

    # 1. Re-upload Resume PDF (Humanized frequency check)
    should_upload = True
    last_upload_str = state.get("last_resume_upload_time")
    if last_upload_str and not force_upload:
        try:
            last_upload_dt = datetime.fromisoformat(last_upload_str)
            hours_since = (datetime.now() - last_upload_dt).total_seconds() / 3600.0
            if hours_since < 18.0:
                should_upload = False
                logger.info(f"✓ Resume PDF was already synced recently ({hours_since:.1f}h ago). Skipping re-upload to maintain natural update cadence.")
        except Exception:
            pass

    if should_upload:
        if resume_path and os.path.isfile(resume_path):
            logger.info(f"Re-uploading resume: {resume_path}...")
            try:
                human_dwell(1.5, 3.0)
                file_inputs = driver.find_elements(By.XPATH, "//input[@id='attachCV' or @type='file']")
                if file_inputs:
                    file_input = file_inputs[0]
                    file_input.send_keys(os.path.abspath(resume_path))
                    time.sleep(4)
                    resume_updated = True
                    state["last_resume_upload_time"] = datetime.now().isoformat()
                    save_booster_state(state)
                    logger.info("✓ Resume successfully uploaded and synced on Naukri!")
                    # Human dwell: simulate verifying the uploaded resume preview
                    human_dwell(3.5, 6.0, "Verifying resume upload confirmation")
                else:
                    logger.warning("Could not find resume file upload input on profile page.")
            except Exception as e:
                logger.warning(f"Error during resume upload: {e}")
        else:
            logger.warning(f"Resume path '{resume_path}' does not exist. Skipping resume upload.")

    # 2. Touch Resume Headline with Dynamic Rotation & Strategic Front-Loading
    headline_updated = update_resume_headline(driver, config)

    # 2b. Sync High-Density ATS Profile Summary (1,000 chars)
    try:
        update_profile_summary(driver, config)
    except Exception as summ_err:
        logger.debug(f"Profile summary sync skipped or failed: {summ_err}")

    logger.info("--------------------------------------------------")
    if resume_updated or headline_updated:
        logger.info("★ SUCCESS: Profile freshness updated to 'TODAY'!")

    # Natural dwell pause before moving to notifications (prevents rapid robotic jumping)
    human_dwell(6.0, 11.0, "Pausing naturally before checking notification feed")

    # 3. Notification Bell & Activity Feed Engagement (with Job NVite auto-apply)
    engage_header_notifications(driver, config=config)
    human_dwell(5.0, 9.0, "Pausing naturally before recommended jobs review")

    # 4. Recommended Jobs Optimization
    optimize_and_apply_recommended_jobs(driver, config)
    human_dwell(5.0, 9.0, "Pausing naturally before recruiter performance review")

    # 5. Search Appearances & Keywords
    engage_performance_and_search_appearances(driver)
    human_dwell(4.0, 8.0, "Pausing naturally before recruiter actions review")

    # 6. Recruiter Actions Engagement
    engage_recruiter_actions(driver)
    human_dwell(4.0, 8.0, "Pausing naturally before early access roles review")

    # 7. Share Interest for Recommended Early Access Roles
    share_interest_early_access_roles(driver)
    human_dwell(4.0, 8.0, "Pausing naturally before application history analysis")

    # 8. Analyze Application History Match Insights
    analyze_application_history_insights(driver, max_tiles=8)
    try:
        from insights_generator import generate_insights_html
        generate_insights_html()
    except Exception as e:
        logger.debug(f"Could not update insights.html: {e}")

    state["last_boost_time"] = datetime.now().isoformat()
    save_booster_state(state)

    logger.info("==================================================")
    logger.info("  PROFILE BOOSTER & ENGAGEMENT COMPLETED          ")
    logger.info("==================================================")
    return True


def quick_boost_profile(driver: WebDriver, config: dict) -> bool:
    """
    Rapid, high-frequency profile boost (~25-35s):
    1. Navigates to candidate profile page
    2. Rotates headline to the next high-converting keyword cluster
    3. Types naturally and saves, resetting candidate freshness to 'TODAY'
    4. Evaluates and logs the Engaging Candidate Index score
    Ideal for running during peak recruiter search hours (e.g. 9-11 AM, 2-5 PM).
    """
    logger.info("==================================================")
    logger.info("  NAUKRI QUICK PROFILE FRESHNESS & HEADLINE BOOST ")
    logger.info("==================================================")
    driver.get("https://www.naukri.com/mnjuser/profile")
    human_dwell(2.5, 4.0, "Loading candidate profile page")

    success = update_resume_headline(driver, config)
    if success:
        state = load_booster_state()
        state["last_boost_time"] = datetime.now().isoformat()
        save_booster_state(state)
        logger.info("★ Quick Boost Complete: Freshness set to 'TODAY' with optimized keyword cluster.")
    else:
        logger.warning("Quick Boost did not complete headline update.")

    return success

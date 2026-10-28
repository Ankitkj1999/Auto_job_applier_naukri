import os
import re
import csv
import time
import random
import urllib.parse
import logging
from datetime import datetime, timedelta
from browser import human_click, human_dwell, human_scroll
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.common.exceptions import TimeoutException
from chatbot_handler import handle_naukri_chatbot_drawer, check_apply_success, check_apply_error
from external_job_tracker import (
    record_external_job,
    resolve_external_url,
    backfill_external_jobs_from_applied_csv,
)

logger = logging.getLogger("NaukriBot")
APPLIED_JOBS_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "applied_jobs.csv")
RUN_SUMMARY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "latest_run_summary.md")


class NaukriDailyLimitReached(Exception):
    """Raised when Naukri displays daily application quota or server rate limit errors."""
    pass


def is_hard_quota_limit(err_msg: str) -> bool:
    """
    Checks if an error message represents an explicit hard daily quota limit
    versus a transient single-job error or temporary glitch.
    """
    m_low = (err_msg or "").lower()
    hard_phrases = [
        "daily application limit",
        "daily limit",
        "reached your daily",
        "maximum applications",
        "limit exceeded",
        "quota reached",
        "quota exceeded",
    ]
    return any(p in m_low for p in hard_phrases)


def load_applied_job_ids() -> set:
    """Loads previously applied job URLs/IDs from CSV to prevent duplicate applications."""
    if not os.path.isfile(APPLIED_JOBS_CSV):
        return set()
    applied = set()
    try:
        with open(APPLIED_JOBS_CSV, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                jid = (row.get("Job ID") or "").strip()
                jurl = (row.get("Job URL") or "").strip()
                if jid:
                    applied.add(jid)
                if jurl:
                    applied.add(jurl)
    except Exception as e:
        logger.warning(f"Could not read applied_jobs.csv: {e}")
    return applied


def record_applied_job(job_id: str, title: str, company: str, location: str, job_url: str, status: str = "Applied") -> None:
    """Appends an applied job record to applied_jobs.csv."""
    file_exists = os.path.isfile(APPLIED_JOBS_CSV)
    try:
        with open(APPLIED_JOBS_CSV, "a", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["Date", "Job ID", "Title", "Company", "Location", "Status", "Job URL"])
            writer.writerow([
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                job_id,
                title,
                company,
                location,
                status,
                job_url,
            ])
    except Exception as e:
        logger.warning(f"Failed to record applied job: {e}")


def is_title_relevant(title: str, bad_words: list[str], mandatory_keywords: list[str] = None) -> bool:
    """
    Checks if a job title is relevant using a strict 2-layer filter:
    1. Blacklist: Must NOT contain any forbidden terms (e.g. Tester, SRE, Lead, Sales).
       Terms like GenAI or AI/ML are allowed when explicitly paired with Data Engineer.
    2. Whitelist: MUST contain at least one target keyword (e.g. Data Engineer, PySpark, Databricks).
    """
    t_low = title.lower()

    # Core data engineering indicators
    has_core_data_eng = any(k in t_low for k in [
        "data engineer", "data engineering", "data engg", "data eng",
        "data developer", "big data", "pyspark", "spark", "databricks",
        "etl", "snowflake", "analytics engineer", "data platform",
        "azure data", "aws data", "gcp data", "data pipeline",
        "data factory", "azure data factory", "adf", "informatica",
        "data integration", "data migration", "dwh"
    ])

    # 1. Reject forbidden terms
    for w in bad_words:
        w_low = w.lower()
        # Terms like GenAI or AI/ML are acceptable sub-specializations when explicitly paired with Data Engineer
        if w_low in ["genai", "gen ai", "generative ai", "ai/ml", "ai and data", "data and ai"] and has_core_data_eng:
            continue

        pattern = r"(?<!\w)" + re.escape(w_low) + r"(?!\w)"
        if re.search(pattern, t_low):
            return False

    # 2. Require at least one mandatory keyword if provided
    if mandatory_keywords:
        matched = any(k.lower() in t_low for k in mandatory_keywords)
        # Also match common title permutations like "Sr Engineer - Data" or "Data Solution Engineer"
        if not matched:
            if re.search(r'\b(engineer|developer|consultant)\b.*\bdata\b', t_low) or re.search(r'\bdata\b.*\b(engineer|developer|consultant)\b', t_low):
                matched = True
        if not matched:
            return False

    return True


def is_location_match(job_loc: str, target_locations: list[str]) -> bool:
    """
    Verifies that the job location matches the candidate's target locations.
    Allows Delhi NCR, Gurgaon, Gurugram, Noida, Bengaluru/Bangalore, Hyderabad,
    Pune, Mumbai, and Remote / Hybrid roles.
    """
    if not target_locations or not job_loc:
        return True

    j_low = job_loc.lower().strip()

    # Always accept Remote, Work from home, Pan India, or flexible Hybrid
    if any(k in j_low for k in ["remote", "work from home", "wfh", "anywhere in india", "pan india", "all india"]):
        return True

    # Generic hybrid / flexible roles without specific excluded location
    if j_low in ["hybrid", "hybrid - hybrid", "flexible", "hybrid - any", "any"]:
        return True

    # Check if target_locations specifies All India / Pan India
    if any(loc.lower().strip() in ["all india", "pan india", "anywhere", "all", "india"] for loc in target_locations):
        return True

    # Normalize candidate target locations
    for loc in target_locations:
        l_low = loc.lower().strip()
        if l_low in ["gurgaon", "gurugram"]:
            if "gurgaon" in j_low or "gurugram" in j_low:
                return True
        elif l_low in ["delhi", "delhi / ncr", "delhi/ncr", "ncr", "new delhi"]:
            if any(d in j_low for d in ["delhi", "ncr", "noida", "gurgaon", "gurugram"]):
                return True
        elif l_low in ["bangalore", "bengaluru"]:
            if "bangalore" in j_low or "bengaluru" in j_low:
                return True
        elif l_low in ["hyderabad", "secunderabad"]:
            if "hyderabad" in j_low or "secunderabad" in j_low:
                return True
        elif l_low in ["mumbai", "bombay", "navi mumbai", "thane"]:
            if any(m in j_low for m in ["mumbai", "navi mumbai", "thane"]):
                return True
        elif l_low in j_low:
            return True

    # If it's a hybrid role, check if any of the target locations match
    if "hybrid" in j_low:
        for loc in target_locations:
            l_low = loc.lower().strip()
            if l_low in ["gurgaon", "gurugram"]:
                if "gurgaon" in j_low or "gurugram" in j_low:
                    return True
            elif l_low in ["delhi", "delhi / ncr", "delhi/ncr", "ncr"]:
                if any(d in j_low for d in ["delhi", "ncr", "noida", "gurgaon", "gurugram"]):
                    return True
            elif l_low in ["bangalore", "bengaluru"]:
                if "bangalore" in j_low or "bengaluru" in j_low:
                    return True
            elif l_low in ["hyderabad", "secunderabad"]:
                if "hyderabad" in j_low or "secunderabad" in j_low:
                    return True
            elif l_low in ["mumbai", "navi mumbai"]:
                if "mumbai" in j_low:
                    return True
            elif l_low in j_low:
                return True

    return False


def parse_experience_range(exp_text: str) -> tuple[int | None, int | None]:
    """
    Parses experience strings like '3-5 Yrs', '2 - 6 years', '4+ Yrs', '3 Yrs'.
    Returns (min_exp, max_exp). If unparseable, returns (None, None).
    """
    if not exp_text:
        return None, None

    clean = exp_text.lower().replace(",", "")

    # Range: e.g. "3-5 Yrs", "3 - 5 Yrs", "3 to 5 Yrs"
    m_range = re.search(r"(\d+)\s*(?:-|to)\s*(\d+)", clean)
    if m_range:
        return int(m_range.group(1)), int(m_range.group(2))

    # Plus: e.g. "5+ Yrs", "3+ years"
    m_plus = re.search(r"(\d+)\s*\+", clean)
    if m_plus:
        val = int(m_plus.group(1))
        return val, val + 5

    # Single number: e.g. "3 Yrs", "3 years"
    m_single = re.search(r"(\d+)\s*(?:yr|year)", clean)
    if m_single:
        val = int(m_single.group(1))
        return val, val

    return None, None


def is_experience_suitable(
    job_exp_text: str,
    candidate_exp: int,
    min_allowed: int | None = None,
    max_allowed: int | None = None,
    max_stretch: int = 1,
) -> tuple[bool, str]:
    """
    Checks if a job's experience requirement matches candidate's experience profile.
    Returns (is_suitable, reason).
    """
    min_req, max_req = parse_experience_range(job_exp_text)
    if min_req is None and max_req is None:
        return True, "Experience not specified"

    if min_allowed is None:
        min_allowed = max(0, candidate_exp - 2)
    if max_allowed is None:
        max_allowed = candidate_exp + 2

    # 1. Job minimum experience requirement cannot exceed candidate experience + stretch
    if min_req is not None and min_req > (candidate_exp + max_stretch):
        return False, f"Job requires min {min_req} YOE (Candidate: {candidate_exp} YOE, stretch: {max_stretch})"

    # 2. Job minimum exceeds configured max_allowed
    if min_req is not None and min_req > max_allowed:
        return False, f"Job min {min_req} YOE exceeds upper limit {max_allowed} YOE"

    # 3. Job maximum is strictly below configured min_allowed (e.g. 0-1 Yr fresher/intern)
    if max_req is not None and max_req < min_allowed:
        return False, f"Job max {max_req} YOE is below lower limit {min_allowed} YOE"

    return True, f"Matches experience range ({min_req}-{max_req} Yrs)"


def extract_experience_from_card(card) -> str:
    """Extracts experience requirement text from a search result card."""
    selectors = [
        ".//span[contains(@class, 'exp-wrap')]",
        ".//span[contains(@class, 'expwdth')]",
        ".//span[contains(@class, 'exp')]",
        ".//li[contains(@class, 'experience')]",
        ".//span[contains(@class, 'ni-job-tuple-icon-experience')]/..",
        ".//span[contains(text(), 'Yrs') or contains(text(), 'yrs') or contains(text(), 'Year')]",
    ]
    for sel in selectors:
        try:
            elem = card.find_element(By.XPATH, sel)
            text = elem.text.strip()
            if text and any(w in text.lower() for w in ["yr", "year"]):
                return text
        except Exception:
            continue
    return ""


def extract_experience_from_page(driver: WebDriver) -> str:
    """Extracts experience requirement text from the job details page."""
    selectors = [
        "//div[contains(@class, 'styles_jexp')]//span",
        "//div[contains(@class, 'styles_jexp')]",
        "//div[contains(@class, 'experience')]//span",
        "//div[contains(@class, 'experience')]",
        "//span[contains(@class, 'exp-wrap')]",
        "//div[contains(@class, 'exp')]//span",
        "//span[contains(@class, 'exp')]",
        "//span[contains(text(), 'Yrs') or contains(text(), 'yrs') or contains(text(), 'Year')]",
    ]
    for sel in selectors:
        try:
            elem = driver.find_element(By.XPATH, sel)
            text = elem.text.strip()
            if text and any(w in text.lower() for w in ["yr", "year"]):
                return text
        except Exception:
            continue
    return ""


def find_naukri_apply_button(driver: WebDriver):
    """
    Finds the actual Apply button on Naukri's job details page,
    strictly ignoring the Save / Bookmark / Share buttons.
    """
    # 1. Check explicit IDs
    for btn_id in ["apply-button", "company-site-button"]:
        try:
            elem = driver.find_element(By.ID, btn_id)
            if elem.is_displayed():
                return elem
        except Exception:
            pass

    # 2. Look for buttons or anchors containing 'Apply'
    candidates = driver.find_elements(
        By.XPATH,
        "//button[contains(translate(., 'APPLY', 'apply'), 'apply')] | "
        "//a[contains(translate(., 'APPLY', 'apply'), 'apply')] | "
        "//button[contains(@class, 'apply')] | "
        "//div[contains(@class, 'apply')]//button"
    )

    for btn in candidates:
        try:
            if not btn.is_displayed():
                continue
            text = (btn.text or "").strip().lower()
            cls = (btn.get_attribute("class") or "").lower()
            btn_id = (btn.get_attribute("id") or "").lower()
            combined = f"{text} {cls} {btn_id}"

            # STRICT GUARD: Never click Save / Saved / Bookmark / Share
            if any(bad in combined for bad in ["save", "saved", "bookmark", "share"]):
                continue

            if "apply" in combined:
                return btn
        except Exception:
            continue
    return None


def search_and_apply_stage(
    driver: WebDriver,
    config: dict,
    stage_name: str,
    stage_locations: list[str],
    applied_set: set,
    total_applied: int,
    max_apps: int,
    applied_in_run: list[dict] = None,
    error_tracker: dict = None,
) -> int:
    """
    Executes search and apply for a specific location stage (e.g. Primary Delhi NCR or Secondary Tech Hubs).
    Returns the updated total_applied count.
    """
    if applied_in_run is None:
        applied_in_run = []
    if error_tracker is None:
        error_tracker = {"consecutive_transient_errors": 0}
    search_cfg = config.get("search", {})
    personals = config.get("personals", {})
    settings = config.get("settings", {})
    keywords = search_cfg.get("search_terms", ["Data Engineer", "AWS Data Engineer"])
    exp = search_cfg.get("experience", 3)
    exp_levels = search_cfg.get("experience_levels", [exp])
    if exp not in exp_levels:
        exp_levels.insert(0, exp)

    candidate_exp = personals.get("total_experience_years", exp)
    min_exp = search_cfg.get("min_experience", 1)
    max_exp = search_cfg.get("max_experience", 6)
    max_stretch = search_cfg.get("max_experience_stretch", 1.5)
    bad_words = search_cfg.get("title_bad_words", [])
    mandatory_words = search_cfg.get("title_mandatory_words", [])
    pause_sec = settings.get("pause_between_applications_sec", 4)
    skip_external = settings.get("skip_external_company_sites", True)
    freshness_days = search_cfg.get("freshness_days", 3)
    max_pages = search_cfg.get("max_pages_per_keyword", 5)

    loc_param = ", ".join(stage_locations) if stage_locations else ""
    is_delhi_ncr = (
        any(loc.lower() in ["gurgaon", "gurugram", "noida", "delhi / ncr", "delhi"] for loc in stage_locations)
        and len(stage_locations) <= 4
        if stage_locations else False
    )

    for exp_target in exp_levels:
        if total_applied >= max_apps:
            break

        for keyword in keywords:
            if total_applied >= max_apps:
                logger.info(f"Reached application target of {max_apps} jobs for this run!")
                break

            slug = re.sub(r'[^a-zA-Z0-9]+', '-', keyword.strip().lower()).strip('-')
            fresh_param = f"&jobAge={freshness_days}" if freshness_days else ""
            loc_display = loc_param if loc_param else "Open / All Locations (Pan-India)"

            for page_num in range(1, max_pages + 1):
                if total_applied >= max_apps:
                    break

                logger.info("\n" + "=" * 60)
                logger.info(f">>> [{stage_name}] SEARCHING: \"{keyword}\" (Exp: {exp_target} YOE, Page {page_num}/{max_pages}) in \"{loc_display}\" (Freshness: Last {freshness_days} days) <<<")
                logger.info("=" * 60)

                # Build Naukri Search URL for current page
                if is_delhi_ncr:
                    if page_num == 1:
                        search_url = f"https://www.naukri.com/{slug}-jobs-in-delhi-ncr?experience={exp_target}{fresh_param}"
                    else:
                        search_url = f"https://www.naukri.com/{slug}-jobs-in-delhi-ncr-{page_num}?experience={exp_target}{fresh_param}"
                else:
                    query_params = {
                        "k": keyword,
                        "experience": str(exp_target),
                    }
                    if loc_param and loc_param.lower() not in ["pan india", "all india", "anywhere", "open"]:
                        query_params["l"] = loc_param
                    if freshness_days:
                        query_params["jobAge"] = str(freshness_days)
                    if page_num > 1:
                        query_params["pageNo"] = str(page_num)
                    search_url = f"https://www.naukri.com/jobs-in-india?{urllib.parse.urlencode(query_params)}"

                logger.info(f"Loading search URL: {search_url}")
                try:
                    driver.get(search_url)
                except TimeoutException:
                    logger.warning("  Page load timed out waiting for all network assets. Stopping further page loading and continuing...")
                    try:
                        driver.execute_script("window.stop();")
                    except Exception:
                        pass
                time.sleep(3.5)

                # Ensure freshness filter is applied if Naukri redirected on page 1
                if page_num == 1 and freshness_days and f"jobAge={freshness_days}" not in driver.current_url:
                    try:
                        fresh_opt = driver.find_elements(By.XPATH, f"//span[text()='Last {freshness_days} days'] | //label[contains(., 'Last {freshness_days} days')]")
                        if fresh_opt and fresh_opt[0].is_displayed():
                            logger.info(f"Activating 'Last {freshness_days} days' freshness filter...")
                            driver.execute_script("arguments[0].click();", fresh_opt[0])
                            time.sleep(3)
                    except Exception:
                        pass

                # Scrape job cards on current page
                job_cards = driver.find_elements(
                    By.XPATH,
                    "//div[contains(@class, 'srp-jobtuple-wrapper')]"
                )
                if not job_cards:
                    job_cards = driver.find_elements(
                        By.XPATH,
                        "//div[contains(@class, 'cust-job-tuple')] | //article[contains(@class, 'jobTuple')]"
                    )

                if not job_cards:
                    logger.info(f"No job cards found on page {page_num}. Moving to next keyword.")
                    break

                logger.info(f"Found {len(job_cards)} job cards on page {page_num}.")
                seen_in_page = set()

                for card in job_cards:
                    if total_applied >= max_apps:
                        break

                    try:
                        # Extract Title and Link
                        title_elem = card.find_element(By.XPATH, ".//a[contains(@class, 'title')]")
                        title = title_elem.text.strip()
                        job_url = title_elem.get_attribute("href") or ""
                        job_id = card.get_attribute("data-job-id") or job_url.split("-")[-1].split("?")[0]
                    except Exception:
                        continue

                    if not job_url or job_url in seen_in_page or job_id in seen_in_page:
                        continue
                    seen_in_page.add(job_url)
                    seen_in_page.add(job_id)

                    try:
                        comp_elem = card.find_element(By.XPATH, ".//a[contains(@class, 'comp-name')] | .//span[contains(@class, 'comp-name')]")
                        company = comp_elem.text.strip()
                    except Exception:
                        company = "Unknown"

                    try:
                        loc_elem = card.find_element(By.XPATH, ".//span[contains(@class, 'loc-wrap')] | .//span[contains(@class, 'loc')]")
                        job_loc = loc_elem.text.strip()
                    except Exception:
                        job_loc = stage_locations[0] if stage_locations else "Delhi NCR"

                    # 1. Skip if already applied
                    if job_id in applied_set or job_url in applied_set:
                        logger.info(f"  [Skip] Already applied: {title} | {company}")
                        continue

                    # 2. Title relevance filtering (whitelist + blacklist)
                    if not is_title_relevant(title, bad_words, mandatory_words):
                        logger.info(f"  [Skip] Irrelevant title: \"{title}\" (not matching data engineering stack or blacklisted)")
                        continue

                    # 3. Experience suitability filtering on search card
                    job_exp = extract_experience_from_card(card)
                    if job_exp:
                        suitable, reason = is_experience_suitable(job_exp, candidate_exp, min_exp, max_exp, max_stretch)
                        if not suitable:
                            logger.info(f"  [Skip] Experience mismatch: \"{title}\" requires \"{job_exp}\" - {reason}")
                            continue

                    # 4. Location relevance check
                    if not is_location_match(job_loc, stage_locations):
                        logger.info(f"  [Skip] Location mismatch: \"{title}\" at \"{job_loc}\" (not in {stage_locations})")
                        continue

                    # 5. Check if card already says "Applied"
                    if "applied" in card.text.lower():
                        logger.info(f"  [Skip] Card indicates already applied: {title} | {company}")
                        applied_set.add(job_id)
                        continue

                    logger.info(f"\nEvaluating: \"{title}\" at \"{company}\" ({job_loc}) [Exp: {job_exp or 'N/A'}]")

                    # Human-like brief pause before opening card
                    time.sleep(random.uniform(1.2, 2.8))

                    # Open the job in a new tab
                    original_window = driver.current_window_handle
                    driver.execute_script("window.open(arguments[0], '_blank');", job_url)
                    time.sleep(random.uniform(2.5, 3.8))

                    new_windows = [w for w in driver.window_handles if w != original_window]
                    if not new_windows:
                        continue

                    driver.switch_to.window(new_windows[-1])
                    time.sleep(random.uniform(2.5, 3.8))

                    # Humanized browsing: simulate candidate reading job description & requirements
                    try:
                        human_scroll(driver, distance=random.randint(300, 500), steps=3)
                        time.sleep(random.uniform(2.0, 4.0))
                        human_scroll(driver, distance=-random.randint(200, 350), steps=2)
                        time.sleep(random.uniform(1.0, 2.0))
                    except Exception:
                        pass

                    try:
                        # Double check experience on details page if available
                        detail_exp = extract_experience_from_page(driver)
                        if detail_exp:
                            suitable, reason = is_experience_suitable(detail_exp, candidate_exp, min_exp, max_exp, max_stretch)
                            if not suitable:
                                logger.info(f"  [Skip] Details page experience mismatch: \"{detail_exp}\" - {reason}")
                                continue

                        # Look for the actual Apply Button on the Job Details Page
                        apply_btn = find_naukri_apply_button(driver)

                        if not apply_btn:
                            logger.info("  [Skip] No Apply button found on job page.")
                        else:
                            btn_text = (apply_btn.text or "").strip()
                            logger.info(f"  Found button: \"{btn_text}\"")

                            if "company site" in btn_text.lower():
                                logger.info(f"  [External] Found external application: '{title}' at '{company}'")
                                ext_url = resolve_external_url(driver, apply_btn, default_url=job_url)
                                record_external_job(
                                    config=config,
                                    job_id=job_id,
                                    title=title,
                                    company=company,
                                    location=job_loc,
                                    experience=job_exp or detail_exp or "",
                                    external_url=ext_url,
                                    naukri_url=job_url,
                                    status="Pending",
                                )
                                if skip_external:
                                    logger.info("  [Skip] External application recorded to tracker. Skipping auto-apply.")
                                    record_applied_job(job_id, title, company, job_loc, job_url, status="External Skipped")
                                    applied_set.add(job_id)
                                else:
                                    logger.info("  [External] Apply on Company Site.")
                                    record_applied_job(job_id, title, company, job_loc, job_url, status="External Link")
                                    applied_set.add(job_id)
                            elif "already applied" in btn_text.lower() or btn_text.lower() == "applied":
                                logger.info("  [Skip] Already applied to this job.")
                                applied_set.add(job_id)
                            else:
                                # Click the REAL Apply button with human-like mouse action (trusted event)
                                logger.info(f"  -> Clicking '{btn_text}'...")
                                human_click(driver, apply_btn, pause_before=random.uniform(0.6, 1.2), pause_after=random.uniform(1.5, 2.5))

                                # Check for immediate rate limit or daily limit error toast
                                has_err, err_msg = check_apply_error(driver)
                                if has_err:
                                    if is_hard_quota_limit(err_msg):
                                        logger.warning(f"\n{'!' * 70}")
                                        logger.warning(f"⚠️ NAUKRI DAILY QUOTA REACHED: \"{err_msg}\"")
                                        logger.warning("Daily application quota encountered.")
                                        logger.warning(f"Total jobs applied today: {total_applied}. Halting to protect account.")
                                        logger.warning(f"{'!' * 70}\n")
                                        raise NaukriDailyLimitReached(err_msg)
                                    else:
                                        error_tracker["consecutive_transient_errors"] += 1
                                        err_count = error_tracker["consecutive_transient_errors"]
                                        logger.warning(f"  ⚠️ Transient error on this job ({err_count}/3): \"{err_msg}\"")
                                        if total_applied == 0 and err_count >= 2:
                                            logger.warning(f"\n{'!' * 70}")
                                            logger.warning(f"⚠️ NAUKRI SERVER THROTTLE DETECTED: {err_count} consecutive application errors at start of run.")
                                            logger.warning(f"Naukri server returned: \"{err_msg}\"")
                                            logger.warning("Likely causes: Naukri 24h rolling limit active or anti-bot cooldown required.")
                                            logger.warning("Halting run immediately to protect candidate account.")
                                            logger.warning(f"{'!' * 70}\n")
                                            raise NaukriDailyLimitReached(f"Naukri server rate limit / early throttle: {err_msg}")
                                        elif err_count >= 3:
                                            logger.warning(f"\n{'!' * 70}")
                                            logger.warning(f"⚠️ NAUKRI LIMIT / PERSISTENT ERRORS ({err_count} consecutive): \"{err_msg}\"")
                                            logger.warning("Naukri server rate limit or repetitive errors encountered. Halting to protect account.")
                                            logger.warning(f"Total jobs applied today: {total_applied}.")
                                            logger.warning(f"{'!' * 70}\n")
                                            raise NaukriDailyLimitReached(err_msg)
                                        else:
                                            backoff_sec = 45 if err_count == 1 else 90
                                            logger.warning(f"  -> Adaptive cooldown: pausing for {backoff_sec}s to let server rate limits clear...")
                                            time.sleep(backoff_sec)
                                            logger.warning("  Skipping this specific job and continuing search...")
                                            continue

                                # Scenario 1: Instant 1-Click Apply (No screening questions required)
                                if check_apply_success(driver, apply_btn=apply_btn):
                                    logger.info("  ✓ Instant 1-Click apply succeeded directly (no side panel questions).")
                                    applied_successfully = True
                                else:
                                    # Scenario 2: Questionnaire Drawer (Screening questions required)
                                    applied_successfully = handle_naukri_chatbot_drawer(driver, config, job_title=title, company=company)

                                    # Re-check for rate/daily limit after questionnaire submission
                                    has_err, err_msg = check_apply_error(driver)
                                    if has_err:
                                        if is_hard_quota_limit(err_msg):
                                            logger.warning(f"\n{'!' * 70}")
                                            logger.warning(f"⚠️ NAUKRI DAILY QUOTA REACHED: \"{err_msg}\"")
                                            logger.warning("Daily application quota encountered.")
                                            logger.warning(f"Total jobs applied today: {total_applied}. Halting to protect account.")
                                            logger.warning(f"{'!' * 70}\n")
                                            raise NaukriDailyLimitReached(err_msg)
                                        else:
                                            error_tracker["consecutive_transient_errors"] += 1
                                            err_count = error_tracker["consecutive_transient_errors"]
                                            logger.warning(f"  ⚠️ Transient error on this job ({err_count}/3): \"{err_msg}\"")
                                            if total_applied == 0 and err_count >= 2:
                                                logger.warning(f"\n{'!' * 70}")
                                                logger.warning(f"⚠️ NAUKRI SERVER THROTTLE DETECTED: {err_count} consecutive application errors at start of run.")
                                                logger.warning(f"Naukri server returned: \"{err_msg}\"")
                                                logger.warning("Likely causes: Naukri 24h rolling limit active or anti-bot cooldown required.")
                                                logger.warning("Halting run immediately to protect candidate account.")
                                                logger.warning(f"{'!' * 70}\n")
                                                raise NaukriDailyLimitReached(f"Naukri server rate limit / early throttle: {err_msg}")
                                            elif err_count >= 3:
                                                logger.warning(f"\n{'!' * 70}")
                                                logger.warning(f"⚠️ NAUKRI LIMIT / PERSISTENT ERRORS ({err_count} consecutive): \"{err_msg}\"")
                                                logger.warning("Naukri server rate limit or repetitive errors encountered. Halting to protect account.")
                                                logger.warning(f"Total jobs applied today: {total_applied}.")
                                                logger.warning(f"{'!' * 70}\n")
                                                raise NaukriDailyLimitReached(err_msg)
                                            else:
                                                backoff_sec = 45 if err_count == 1 else 90
                                                logger.warning(f"  -> Adaptive cooldown: pausing for {backoff_sec}s to let server rate limits clear...")
                                                time.sleep(backoff_sec)
                                                logger.warning("  Skipping this specific job and continuing search...")
                                                continue

                                if applied_successfully:
                                    error_tracker["consecutive_transient_errors"] = 0
                                    total_applied += 1
                                    applied_set.add(job_id)
                                    record_applied_job(job_id, title, company, job_loc, job_url, status="Applied (Naukri)")
                                    applied_in_run.append({
                                        "title": title,
                                        "company": company,
                                        "location": job_loc,
                                        "url": job_url,
                                    })
                                    logger.info(f"  ★ SUCCESS ({total_applied}/{max_apps}): Applied to {title} | {company}")

                                    # Periodic Candidate Break: every 4-5 applications, take a human-like pause (60-90s)
                                    if total_applied % 4 == 0 and total_applied < max_apps:
                                        break_pause = round(random.uniform(60, 95), 1)
                                        logger.info(f"  ☕ Candidate review break ({total_applied} applied): taking a human-like pause for {break_pause}s...")
                                        time.sleep(break_pause)
                                    else:
                                        # Humanized randomized jitter around pause_sec
                                        actual_delay = max(5.0, round(random.uniform(pause_sec * 0.9, pause_sec * 1.5), 1))
                                        logger.info(f"  Pacing delay: waiting {actual_delay}s before next job...")
                                        time.sleep(actual_delay)
                                else:
                                    logger.info("  Could not complete application (unsupported form / external).")
                                    applied_set.add(job_id)
                    except NaukriDailyLimitReached:
                        raise
                    except Exception as e:
                        logger.warning(f"  Error applying to job: {e}")
                    finally:
                        # Close the job tab and return to search results
                        try:
                            driver.close()
                            driver.switch_to.window(original_window)
                        except Exception:
                            pass

    return total_applied


def count_applied_today() -> int:
    """Counts how many jobs were successfully applied today in applied_jobs.csv."""
    if not os.path.isfile(APPLIED_JOBS_CSV):
        return 0
    today_str = datetime.now().strftime("%Y-%m-%d")
    count = 0
    try:
        with open(APPLIED_JOBS_CSV, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                dt = (row.get("Date") or "").strip()
                st = (row.get("Status") or "").strip().lower()
                if dt.startswith(today_str) and "applied" in st and not any(neg in st for neg in ["skipped", "external", "already"]):
                    count += 1
    except Exception:
        pass
    return count


def count_applied_in_last_24_hours() -> int:
    """Counts how many jobs were successfully applied in the last 24 hours in applied_jobs.csv."""
    if not os.path.isfile(APPLIED_JOBS_CSV):
        return 0
    now = datetime.now()
    cutoff = now - timedelta(hours=24)
    count = 0
    try:
        with open(APPLIED_JOBS_CSV, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                dt_str = (row.get("Date") or "").strip()
                st = (row.get("Status") or "").strip().lower()
                if "applied" in st and not any(neg in st for neg in ["skipped", "external", "already"]):
                    try:
                        if len(dt_str) >= 19:
                            dt = datetime.strptime(dt_str[:19], "%Y-%m-%d %H:%M:%S")
                        else:
                            dt = datetime.strptime(dt_str[:10], "%Y-%m-%d")
                        if dt >= cutoff:
                            count += 1
                    except Exception:
                        pass
    except Exception:
        pass
    return count



def format_and_log_run_summary(applied_in_run: list[dict], summary_file: str = RUN_SUMMARY_FILE) -> str:
    """
    Builds a clean tabular summary with job title, company, location, and clickable links
    for all jobs applied during the current run. Logs the table to console/log file and
    writes it to latest_run_summary.md.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    count = len(applied_in_run)

    md_lines = [
        "# 🚀 Naukri Auto Apply - Run Summary\n",
        f"- **Run Timestamp**: `{timestamp}`",
        f"- **Total Applications in this Run**: `{count}`\n",
    ]

    log_lines = [
        "\n" + "=" * 110,
        "                         NAUKRI AUTO APPLY - RUN SUMMARY",
        "=" * 110,
        f"Timestamp: {timestamp} | Applications in this Run: {count}\n",
    ]

    if not applied_in_run:
        no_job_msg = "No jobs were applied to in this run (either daily quota was reached or no eligible new jobs found)."
        md_lines.append(f"> [!NOTE]\n> {no_job_msg}\n")
        log_lines.append(f"  {no_job_msg}")
    else:
        # Markdown table for latest_run_summary.md
        md_lines.append("| # | Job Title | Company | Location | Job Link |")
        md_lines.append("|---|-----------|---------|----------|----------|")
        for idx, job in enumerate(applied_in_run, 1):
            title = str(job.get("title") or "N/A").replace("|", "-").strip()
            company = str(job.get("company") or "N/A").replace("|", "-").strip()
            loc = str(job.get("location") or "N/A").replace("|", "-").strip()
            url = str(job.get("url") or "#").strip()
            md_lines.append(f"| {idx} | {title} | {company} | {loc} | [Open on Naukri]({url}) |")

        # Terminal / Log table (readable columns)
        log_lines.append(f"{'#':<4} | {'Job Title':<32} | {'Company':<22} | {'Location':<18} | Job Link")
        log_lines.append("-" * 110)
        for idx, job in enumerate(applied_in_run, 1):
            t = str(job.get("title") or "N/A")[:30]
            c = str(job.get("company") or "N/A")[:20]
            l = str(job.get("location") or "N/A")[:16]
            u = str(job.get("url") or "#")
            log_lines.append(f"{idx:<4} | {t:<32} | {c:<22} | {l:<18} | {u}")

    # External jobs tracker reference
    try:
        from external_job_tracker import load_external_jobs, EXTERNAL_JOBS_MD
        ext_jobs = load_external_jobs()
        if ext_jobs:
            pending = sum(1 for j in ext_jobs if "pending" in (j.get("Status") or "").lower())
            md_lines.append(f"\n> 💡 **External Career Portal Jobs**: `{len(ext_jobs)}` opportunities tracked (`{pending}` pending) in [`external_jobs_tracker.md`](./external_jobs_tracker.md).\n")
            log_lines.append(f"External Portal Jobs: {len(ext_jobs)} tracked ({pending} pending) -> {EXTERNAL_JOBS_MD}")
    except Exception:
        pass

    log_lines.append("=" * 110)
    log_lines.append(f"Summary markdown file saved to: {summary_file}")
    log_lines.append("=" * 110 + "\n")

    summary_log_str = "\n".join(log_lines)
    logger.info(summary_log_str)

    md_content = "\n".join(md_lines)
    try:
        with open(summary_file, "w", encoding="utf-8") as f:
            f.write(md_content)
    except Exception as e:
        logger.warning(f"Could not write summary markdown file {summary_file}: {e}")

    return md_content


def apply_to_naukri_jobs(driver: WebDriver, config: dict) -> int:
    """
    Main job applier loop:
    1. First prioritizes Primary locations (Delhi NCR).
    2. If primary locations are exhausted and daily quota remains,
       automatically proceeds to Secondary Tech Hubs (Bengaluru, Hyderabad, Pune, Mumbai).
    """
    logger.info("==================================================")
    logger.info("   NAUKRI DATA ENGINEER AUTO APPLIER (MULTI-HUB)  ")
    logger.info("==================================================")

    search_cfg = config.get("search", {})
    settings = config.get("settings", {})
    primary_locations = search_cfg.get("locations", ["Gurgaon", "Noida", "Delhi / NCR"])
    fallback_locations = search_cfg.get("fallback_locations", ["Bengaluru", "Hyderabad", "Pune", "Mumbai"])
    max_apps = search_cfg.get("max_applications_per_run", 65)

    # 24-Hour Rolling Quota Safeguard
    daily_ceiling = settings.get("daily_application_ceiling", 45)
    applied_24h = count_applied_in_last_24_hours()
    logger.info(f"24-Hour Application Quota Monitor: {applied_24h}/{daily_ceiling} applications used in the last 24 hours.")
    if applied_24h >= daily_ceiling:
        logger.warning("\n" + "=" * 70)
        logger.warning(f"⚠️ NAUKRI 24-HOUR APPLICATION CEILING ACTIVE: {applied_24h}/{daily_ceiling} applications used in last 24h.")
        logger.warning("Naukri enforces strict 24-hour account rate limits (~40-50 apps/day on free accounts).")
        logger.warning("Pausing auto-apply to protect candidate account integrity and prevent temporary blocks.")
        logger.warning("=" * 70 + "\n")
        return applied_24h

    remaining_24h = daily_ceiling - applied_24h
    if max_apps > remaining_24h:
        logger.info(f"-> Capping target applications for this run from {max_apps} to {remaining_24h} to stay safely within 24-hour limit ({daily_ceiling}).")
        max_apps = remaining_24h

    # Build location stages: Primary first, Fallback second, Open/Pan-India third
    location_stages = [("Primary (Delhi NCR)", primary_locations)]
    if fallback_locations:
        location_stages.append(("Secondary Tech Hubs (Bengaluru, Hyderabad, Pune, Mumbai)", fallback_locations))
    location_stages.append(("Open / Pan-India (All Locations)", []))

    applied_set = load_applied_job_ids()
    backfill_external_jobs_from_applied_csv(config)
    total_applied = 0
    applied_in_run = []
    error_tracker = {"consecutive_transient_errors": 0}

    try:
        for stage_idx, (stage_name, stage_locations) in enumerate(location_stages, 1):
            if total_applied >= max_apps:
                break

            remaining = max_apps - total_applied
            logger.info("\n" + "#" * 70)
            logger.info(f"### [STAGE {stage_idx}/{len(location_stages)}] LOCATION: {stage_name} ###")
            logger.info(f"### Target Hubs: {stage_locations} | Applications: {total_applied}/{max_apps} (Quota Left: {remaining}) ###")
            logger.info("#" * 70)

            total_applied = search_and_apply_stage(
                driver=driver,
                config=config,
                stage_name=stage_name,
                stage_locations=stage_locations,
                applied_set=applied_set,
                total_applied=total_applied,
                max_apps=max_apps,
                applied_in_run=applied_in_run,
                error_tracker=error_tracker,
            )
    except NaukriDailyLimitReached as e:
        actual_today = count_applied_today()
        if actual_today > total_applied:
            total_applied = actual_today
        logger.warning("\n" + "=" * 60)
        logger.warning(f"⚠️ Bot paused: Naukri daily limit / rate limit active: {e}")
        logger.warning(f"Successfully recorded {total_applied} applications today before reaching the threshold.")
        logger.warning("=" * 60)
    finally:
        # Always output and save the tabular summary of jobs applied in this run
        format_and_log_run_summary(applied_in_run)
        try:
            from insights_generator import generate_insights_html
            generate_insights_html()
        except Exception as e:
            logger.debug(f"Could not auto-generate insights.html: {e}")

    actual_today = count_applied_today()
    final_count = max(total_applied, actual_today)
    logger.info("=" * 60)
    logger.info(f"Run Finished: Successfully applied to {len(applied_in_run)} jobs this run ({final_count} total recorded today).")
    logger.info("=" * 60)
    return final_count

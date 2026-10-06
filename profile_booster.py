import os
import json
import time
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

logger = logging.getLogger("NaukriBot")

INSIGHTS_JSON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "application_insights.json")


def engage_header_notifications(driver: WebDriver, max_taps: int = 2) -> int:
    """
    Opens the Naukri Header Notification Bell (/html/body/div[3]/div[2]/div[4]/button/span),
    locates the right-side notification drawer list (/html/body/div[3]/div[2]/div[4]/div/div[2]/div[2]/div[1]/div/div/ul),
    iterates through all notification items, scrolls and hovers to simulate candidate review,
    taps on recent notifications to open and read their details (marking them read and signaling active engagement),
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

            for idx, it in enumerate(items, 1):
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
                    logger.info(f"  [{idx}/{count}]{unread_tag} {text_snippet}")
                    time.sleep(0.3)
                except Exception:
                    continue

            # Tap on recent notifications (up to max_taps)
            num_to_tap = min(max_taps, count)
            for tap_idx in range(num_to_tap):
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
                    logger.info(f"  -> Tapping notification [{tap_idx+1}/{num_to_tap}]: \"{item_title}\"...")
                    driver.execute_script("arguments[0].click();", clickable)
                    time.sleep(3)
                    tapped_count += 1
                    target_url = getattr(driver, "current_url", "") or ""
                    logger.info(f"     ✓ Viewed notification update ({target_url[:65]})")

                    # Simulate reviewing the destination page
                    driver.execute_script("window.scrollBy({top: 250, behavior: 'smooth'});")
                    time.sleep(2)

                    # Return to homepage to tap the next or proceed
                    driver.get("https://www.naukri.com/mnjuser/homepage")
                    time.sleep(3)

                    if tap_idx < num_to_tap - 1:
                        # Re-open bell drawer for the next notification tap
                        btn = get_bell_button()
                        if btn:
                            driver.execute_script("arguments[0].click();", btn)
                            time.sleep(2)
                except Exception as tap_err:
                    logger.warning(f"  Could not tap notification {tap_idx+1}: {tap_err}")
                    driver.get("https://www.naukri.com/mnjuser/homepage")
                    time.sleep(2.5)

        logger.info(f"✓ Completed notification engagement: reviewed {count} alerts, tapped {tapped_count} recent updates.")

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
    max_cards_per_tab: int = 10,
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
    - If irrelevant: Clicks 'Hide', opens 'Tell Us Why', selects the specific mismatch
      reason ('Job role', 'Experience', 'Location', or 'Skills'), and submits feedback
      to actively train and sharpen Naukri's recommendation algorithm.
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

        candidate_exp = personals.get("total_experience_years", 3.5)
        min_exp = search_cfg.get("min_experience", 1)
        max_exp = search_cfg.get("max_experience", 6)
        max_stretch = search_cfg.get("max_experience_stretch", 1.5)
        bad_words = search_cfg.get("title_bad_words", [])
        mandatory_words = search_cfg.get("title_mandatory_words", [])
        target_locations = search_cfg.get("locations", []) + search_cfg.get("fallback_locations", [])

        applied_set = load_applied_job_ids()
        backfill_external_jobs_from_applied_csv(config)

        tabs_to_process = ["Applies", "Top Candidate", "Preferences", "You might like"]

        for tab_name in tabs_to_process:
            logger.info(f"\n>>> Processing Recommended Tab: \"{tab_name}\" <<<")
            tab_elems = driver.find_elements(
                By.XPATH,
                f"//div[contains(@class, 'tab-wrapper')]//div[contains(text(), '{tab_name}')] | "
                f"//div[contains(@class, 'tab-list-item') and contains(text(), '{tab_name}')]"
            )
            if tab_elems:
                driver.execute_script("arguments[0].click();", tab_elems[0])
                time.sleep(2.5)

            cards = driver.find_elements(By.XPATH, "//article[contains(@class, 'jobTuple')]")
            if not cards:
                logger.info(f"  No cards found under tab '{tab_name}'.")
                continue

            sample_cards = cards[:max_cards_per_tab]
            logger.info(f"  Evaluating {len(sample_cards)} card(s) under '{tab_name}'...")

            for card in sample_cards:
                try:
                    job_id = card.get_attribute("data-job-id") or ""
                    title_elem = card.find_elements(By.XPATH, ".//*[contains(@class, 'title')]")
                    title = title_elem[0].text.strip() if title_elem else "Unknown Title"

                    # Skip already hidden or undo state
                    card_text = card.text or ""
                    if "has been hidden" in card_text or "Undo" in card_text:
                        continue

                    company_elem = card.find_elements(By.XPATH, ".//*[contains(@class, 'subTitle') or contains(@class, 'company')]")
                    company = company_elem[0].text.strip().split("\n")[0] if company_elem else "Unknown Company"

                    # Extract exp and loc
                    exp_str = ""
                    job_loc = ""
                    detail_spans = card.find_elements(By.XPATH, ".//span[contains(@class, 'ellipsis') and contains(@class, 'valignM')]")
                    for s in detail_spans:
                        t = s.text.strip()
                        if not t:
                            continue
                        if "yr" in t.lower():
                            exp_str = t
                        elif any(c in t.lower() for c in ["lakh", "disclosed", "₹", "cr"]):
                            continue
                        else:
                            job_loc = t

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
                        # Mismatch: Hide and Submit Reason to train algorithm!
                        logger.info(f"  ✕ [Hide & Feedback] \"{title}\" at \"{company}\" [{exp_str}, {job_loc}] -> Reason: '{reason}'")
                        hide_and_submit_recommendation_reason(driver, card, reason=reason)
                        summary["hidden"] += 1
                        summary["reasons"][reason] = summary["reasons"].get(reason, 0) + 1
                        time.sleep(1)
                        continue
                    else:
                        # Match: Apply to this recommended job!
                        logger.info(f"  ★ [Recommended Match] \"{title}\" at \"{company}\" ({job_loc}) [{exp_str}]")

                        original_window = driver.current_window_handle
                        windows_before = set(driver.window_handles)
                        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", title_elem[0])
                        time.sleep(0.5)
                        driver.execute_script("arguments[0].click();", title_elem[0])
                        time.sleep(3)

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
                                                time.sleep(pause_sec)
                            except Exception as app_err:
                                logger.warning(f"    Error applying to recommended job: {app_err}")
                            finally:
                                try:
                                    driver.close()
                                    driver.switch_to.window(original_window)
                                    time.sleep(1)
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


def boost_profile(driver: WebDriver, config: dict) -> bool:
    """
    Refreshes the candidate's Naukri profile and platform engagement by:
    1. Re-uploading the resume PDF
    2. Touching the resume headline (updating 'Last Active / Last Updated' timestamp)
    3. Interacting with the Notification Bell drawer and activity feed (Button 1 & list)
    4. Opening Profile & Recruiter Menu Drawer -> Search Appearances (Button 2 & Link 2.1)
    5. Opening Profile & Recruiter Menu Drawer -> Recruiter Actions (Button 2 & Link 2.2)
    6. Sharing Interest in Recommended Early Access Roles
    7. Visiting Application History & scraping 'What may work for you' match insights
    """
    logger.info("==================================================")
    logger.info("  NAUKRI PROFILE BOOSTER & ENGAGEMENT SUITE       ")
    logger.info("==================================================")

    driver.get("https://www.naukri.com/mnjuser/profile")
    time.sleep(3)

    from resume_resolver import resolve_resume_path

    personals = config.get("personals", {})
    resume_path = resolve_resume_path(config)
    target_headline = personals.get("resume_headline", "").strip()

    resume_updated = False
    headline_updated = False

    # 1. Re-upload Resume PDF
    if resume_path and os.path.isfile(resume_path):
        logger.info(f"Re-uploading resume: {resume_path}...")
        try:
            file_inputs = driver.find_elements(By.XPATH, "//input[@id='attachCV' or @type='file']")
            if file_inputs:
                file_input = file_inputs[0]
                file_input.send_keys(os.path.abspath(resume_path))
                time.sleep(4)
                resume_updated = True
                logger.info("✓ Resume successfully uploaded and synced on Naukri!")
            else:
                logger.warning("Could not find resume file upload input on profile page.")
        except Exception as e:
            logger.warning(f"Error during resume upload: {e}")
    else:
        logger.warning(f"Resume path '{resume_path}' does not exist. Skipping resume upload.")

    # 2. Touch Resume Headline
    try:
        logger.info("Touching Resume Headline to refresh candidate activity...")
        edit_buttons = driver.find_elements(
            By.XPATH,
            "//div[contains(@class, 'resumeHeadline')]//span[contains(text(), 'edit') or contains(@class, 'edit') or contains(text(), 'Edit')] | "
            "//span[normalize-space()='Edit' and ancestor::div[contains(@class, 'resumeHeadline')]] | "
            "//div[contains(@class, 'resumeHeadline')]//*[@class and contains(@class, 'icon')]"
        )
        if edit_buttons:
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", edit_buttons[0])
            time.sleep(1)
            driver.execute_script("arguments[0].click();", edit_buttons[0])
            time.sleep(2)

            try:
                ta = WebDriverWait(driver, 6).until(
                    EC.visibility_of_element_located((
                        By.XPATH,
                        "//textarea[@id='resumeHeadlineTxt' or contains(@class, 'resumeHeadlineTxt') or contains(@class, 'headline')] | //form//textarea"
                    ))
                )
            except Exception:
                ta = None

            if ta:
                current_text = ta.get_attribute("value") or ""
                new_text = target_headline or current_text

                # Toggle trailing period to trigger dirty-state validation on Naukri
                if new_text.endswith("."):
                    new_text = new_text[:-1]
                else:
                    new_text = new_text + "."

                # Clear and send keys via both keyboard shortcuts and JS event dispatch for React
                ta.click()
                ta.send_keys(Keys.CONTROL + "a")
                ta.send_keys(Keys.BACKSPACE)
                ta.send_keys(new_text)
                time.sleep(0.5)

                driver.execute_script("""
                    var el = arguments[0];
                    el.value = arguments[1];
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                """, ta, new_text)
                time.sleep(1)

                # Find the visible SAVE button inside the active modal/drawer/form
                save_buttons = driver.find_elements(
                    By.XPATH,
                    "//form[@name='resumeHeadlineForm']//button[normalize-space()='Save' or contains(text(), 'Save')] | "
                    "//div[contains(@class, 'lightbox') or contains(@class, 'modal') or contains(@class, 'drawer') or contains(@class, 'resumeHeadline')]//button[normalize-space()='Save'] | "
                    "//button[normalize-space()='Save' and contains(@class, 'btn-dark-ot')]"
                )
                saved = False
                for btn in save_buttons:
                    if btn.is_displayed():
                        driver.execute_script("arguments[0].click();", btn)
                        saved = True
                        break

                if saved:
                    time.sleep(3)
                    headline_updated = True
                    logger.info("✓ Resume headline successfully updated and saved!")
                else:
                    logger.warning("Could not find visible Save button candidate in headline modal.")
            else:
                logger.warning("Could not find headline textarea.")
        else:
            logger.warning("Could not find headline edit button.")
    except Exception as e:
        logger.warning(f"Error during headline update: {e}")

    logger.info("--------------------------------------------------")
    if resume_updated or headline_updated:
        logger.info("★ SUCCESS: Profile freshness updated to 'TODAY'!")

    # 3. Notification Bell & Activity Feed Engagement (Button 1 & notification list)
    engage_header_notifications(driver)

    # 4. Recommended Jobs Optimization: Apply to Top Candidates / Train Algorithm via Auto-Hide
    optimize_and_apply_recommended_jobs(driver, config, max_cards_per_tab=10)

    # 5. Search Appearances & Keywords (Profile Drawer 2.1)
    engage_performance_and_search_appearances(driver)

    # 6. Recruiter Actions Engagement (Profile Drawer 2.2)
    engage_recruiter_actions(driver)

    # 7. Share Interest for Recommended Early Access Roles
    share_interest_early_access_roles(driver)

    # 8. Analyze Application History Match Insights
    analyze_application_history_insights(driver, max_tiles=8)
    try:
        from insights_generator import generate_insights_html
        generate_insights_html()
    except Exception as e:
        logger.debug(f"Could not update insights.html: {e}")

    logger.info("==================================================")
    logger.info("  PROFILE BOOSTER & ENGAGEMENT COMPLETED          ")
    logger.info("==================================================")
    return True

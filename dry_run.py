import os
import re
import json
import time
import urllib.parse
import logging
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import Select
import browser
from job_applier import (
    is_title_relevant,
    is_location_match,
    is_experience_suitable,
    extract_experience_from_card,
    extract_experience_from_page,
    find_naukri_apply_button,
)
from chatbot_handler import (
    find_drawer,
    is_real_questionnaire_drawer,
    get_latest_bot_question,
    get_question_for_field,
    get_valid_chips,
    get_visible_inputs,
    get_visible_selects,
    resolve_text_question,
    resolve_chip_choice,
    check_apply_success,
    close_drawer,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("DryRun")


def run_dry_run(max_cards: int = 15, actual_submit: bool = False):
    """
    Dry-run diagnostics tool:
    Inspects 10-20 live jobs on Naukri to verify:
    1. Card extraction (Title, Company, Location, Experience)
    2. 5-layer quality filters
    3. Job details page Apply button detection
    4. Side panel / questionnaire drawer widget discovery:
       - Identifies exact DOM classes & structure
       - Tests finding inputs, placeholders, labels, and resolved values
       - Tests finding chips, options, and radio buttons
       - Validates whether 1-click apply or drawer is triggered
    """
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    personals = config.get("personals", {})
    search_cfg = config.get("search", {})
    settings = config.get("settings", {})
    skills_exp = config.get("skills_experience", {})

    keyword = search_cfg.get("search_terms", ["Data Engineer"])[0]
    locations = search_cfg.get("locations", ["Gurgaon", "Noida", "Delhi / NCR"])
    exp = search_cfg.get("experience", 3)
    min_exp = search_cfg.get("min_experience", 1)
    max_exp = search_cfg.get("max_experience", 6)
    max_stretch = search_cfg.get("max_experience_stretch", 1.5)
    bad_words = search_cfg.get("title_bad_words", [])
    mandatory_words = search_cfg.get("title_mandatory_words", [])

    profile_dir = settings.get("chrome_profile_dir", "~/.naukri-bot-profile")
    headless = settings.get("headless", False)

    logger.info("=" * 70)
    logger.info("   NAUKRI BOT DRY-RUN & WIDGET DIAGNOSTIC INSPECTOR")
    logger.info(f"   Target: '{keyword}' in {locations} (Exp: {exp} YOE, Range: {min_exp}-{max_exp})")
    logger.info(f"   Inspection limit: {max_cards} job cards | Actual submit: {actual_submit}")
    logger.info("=" * 70)

    driver = browser.get_chrome_driver(profile_dir=profile_dir, headless=headless)

    summary_results = []

    try:
        browser.ensure_login(driver)

        loc_param = ", ".join(locations)
        freshness_days = search_cfg.get("freshness_days", 3)
        slug = re.sub(r'[^a-zA-Z0-9]+', '-', keyword.strip().lower()).strip('-')
        is_delhi_ncr = any(loc.lower() in ["gurgaon", "gurugram", "noida", "delhi / ncr", "delhi"] for loc in locations)
        if is_delhi_ncr:
            fresh_param = f"&jobAge={freshness_days}" if freshness_days else ""
            search_url = f"https://www.naukri.com/{slug}-jobs-in-delhi-ncr?experience={exp}{fresh_param}"
        else:
            query_params = {
                "k": keyword,
                "l": loc_param,
                "experience": str(exp),
            }
            if freshness_days:
                query_params["jobAge"] = str(freshness_days)
            search_url = f"https://www.naukri.com/jobs-in-india?{urllib.parse.urlencode(query_params)}"

        logger.info(f"Loading search URL: {search_url}")
        driver.get(search_url)
        time.sleep(4)

        if freshness_days and f"jobAge={freshness_days}" not in driver.current_url:
            try:
                fresh_opt = driver.find_elements(By.XPATH, f"//span[text()='Last {freshness_days} days'] | //label[contains(., 'Last {freshness_days} days')]")
                if fresh_opt and fresh_opt[0].is_displayed():
                    driver.execute_script("arguments[0].click();", fresh_opt[0])
                    time.sleep(3)
            except Exception:
                pass

        # Scrape cards
        job_cards = driver.find_elements(By.XPATH, "//div[contains(@class, 'srp-jobtuple-wrapper')]")
        if not job_cards:
            job_cards = driver.find_elements(
                By.XPATH,
                "//div[contains(@class, 'cust-job-tuple')] | //article[contains(@class, 'jobTuple')]"
            )

        logger.info(f"\nFound {len(job_cards)} job cards on search page.\n")

        inspected = 0
        original_window = driver.current_window_handle

        for idx, card in enumerate(job_cards[:max_cards], 1):
            report = {
                "idx": idx,
                "title": "",
                "company": "",
                "location": "",
                "experience": "",
                "status": "",
                "apply_type": "",
                "drawer_found": False,
                "widgets": [],
            }

            try:
                title_elem = card.find_element(By.XPATH, ".//a[contains(@class, 'title')]")
                report["title"] = title_elem.text.strip()
                job_url = title_elem.get_attribute("href") or ""
            except Exception:
                continue

            try:
                comp_elem = card.find_element(By.XPATH, ".//a[contains(@class, 'comp-name')] | .//span[contains(@class, 'comp-name')]")
                report["company"] = comp_elem.text.strip()
            except Exception:
                report["company"] = "Unknown"

            try:
                loc_elem = card.find_element(By.XPATH, ".//span[contains(@class, 'loc-wrap')] | .//span[contains(@class, 'loc')]")
                report["location"] = loc_elem.text.strip()
            except Exception:
                report["location"] = "Unknown"

            job_exp = extract_experience_from_card(card)
            report["experience"] = job_exp or "Not specified"

            logger.info(f"\n[{idx}/{max_cards}] INSPECTING CARD: \"{report['title']}\" at \"{report['company']}\"")
            logger.info(f"     Location: {report['location']} | Experience: {report['experience']}")

            # Filter checks
            if not is_title_relevant(report["title"], bad_words, mandatory_words):
                logger.info("     -> [FILTER] Rejected by Title filter (non-data engineering or blacklisted).")
                report["status"] = "Skipped (Title Filter)"
                summary_results.append(report)
                continue

            if job_exp:
                suitable, reason = is_experience_suitable(job_exp, exp, min_exp, max_exp, max_stretch)
                if not suitable:
                    logger.info(f"     -> [FILTER] Rejected by Experience filter: {reason}")
                    report["status"] = f"Skipped ({reason})"
                    summary_results.append(report)
                    continue

            if not is_location_match(report["location"], locations):
                logger.info(f"     -> [FILTER] Rejected by Location filter ({report['location']}).")
                report["status"] = "Skipped (Location Filter)"
                summary_results.append(report)
                continue

            if "applied" in card.text.lower():
                logger.info("     -> [FILTER] Card already marked 'Applied'.")
                report["status"] = "Already Applied (Card)"
                summary_results.append(report)
                continue

            logger.info("     -> [PASS] Card passed all filters! Opening details tab...")
            inspected += 1

            driver.execute_script("window.open(arguments[0], '_blank');", job_url)
            time.sleep(2.5)

            new_windows = [w for w in driver.window_handles if w != original_window]
            if not new_windows:
                report["status"] = "Failed to open tab"
                summary_results.append(report)
                continue

            driver.switch_to.window(new_windows[-1])
            time.sleep(2)

            try:
                # Check details page experience
                detail_exp = extract_experience_from_page(driver)
                if detail_exp:
                    logger.info(f"     Details page experience: \"{detail_exp}\"")
                    suitable, reason = is_experience_suitable(detail_exp, exp, min_exp, max_exp, max_stretch)
                    if not suitable:
                        logger.info(f"     -> [FILTER] Details page experience mismatch: {reason}")
                        report["status"] = f"Skipped Details Exp ({reason})"
                        continue

                # Locate Apply button
                apply_btn = find_naukri_apply_button(driver)
                if not apply_btn:
                    logger.info("     -> No Apply button found on page.")
                    report["status"] = "No Apply Button"
                    continue

                btn_text = (apply_btn.text or "").strip()
                btn_class = (apply_btn.get_attribute("class") or "").strip()
                btn_id = (apply_btn.get_attribute("id") or "").strip()
                logger.info(f"     Apply Button: Text=\"{btn_text}\" | ID=\"{btn_id}\" | Class=\"{btn_class[:40]}...\"")

                if "company site" in btn_text.lower():
                    logger.info("     -> Button is 'Apply on Company Site' (External application).")
                    report["status"] = "External (Company Site)"
                    report["apply_type"] = "External"
                    continue

                if "already applied" in btn_text.lower() or btn_text.lower() == "applied":
                    logger.info("     -> Already applied to this job.")
                    report["status"] = "Already Applied"
                    report["apply_type"] = "Already Applied"
                    continue

                # Test clicking Apply button
                logger.info(f"     -> Clicking '{btn_text}' to inspect application response...")
                driver.execute_script("arguments[0].click();", apply_btn)
                time.sleep(2.5)

                # 1. Check for Instant 1-Click Apply
                if check_apply_success(driver, apply_btn=apply_btn):
                    logger.info("     ★ SUCCESS: Instant 1-Click apply detected directly! (No side panel questions)")
                    report["status"] = "Success (1-Click Apply)"
                    report["apply_type"] = "1-Click Direct Apply"
                    continue

                # 2. Check for Questionnaire Drawer
                drawer = find_drawer(driver)
                if not drawer:
                    # Check if inside an iframe
                    iframes = driver.find_elements(By.TAG_NAME, "iframe")
                    for fr in iframes:
                        try:
                            if not fr.is_displayed():
                                continue
                            driver.switch_to.frame(fr)
                            sub = find_drawer(driver) or driver.find_element(By.TAG_NAME, "body")
                            if is_real_questionnaire_drawer(sub):
                                drawer = sub
                                logger.info("     -> Questionnaire detected INSIDE an IFRAME!")
                                break
                            driver.switch_to.default_content()
                        except Exception:
                            driver.switch_to.default_content()

                if drawer:
                    report["drawer_found"] = True
                    dr_tag = drawer.tag_name
                    dr_class = drawer.get_attribute("class") or ""
                    dr_id = drawer.get_attribute("id") or ""
                    logger.info(f"     -> Side Panel Drawer DETECTED! <{dr_tag}> ID='{dr_id}' Class='{dr_class[:50]}'")

                    # Inspect bot questions
                    bot_q = get_latest_bot_question(drawer)
                    if bot_q:
                        logger.info(f"     [Question Detected]: \"{bot_q}\"")

                    # Inspect inputs
                    inputs = get_visible_inputs(drawer)
                    logger.info(f"     [Inputs Found]: {len(inputs)} visible text/number inputs")
                    for inp_idx, inp in enumerate(inputs, 1):
                        inp_q = get_question_for_field(inp)
                        effective_q = bot_q if (bot_q and len(bot_q) > 5) else inp_q
                        answer = resolve_text_question(effective_q, personals, skills_exp)
                        ph = inp.get_attribute("placeholder") or inp.get_attribute("data-placeholder") or ""
                        val = inp.get_attribute("value") or inp.text or ""
                        logger.info(f"       Input #{inp_idx}: field_q='{effective_q[:40]}' | ph='{ph}' | current_val='{val}' => Would Fill: \"{answer}\"")
                        report["widgets"].append(f"Input: '{effective_q[:30]}' -> '{answer}'")

                    # Inspect chips
                    chips = get_valid_chips(drawer)
                    logger.info(f"     [Chips/Options Found]: {len(chips)} clickable pills")
                    if chips:
                        chip_texts = [(c.text or c.get_attribute("innerText") or "").strip() for c in chips]
                        logger.info(f"       Chip labels: {chip_texts}")
                        chosen_chip = resolve_chip_choice(bot_q, chips, personals)
                        if chosen_chip:
                            chosen_txt = (chosen_chip.text or chosen_chip.get_attribute("innerText") or "").strip()
                            logger.info(f"       => Would Select Chip: \"{chosen_txt}\"")
                            report["widgets"].append(f"Chip: '{chosen_txt}'")

                    # Inspect selects
                    selects = get_visible_selects(drawer)
                    logger.info(f"     [Selects Found]: {len(selects)} dropdowns")
                    for s_idx, sel in enumerate(selects, 1):
                        s_q = get_question_for_field(sel)
                        options = [o.text for o in Select(sel).options]
                        logger.info(f"       Select #{s_idx}: q='{s_q[:40]}' | options={options[:5]}")
                        report["widgets"].append(f"Select: '{s_q[:30]}'")

                    # Inspect Radios
                    radios = drawer.find_elements(By.XPATH, ".//input[@type='radio']")
                    logger.info(f"     [Radio Buttons Found]: {len(radios)} radios")

                    # Inspect Submit/Save button
                    sub_btn = drawer.find_elements(By.XPATH, ".//div[contains(@class, 'sendMsg')] | .//div[contains(@class, 'send')] | .//button[contains(translate(., 'APPLY', 'apply'), 'apply') or contains(translate(., 'SUBMIT', 'submit'), 'submit') or contains(translate(., 'SAVE', 'save'), 'save')]")
                    if sub_btn:
                        btn_lbl = (sub_btn[0].text or sub_btn[0].get_attribute("innerText") or "").strip()
                        logger.info(f"     [Submit/Save Button]: Found '{btn_lbl}'")

                    report["status"] = "Drawer Inspected Successfully"
                    report["apply_type"] = "Questionnaire Side Panel"

                    if not actual_submit:
                        logger.info("     -> [DRY-RUN] Skipping final submit. Closing drawer...")
                        close_drawer(driver)
                else:
                    time.sleep(1.5)
                    if check_apply_success(driver, apply_btn=apply_btn):
                        logger.info("     ★ SUCCESS: 1-Click apply confirmed on re-check!")
                        report["status"] = "Success (1-Click Apply on re-check)"
                        report["apply_type"] = "1-Click Direct Apply"
                    else:
                        logger.info("     -> No drawer or success detected after clicking Apply.")
                        report["status"] = "Unconfirmed Application"
                        report["apply_type"] = "Unknown"

            except Exception as e:
                logger.warning(f"     Error during job page inspection: {e}")
                report["status"] = f"Error: {e}"
            finally:
                driver.close()
                driver.switch_to.window(original_window)
                summary_results.append(report)

        # Print Summary Table
        logger.info("\n" + "=" * 80)
        logger.info("                  DRY-RUN DIAGNOSTIC SUMMARY")
        logger.info("=" * 80)
        logger.info(f"{'#':<3} | {'Job Title':<30} | {'Company':<20} | {'Exp':<10} | {'Apply Type / Status':<25}")
        logger.info("-" * 80)
        for r in summary_results:
            title_short = (r['title'][:28] + "..") if len(r['title']) > 28 else r['title']
            comp_short = (r['company'][:18] + "..") if len(r['company']) > 18 else r['company']
            status_desc = r['apply_type'] or r['status']
            status_short = (status_desc[:23] + "..") if len(status_desc) > 23 else status_desc
            logger.info(f"{r['idx']:<3} | {title_short:<30} | {comp_short:<20} | {r['experience']:<10} | {status_short:<25}")
        logger.info("=" * 80)

    finally:
        driver.quit()
        logger.info("Browser closed. Dry run complete.")


if __name__ == "__main__":
    import sys
    limit = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 10
    run_dry_run(max_cards=limit, actual_submit=False)

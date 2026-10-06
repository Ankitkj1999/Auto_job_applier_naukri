import os
import json
import time
import urllib.parse
import logging
from selenium.webdriver.common.by import By
import browser
from job_applier import find_naukri_apply_button

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("InspectTenarai")

config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
with open(config_path, "r", encoding="utf-8") as f:
    config = json.load(f)

settings = config.get("settings", {})
profile_dir = settings.get("chrome_profile_dir", "~/.naukri-bot-profile")

driver = browser.get_chrome_driver(profile_dir=profile_dir, headless=False)

try:
    browser.ensure_login(driver)

    search_url = "https://www.naukri.com/jobs-in-india?k=Data+Engineer&l=Gurgaon%2C+Noida%2C+Delhi+%2F+NCR&experience=3"
    driver.get(search_url)
    time.sleep(4)

    job_cards = driver.find_elements(By.XPATH, "//div[contains(@class, 'srp-jobtuple-wrapper')]")
    logger.info(f"Found {len(job_cards)} cards.")

    target_card = None
    for card in job_cards:
        if "tenarai" in card.text.lower() or "easyrewardz" in card.text.lower() or "firstcall" in card.text.lower():
            target_card = card
            break

    if not target_card:
        logger.info("Tenarai/Easyrewardz card not found in first pass, picking first direct Apply card.")
        for card in job_cards:
            if "company site" not in card.text.lower() and "applied" not in card.text.lower():
                target_card = card
                break

    title_elem = target_card.find_element(By.XPATH, ".//a[contains(@class, 'title')]")
    title = title_elem.text.strip()
    job_url = title_elem.get_attribute("href")
    logger.info(f"Selected Job: {title} ({job_url})")

    original_window = driver.current_window_handle
    driver.execute_script("window.open(arguments[0], '_blank');", job_url)
    time.sleep(3)

    new_windows = [w for w in driver.window_handles if w != original_window]
    driver.switch_to.window(new_windows[-1])
    time.sleep(3)

    apply_btn = find_naukri_apply_button(driver)
    logger.info(f"Apply Button: text='{apply_btn.text}' | id='{apply_btn.get_attribute('id')}' | class='{apply_btn.get_attribute('class')}'")

    # Record DOM state before click
    before_windows = set(driver.window_handles)

    logger.info("Clicking Apply button...")
    driver.execute_script("arguments[0].click();", apply_btn)
    time.sleep(3)

    # Check if a new tab or window opened
    after_windows = set(driver.window_handles)
    diff_windows = after_windows - before_windows
    if diff_windows:
        logger.info(f"NEW WINDOW/TAB OPENED: {diff_windows}")

    # Check URL
    logger.info(f"Current URL after click: {driver.current_url}")

    # Screenshot
    ss_path = "/home/ankit/.gemini/antigravity-cli/brain/c5810246-7d62-4e28-a522-909c60a69155/apply_clicked.png"
    driver.save_screenshot(ss_path)
    logger.info(f"Saved screenshot to {ss_path}")

    # Inspect all visible elements on page
    logger.info("--- INSPECTING ALL VISIBLE DIALOGS / DRAWERS / MODALS / OVERLAYS ---")
    overlays = driver.find_elements(
        By.XPATH,
        "//div[contains(@class, 'drawer') or contains(@class, 'modal') or contains(@class, 'popup') or contains(@class, 'layer') or contains(@class, 'dialog') or contains(@class, 'overlay') or contains(@class, 'chat') or contains(@class, 'apply') or @role='dialog']"
    )
    for idx, ov in enumerate(overlays):
        try:
            if ov.is_displayed():
                cl = ov.get_attribute("class") or ""
                tid = ov.get_attribute("id") or ""
                tag = ov.tag_name
                txt = ov.text.strip().replace("\n", " ")[:100]
                logger.info(f"Visible Overlay #{idx}: <{tag}> id='{tid}' class='{cl}' | text='{txt}'")
        except Exception:
            pass

    logger.info("--- INSPECTING ALL VISIBLE INPUTS / BUTTONS ---")
    all_inputs = driver.find_elements(By.XPATH, "//input | //textarea | //select")
    for idx, inp in enumerate(all_inputs):
        try:
            if inp.is_displayed():
                itype = inp.get_attribute("type") or "text"
                iname = inp.get_attribute("name") or ""
                iid = inp.get_attribute("id") or ""
                iph = inp.get_attribute("placeholder") or ""
                ival = inp.get_attribute("value") or ""
                logger.info(f"Visible Input #{idx}: tag='{inp.tag_name}' type='{itype}' name='{iname}' id='{iid}' ph='{iph}' val='{ival}'")
        except Exception:
            pass

    logger.info("--- INSPECTING ALL IFRAMES ---")
    iframes = driver.find_elements(By.TAG_NAME, "iframe")
    for idx, fr in enumerate(iframes):
        try:
            src = fr.get_attribute("src") or ""
            f_id = fr.get_attribute("id") or ""
            f_name = fr.get_attribute("name") or ""
            logger.info(f"Iframe #{idx}: id='{f_id}' name='{f_name}' src='{src[:60]}' displayed={fr.is_displayed()}")
        except Exception:
            pass

    time.sleep(2)
finally:
    driver.quit()
    logger.info("Done inspecting.")

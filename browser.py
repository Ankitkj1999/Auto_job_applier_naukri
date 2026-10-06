import os
import sys
import time
import logging
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

logger = logging.getLogger("NaukriBot")


def get_chrome_driver(profile_dir: str = "~/.naukri-bot-profile", headless: bool = False) -> webdriver.Chrome:
    """
    Initializes a Chrome browser instance with a dedicated user data directory
    and anti-detection settings.
    """
    expanded_profile = os.path.expanduser(profile_dir)
    os.makedirs(expanded_profile, exist_ok=True)

    options = Options()
    options.add_argument(f"--user-data-dir={expanded_profile}")
    options.add_argument("--profile-directory=Default")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    user_agent = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    )
    options.add_argument(f"user-agent={user_agent}")

    if headless:
        options.add_argument("--headless=new")
        options.add_argument("--window-size=1920,1080")
    else:
        options.add_argument("--start-maximized")

    # Launch Chrome (Selenium 4.10+ handles driver management automatically)
    try:
        driver = webdriver.Chrome(options=options)
    except Exception as e:
        logger.warning(f"Native Chrome launch failed ({e}), falling back to ChromeDriverManager...")
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)

    # Remove navigator.webdriver flag
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"},
    )

    return driver


def wait_for_cloudflare(driver: webdriver.Chrome, timeout: int = 120) -> bool:
    """
    Detects Cloudflare Turnstile / verification challenge.
    Pauses, alerts the user, and waits until the challenge is solved or disappears.
    """
    def is_cf_active():
        try:
            title = (driver.title or "").lower()
            if any(t in title for t in ["just a moment", "attention required", "security check", "challenge"]):
                return True
            cf_elements = driver.find_elements(
                By.XPATH,
                "//iframe[contains(@src, 'cloudflare') or contains(@src, 'turnstile') or contains(@src, 'challenge')] | "
                "//div[@id='challenge-stage' or @id='challenge-running'] | "
                "//div[contains(@class, 'cf-turnstile')] | "
                "//div[@id='turnstile-wrapper'] | "
                "//span[contains(text(), 'Verify you are human')]"
            )
            if cf_elements and any(e.is_displayed() for e in cf_elements):
                return True
        except Exception:
            pass
        return False

    if not is_cf_active():
        return True

    logger.warning("\n" + "=" * 70)
    logger.warning(">>> SECURITY VERIFICATION / CLOUDFLARE DETECTED <<<")
    logger.warning("Please check the Chrome window and complete verification ('Verify you are human').")
    logger.warning(f"The bot is waiting up to {timeout} seconds for the challenge to pass...")
    logger.warning("=" * 70 + "\n")

    start = time.time()
    while time.time() - start < timeout:
        time.sleep(2)
        if not is_cf_active():
            time.sleep(2)
            logger.info("✓ Verification passed! Resuming...")
            return True

    logger.error("Security verification timed out.")
    return False


def is_logged_in(driver: webdriver.Chrome) -> bool:
    """Checks whether the browser currently has an active Naukri session."""
    driver.get("https://www.naukri.com/mnjuser/profile")
    wait_for_cloudflare(driver)
    time.sleep(2)
    current_url = driver.current_url.lower()
    if "nlogin" in current_url or "login" in current_url:
        return False
    # Check for profile elements
    try:
        driver.find_element(By.XPATH, "//div[contains(@class, 'user-profile') or contains(@class, 'profile-layer') or contains(@class, 'fullname')]")
        return True
    except Exception:
        # Check if URL stayed on profile or homepage
        return "mnjuser" in current_url or "mynaukri" in current_url


def ensure_login(driver: webdriver.Chrome) -> None:
    """
    Checks login status; if not logged in, opens the login page and
    waits for the user to complete OTP/password login once.
    """
    if is_logged_in(driver):
        logger.info("✓ Already logged in to Naukri!")
        return

    logger.warning("! Not logged in to Naukri.")
    logger.info("Opening Naukri login page. Please log in (with OTP, Password, or Google)...")
    driver.get("https://www.naukri.com/nlogin/login")
    wait_for_cloudflare(driver)

    # Wait up to 300 seconds for the user to complete manual login
    print("\n" + "=" * 70)
    print(">>> PLEASE LOG IN TO NAUKRI IN THE BROWSER WINDOW <<<")
    print("Complete your login (Password / OTP / Google).")
    print("Once logged in, your session is saved in ~/.naukri-bot-profile permanently!")
    print("=" * 70 + "\n")

    max_wait = 300
    start_time = time.time()
    while time.time() - start_time < max_wait:
        time.sleep(3)
        current = driver.current_url.lower()
        if "mnjuser" in current or ("nlogin" not in current and "login" not in current and "naukri.com" in current):
            try:
                driver.get("https://www.naukri.com/mnjuser/profile")
                time.sleep(3)
                if is_logged_in(driver):
                    logger.info("✓ Login successfully detected and verified!")
                    return
            except Exception:
                pass

    raise TimeoutError("Login wait timed out. Please run the script again and complete login.")

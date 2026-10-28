import os
import sys
import time
import random
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

    # Set page load strategy to 'eager' so navigation returns as soon as DOMContentLoaded fires
    # instead of hanging indefinitely on slow analytics, trackers, or ad scripts
    options.page_load_strategy = "eager"

    # Launch Chrome (Fast launch: prefer local cached driver over 300s Selenium Manager network timeout)
    try:
        os.environ.setdefault("SE_OFFLINE", "true")
        driver = webdriver.Chrome(options=options)
    except Exception:
        os.environ.pop("SE_OFFLINE", None)
        try:
            driver = webdriver.Chrome(options=options)
        except Exception as e:
            logger.warning(f"Native Chrome launch failed ({e}), falling back to ChromeDriverManager...")
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=options)

    # Set explicit page load timeout to prevent indefinite hangs
    driver.set_page_load_timeout(45)

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


def human_dwell(min_sec: float = 2.0, max_sec: float = 5.0, message: str = ""):
    """Simulates realistic human reading or thinking pauses."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    delay = round(random.uniform(min_sec, max_sec), 2)
    if message:
        logger.debug(f"{message} (dwelling {delay}s)")
    time.sleep(delay)


def human_scroll(driver, distance: int = 300, steps: int = 3):
    """Smoothly scrolls page in fractional steps to simulate human trackpad or mouse wheel."""
    if not driver:
        return
    if os.environ.get("PYTEST_CURRENT_TEST"):
        try:
            driver.execute_script(f"window.scrollBy(0, {distance});")
        except Exception:
            pass
        return

    step_dist = distance / max(1, steps)
    for _ in range(steps):
        try:
            driver.execute_script(f"window.scrollBy({{top: {step_dist}, behavior: 'smooth'}});")
            time.sleep(random.uniform(0.15, 0.35))
        except Exception:
            break


def human_click(driver, element, pause_before: float = None, pause_after: float = None) -> bool:
    """
    Simulates a human-like mouse interaction:
    1. Smoothly scrolls the element into view.
    2. Pauses naturally as a user aiming their cursor.
    3. Uses native ActionChains to hover and click (trusted pointer event).
    4. Falls back to element.click() and driver.execute_script if obstructed.
    5. Pauses after clicking to simulate user observing the action's result.
    """
    is_test = bool(os.environ.get("PYTEST_CURRENT_TEST"))
    if pause_before is None:
        pause_before = 0.01 if is_test else random.uniform(0.5, 1.2)
    if pause_after is None:
        pause_after = 0.01 if is_test else random.uniform(0.8, 1.8)

    try:
        driver.execute_script("arguments[0].scrollIntoView({block: 'center', behavior: 'smooth'});", element)
    except Exception:
        pass

    if pause_before > 0:
        time.sleep(pause_before)

    clicked = False
    try:
        from selenium.webdriver.common.action_chains import ActionChains
        ActionChains(driver).move_to_element(element).pause(0.01 if is_test else random.uniform(0.2, 0.4)).click().perform()
        clicked = True
    except Exception:
        try:
            element.click()
            clicked = True
        except Exception:
            try:
                driver.execute_script("arguments[0].click();", element)
                clicked = True
            except Exception:
                pass

    if pause_after > 0:
        time.sleep(pause_after)

    return clicked


def human_type_into_element(driver, element, text: str, clear_first: bool = True) -> bool:
    """
    Types text into an input or textarea element with human-like typing cadence,
    natural inter-key latencies, pauses at spaces and punctuation, and dispatches
    appropriate browser events to ensure React / form state recognition without instant pasting.
    """
    is_test = bool(os.environ.get("PYTEST_CURRENT_TEST"))
    from selenium.webdriver.common.keys import Keys

    # Focus element
    try:
        from selenium.webdriver.common.action_chains import ActionChains
        ActionChains(driver).move_to_element(element).click().perform()
    except Exception:
        try:
            element.click()
        except Exception:
            pass

    if not is_test:
        time.sleep(random.uniform(0.3, 0.7))

    # Clear existing content if requested
    if clear_first:
        try:
            element.send_keys(Keys.CONTROL + "a")
            if not is_test:
                time.sleep(random.uniform(0.15, 0.3))
            element.send_keys(Keys.BACKSPACE)
            if not is_test:
                time.sleep(random.uniform(0.2, 0.4))
        except Exception:
            try:
                element.clear()
            except Exception:
                pass

    if is_test:
        try:
            element.send_keys(text)
        except Exception:
            pass
    else:
        # Realistic human typing cadence
        for idx, char in enumerate(text):
            try:
                element.send_keys(char)
            except Exception:
                break

            delay = random.uniform(0.025, 0.075)
            if char in " \t":
                delay = random.uniform(0.08, 0.18)
            elif char in ",.;:-/|":
                delay = random.uniform(0.18, 0.38)

            # Micro-hesitation every ~35-45 characters
            if idx > 0 and idx % random.randint(32, 48) == 0:
                delay += random.uniform(0.25, 0.50)

            time.sleep(delay)

    # Dispatch React / Vue synthetic change events to ensure state sync
    try:
        driver.execute_script("""
            var el = arguments[0];
            var val = arguments[1];
            if (el.value !== val) {
                el.value = val;
            }
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
        """, element, text)
    except Exception:
        pass

    # Human proofreading pause after typing
    if not is_test:
        time.sleep(random.uniform(2.0, 3.8))

    return True


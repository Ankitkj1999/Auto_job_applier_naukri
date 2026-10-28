import time
import os
import re
import json
import logging
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support.ui import Select

logger = logging.getLogger("NaukriBot")

SCREENING_QUESTIONS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screening_questions.json")


def record_screening_question(
    job_title: str,
    company: str,
    question: str,
    field_type: str,
    answer: str,
    options: list = None,
    status: str = "answered",
    filepath: str = SCREENING_QUESTIONS_PATH
) -> None:
    """
    Persistently logs screening questions, available options, and candidate responses
    to screening_questions.json to expand domain intelligence and improve automated answers.
    """
    if not question:
        return
    try:
        data = []
        if os.path.exists(filepath):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content:
                        loaded = json.loads(content)
                        if isinstance(loaded, list):
                            data = loaded
            except Exception as e:
                logger.debug(f"Failed to load existing {filepath}: {e}")
                data = []

        entry = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "job_title": job_title or "Unknown Job",
            "company": company or "Unknown Company",
            "question": question.strip(),
            "field_type": field_type,
            "answer": str(answer),
            "options": options or [],
            "status": status
        }
        data.append(entry)

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.debug(f"Failed to record screening question: {e}")


def sanitize_whole_number(val: str | int | float, min_val: int = 0, max_val: int = 99, default: int = 3) -> str:
    """
    Sanitizes any input value into a clean whole integer string between min_val and max_val (default 0-99).
    Converts floats (e.g. 3.5 -> 3), text with units (e.g. '30 Days' -> '30', '13 LPA' -> '13'),
    and enforces boundaries.
    """
    if val is None:
        return str(default)

    val_str = str(val).strip()
    if not val_str:
        return str(default)

    # If purely digits, clamp to bounds
    if val_str.isdigit():
        num = int(val_str)
        return str(max(min_val, min(max_val, num)))

    # Extract number (integer or float with optional negative sign)
    m = re.search(r'(-?\d+(?:\.\d+)?)', val_str)
    if m:
        try:
            num = int(float(m.group(1)))
            return str(max(min_val, min(max_val, num)))
        except (ValueError, TypeError):
            pass

    return str(default)


def is_whole_number_required(input_elem=None, question: str = "", drawer=None) -> bool:
    """
    Checks if an input element, question, or drawer validation state requires a whole number between 0 and 99.
    Checks input type, attributes, placeholder, aria-label, question text, and on-screen validation errors.
    Explicitly excludes date of birth, dates, ID cards, names, emails, and locations.
    """
    q_low = (question or "").lower()
    # Explicit exclusions: Dates, DOB, ID cards, names, emails, locations should NEVER be constrained to 0-99
    if any(k in q_low for k in [
        "dob", "date of birth", "birth date", "birthdate", "select your date of birth",
        "date", "day of birth", "pan", "aadhar", "aadhaar", "passport",
        "email", "phone", "mobile", "name", "city", "location", "lwd", "last working day"
    ]):
        return False

    if any(k in q_low for k in ["whole number", "between 0 and 99", "0-99", "0 to 99", "0 and 99"]):
        return True

    if input_elem:
        try:
            inp_type = (input_elem.get_attribute("type") or "").lower()
            if inp_type in ["date", "datetime", "datetime-local"]:
                return False
            ph = (input_elem.get_attribute("placeholder") or "").lower()
            aria = (input_elem.get_attribute("aria-label") or "").lower()
            name = (input_elem.get_attribute("name") or "").lower()
            cls = (input_elem.get_attribute("class") or "").lower()
            combined_attr = f"{ph} {aria} {name} {cls}"
            if any(k in combined_attr for k in ["date", "dob", "birth", "dd/mm", "dd-mm", "yyyy", "day", "month"]):
                return False

            if inp_type in ["number", "tel"]:
                return True
            inp_step = input_elem.get_attribute("step")
            if inp_step == "1":
                return True
            if any(k in combined_attr for k in ["whole number", "0-99", "between 0 and 99", "years", "months", "ctc", "total experience"]):
                return True
        except Exception:
            pass

    if drawer:
        try:
            err_elems = drawer.find_elements(
                By.XPATH,
                ".//*[contains(@class, 'err') or contains(@class, 'error') or contains(@class, 'warning')]"
            )
            for err in err_elems:
                if err.is_displayed():
                    err_txt = (err.text or "").lower()
                    if any(k in err_txt for k in ["whole number", "between 0 and 99", "valid number", "0 to 99", "0-99"]):
                        return True
        except Exception:
            pass

    return False



def is_real_questionnaire_drawer(drawer) -> bool:
    """
    Verifies that the element is an actual application questionnaire.
    Checks for questions, contenteditable inputs, textareas, chips, or save/submit buttons.
    """
    if not drawer:
        return False
    try:
        if not drawer.is_displayed():
            return False
        # Must have questions, inputs, chips, or submit/apply button
        has_inputs = bool(drawer.find_elements(
            By.XPATH,
            ".//div[@contenteditable='true'] | .//input[not(@type='hidden') and not(@type='checkbox')] | .//textarea | .//select"
        ))
        has_chips = bool(drawer.find_elements(
            By.XPATH,
            ".//div[contains(@class, 'chip')] | .//button[contains(@class, 'chip')] | .//div[contains(@class, 'options')] | .//label[contains(@class, 'radio')] | .//label[contains(@class, 'ssrc__label')] | .//div[contains(@class, 'singleselect')]"
        ))
        has_questions = bool(drawer.find_elements(
            By.XPATH,
            ".//div[contains(@class, 'botMsg')] | .//div[contains(@class, 'bot-msg')] | .//div[contains(@class, 'msg-text')] | .//div[contains(@class, 'question')] | .//li[contains(@class, 'botItem')]"
        ))
        has_submit = bool(drawer.find_elements(
            By.XPATH,
            ".//div[contains(@class, 'sendMsg')] | .//div[contains(@class, 'send')] | .//button"
        ))
        return has_inputs or has_chips or has_questions or has_submit
    except Exception:
        return False


def find_drawer(driver: WebDriver):
    """
    Finds the active slide-in application side panel / questionnaire drawer.
    Matches Naukri's exact chatbot_Drawer, _chatBotContainer, and apply-drawer containers.
    Returns the WebElement if visible and contains real questionnaire elements, else None.
    """
    drawer_locators = [
        "//div[contains(@class, 'chatbot_Drawer') and contains(@class, 'chatbot_right')]",
        "//div[contains(@class, 'chatbot_Drawer')]",
        "//div[contains(@class, '_chatBotContainer')]",
        "//div[contains(@class, 'apply-drawer') or contains(@class, 'applyDrawer')]",
        "//div[contains(@class, 'drawer-wrapper') and not(contains(@class, 'chatbot_Nav'))]",
        "//div[contains(@class, 'apply-message-box')]",
        "//div[contains(@class, 'chat-container')]",
        "//div[contains(@class, 'bot-container')]",
        "//div[contains(@id, 'apply-drawer')]",
        "//div[contains(@class, 'styles_drawer')]",
        "//section[contains(@class, 'chatbot')]",
        "//div[contains(@class, 'side-drawer')]",
        "//div[contains(@class, 'side-panel')]",
        "//div[@role='dialog']",
    ]

    for loc in drawer_locators:
        try:
            elems = driver.find_elements(By.XPATH, loc)
            for elem in elems:
                if elem.is_displayed() and is_real_questionnaire_drawer(elem):
                    return elem
        except Exception:
            continue

    # Dynamic fallback: look for any visible container with contenteditable or questionnaire input
    try:
        candidates = driver.find_elements(
            By.XPATH,
            "//div[not(ancestor::header) and not(ancestor::nav)]//div[@contenteditable='true'] | "
            "//div[not(ancestor::header) and not(ancestor::nav)]//input[not(@type='hidden') and not(@type='checkbox') and not(@type='radio')] | "
            "//div[not(ancestor::header) and not(ancestor::nav)]//textarea"
        )
        for cand in candidates:
            if cand.is_displayed():
                try:
                    container = cand.find_element(
                        By.XPATH,
                        "./ancestor::div[contains(@class, 'Drawer') or contains(@class, 'drawer') or contains(@class, 'modal') or contains(@class, 'container') or contains(@class, 'box') or contains(@class, 'layer') or @role='dialog'][1]"
                    )
                    if container.is_displayed() and is_real_questionnaire_drawer(container):
                        return container
                except Exception:
                    pass
    except Exception:
        pass

    return None


def get_latest_bot_question(drawer) -> str:
    """Extracts the latest question or message text from the bot inside the drawer."""
    try:
        bot_msgs = drawer.find_elements(
            By.XPATH,
            ".//div[contains(@class, 'botMsg')]//span | "
            ".//div[contains(@class, 'botMsg')] | "
            ".//div[contains(@class, 'bot-msg')]//span | "
            ".//div[contains(@class, 'msg-text')] | "
            ".//div[contains(@class, 'question')] | "
            ".//li[contains(@class, 'botItem')]//span | "
            ".//div[contains(@class, 'chat-bubble')]"
        )
        for m in reversed(bot_msgs):
            if not m.is_displayed():
                continue
            txt = (m.text or m.get_attribute("innerText") or "").strip()
            if txt and len(txt) > 2:
                return txt
    except Exception:
        pass
    return ""


def get_question_for_field(elem) -> str:
    """Finds the question text associated with an individual form field."""
    try:
        ph = (elem.get_attribute("placeholder") or elem.get_attribute("data-placeholder") or "").strip()
        aria = (elem.get_attribute("aria-label") or "").strip()
        name = (elem.get_attribute("name") or "").strip()

        label_text = ""
        elem_id = elem.get_attribute("id")
        if elem_id:
            try:
                lbl = elem.find_element(By.XPATH, f"//label[@for='{elem_id}']")
                label_text = lbl.text.strip()
            except Exception:
                pass

        if not label_text:
            try:
                parent = elem.find_element(
                    By.XPATH,
                    "./ancestor::div[contains(@class, 'form') or contains(@class, 'field') or contains(@class, 'question') or contains(@class, 'row') or contains(@class, 'group') or contains(@class, 'wrap')][1]"
                )
                label_text = parent.text.strip()
            except Exception:
                pass

        combined = f"{label_text} {ph} {aria} {name}".strip()
        return combined if combined else "Experience"
    except Exception:
        return "Experience"


def get_label_for_radio(radio_elem) -> str:
    """Finds the label or text associated with a radio button."""
    try:
        parent = radio_elem.find_element(By.XPATH, "./parent::*")
        txt = parent.text.strip()
        if txt:
            return txt
        sibling = radio_elem.find_element(By.XPATH, "./following-sibling::*")
        return sibling.text.strip()
    except Exception:
        return ""


def get_question_for_chip(chip_elem) -> str:
    """Extracts question text associated with a chip or radio option container."""
    try:
        containers = chip_elem.find_elements(
            By.XPATH,
            "./ancestor::div[contains(@class, 'question') or contains(@class, 'field') or contains(@class, 'botMsg') or contains(@class, 'group') or contains(@class, 'chatbot_ListItem') or contains(@class, 'ssrc__radio')][1]"
        )
        if containers:
            q_elems = containers[0].find_elements(
                By.XPATH,
                ".//div[contains(@class, 'botMsg')] | .//div[contains(@class, 'question')] | .//div[contains(@class, 'title')] | .//span[contains(@class, 'botText')] | .//label[not(contains(@class, 'radio')) and not(contains(@class, 'chip'))]"
            )
            for qe in q_elems:
                txt = (qe.text or qe.get_attribute("innerText") or "").strip()
                if txt and len(txt) > 5 and not any(phrase in txt.lower() for phrase in ["skip this question", "skip question", "submit", "save", "next"]):
                    return txt
    except Exception:
        pass
    return ""


def get_valid_chips(drawer) -> list:
    """
    Finds all valid, visible, and non-empty clickable chips/options strictly inside the drawer.
    Guarantees that bot messages, greetings, background-page elements, and skip links are excluded.
    Supports Naukri's chip lists, quick replies, radio options, and ssrc__ radio widgets.
    """
    valid_chips = []
    try:
        chips = drawer.find_elements(
            By.XPATH,
            ".//li[contains(@class, 'chatbot_ListItem')]//div[contains(@class, 'chip')] | "
            ".//ul[contains(@class, 'chips')]//li | "
            ".//div[contains(@class, 'chips')]//span | "
            ".//div[contains(@class, 'chip')] | "
            ".//button[contains(@class, 'chip')] | "
            ".//li[contains(@class, 'chip')] | "
            ".//div[contains(@class, 'quick-replies')]//button | "
            ".//div[contains(@class, 'options')]//button | "
            ".//div[contains(@class, 'options')]//li | "
            ".//div[contains(@class, 'bot-options')]//li | "
            ".//div[contains(@class, 'bot-options')]//button | "
            ".//label[contains(@class, 'radio')] | "
            ".//label[contains(@class, 'chip')] | "
            ".//button[contains(@class, 'option')] | "
            ".//label[contains(@class, 'ssrc__label')] | "
            ".//div[contains(@class, 'ssrc__radio-btn-container')] | "
            ".//div[contains(@class, 'singleselect')]//label | "
            ".//div[contains(@class, 'singleselect')]//div[contains(@class, 'radio-btn')] | "
            ".//div[contains(@class, 'radio')]//label"
        )
        for c in chips:
            try:
                if not c.is_displayed():
                    continue
                # Exclude if inside botMsg, userMsg, or chat header
                is_msg = bool(c.find_elements(
                    By.XPATH,
                    "./ancestor::div[contains(@class, 'botMsg') or contains(@class, 'bot-msg') or contains(@class, 'userMsg') or contains(@class, 'msg-text')]"
                ))
                if is_msg:
                    continue

                # Exclude composite wrapper containers (which wrap multiple radio choices)
                cls = (c.get_attribute("class") or "").lower()
                if "singleselect-radiobutton" in cls and "container" in cls:
                    continue
                try:
                    if len(c.find_elements(By.XPATH, ".//input[@type='radio'] | .//label")) > 1:
                        continue
                except Exception:
                    pass

                txt = (c.text or c.get_attribute("innerText") or "").strip()
                # Exclude composite blocks where multiple options are grouped with newlines (e.g. "Currently serving\nPreviously served\nNever served")
                if "\n" in txt:
                    continue

                # Real chips and radio options (allowing up to 200 chars for descriptive options)
                if txt and len(txt) <= 200:
                    lower = txt.lower()
                    skip_phrases = [
                        "thank you", "kindly answer", "recruiter's question",
                        "showing interest", "upload resume", "do it later",
                        "skip this question", "skip question", "skip for now",
                        "try again"
                    ]
                    if not any(phrase in lower for phrase in skip_phrases) and lower != "skip":
                        valid_chips.append(c)
            except Exception:
                continue
    except Exception:
        pass
    return valid_chips


def get_visible_inputs(drawer) -> list:
    """Finds visible text, number, contenteditable, or textarea inputs strictly inside the drawer."""
    try:
        inputs = drawer.find_elements(
            By.XPATH,
            ".//div[@contenteditable='true'] | "
            ".//input[(@type='text' or @type='number' or not(@type)) and not(@type='hidden') and not(@type='radio') and not(@type='checkbox') and not(contains(@class, 'dob__input')) and not(@name='day') and not(@name='month') and not(@name='year')] | "
            ".//textarea"
        )
        return [i for i in inputs if i.is_displayed()]
    except Exception:
        return []


def get_visible_selects(drawer) -> list:
    """Finds visible dropdown selects strictly inside the drawer."""
    try:
        selects = drawer.find_elements(By.XPATH, ".//select")
        return [s for s in selects if s.is_displayed()]
    except Exception:
        return []


def find_drawer_button(drawer, keywords: list):
    """Finds a button or clickable send div inside drawer matching any of the specified keywords."""
    try:
        buttons = drawer.find_elements(
            By.XPATH,
            ".//div[contains(@class, 'sendMsg')] | "
            ".//div[contains(@class, 'send') and not(contains(@class, 'sendMsgbtn_container'))] | "
            ".//button | .//span[@role='button'] | .//div[@role='button'] | .//a[contains(@class, 'btn')]"
        )
        for btn in buttons:
            try:
                if not btn.is_displayed():
                    continue
                text = (btn.text or "").lower()
                cls = (btn.get_attribute("class") or "").lower()
                aria = (btn.get_attribute("aria-label") or "").lower()
                tid = (btn.get_attribute("id") or "").lower()
                combined = f"{text} {cls} {aria} {tid}"
                if any(k in combined for k in keywords):
                    return btn
            except Exception:
                continue
    except Exception:
        pass
    return None


def get_candidate_worked_companies(personals: dict) -> list:
    """Returns the list of companies the candidate has actually worked with."""
    if not isinstance(personals, dict):
        personals = {}
    companies = []
    for key in ["worked_companies", "past_companies", "previous_companies"]:
        val = personals.get(key)
        if isinstance(val, list):
            for c in val:
                c_str = str(c).strip()
                if c_str and c_str not in companies:
                    companies.append(c_str)
    current = str(personals.get("current_company", "")).strip()
    if current and current not in companies:
        companies.append(current)
    # Default candidate worked companies if not explicitly defined
    default_companies = ["Lemon Tree Hotels Limited", "Lemon Tree Hotels", "Zalon", "Techtonic", "Tekniko"]
    for dc in default_companies:
        if dc not in companies:
            companies.append(dc)
    return companies


def is_prior_company_question(question: str, skills_exp: dict = None) -> bool:
    """
    Detects if the question asks whether the candidate worked for / with / in a specific company,
    is an ex-employee, prior employee, former employee, applied earlier, cooling off, rehire, etc.
    Strictly distinguishes employer questions from technical tool/skill questions (e.g. DBT, Python).
    """
    q_low = (question or "").lower()

    # 1. Direct explicit employment / affiliation indicators
    if any(k in q_low for k in [
        "ex-employee", "ex employee", "ex - employee", "ex-",
        "former employee", "past employee", "previous employee", "prior employee",
        "prior employment", "past employment", "cooling off", "cooling-off", "cooling period",
        "rehire", "worked earlier", "applied earlier", "applied before",
        "previously applied", "previously employed",
        "interviewed with us", "interviewed earlier", "attended interview earlier",
        "worked with us", "worked for us", "worked at us",
        "emp id", "employee id"
    ]):
        return True

    # 2. Check if this is a technical skill question (e.g. "Have you worked with DBT?", "Have you worked in PySpark?")
    tech_skills = {
        "dbt", "python", "sql", "aws", "spark", "pyspark", "databricks", "etl", "data pipeline",
        "data warehouse", "data lake", "airflow", "docker", "postgresql", "mongodb", "redis",
        "big data", "redshift", "glue", "lambda", "kinesis", "looker", "gcp", "google",
        "data studio", "power bi", "tableau", "snowflake", "azure", "kafka",
        "data quality", "streaming", "streams", "j2ee", "pandas", "numpy", "scala",
        "kubernetes", "ci/cd", "rest api", "vertex ai", "pubsub", "hadoop", "hive",
        "oracle", "mysql", "git", "linux", "cloud composer", "teradata", "synapse"
    }
    if isinstance(skills_exp, dict):
        tech_skills.update(k.lower() for k in skills_exp.keys())

    is_about_tech = any(re.search(r'\b' + re.escape(tech) + r'\b', q_low) for tech in tech_skills)
    if is_about_tech and not any(k in q_low for k in ["earlier", "before", "previously", "past company", "ex-", "former"]):
        return False

    # 3. Work for/at/in/by company:
    if re.search(r'\b(worked\s+(for|at)|employed\s+(with|at|in|by))\b', q_low):
        return True

    # 4. "worked with <company> before/earlier/previously"
    if re.search(r'\bworked\s+with\b', q_low) and any(t in q_low for t in ["before", "earlier", "previously", "past", "prior"]):
        if not is_about_tech:
            return True

    # 5. "worked in / applied to"
    if "worked in / applied to" in q_low or "worked in/applied to" in q_low or "worked or applied" in q_low:
        return True

    # 6. Specific companies
    known_companies = ["cognizant", "wipro", "infosys", "tcs", "deloitte", "accenture", "capgemini", "hcl", "happiest minds", "lemon tree", "zalon", "techtonic", "tekniko"]
    if any(co in q_low for co in known_companies) and any(w in q_low for w in ["worked", "employed", "applied", "interviewed", "ex"]):
        return True

    return False


def is_candidate_worked_company_mentioned(question: str, worked_companies: list) -> bool:
    """
    Checks if any company the candidate has worked with is explicitly named in the question.
    """
    q_low = (question or "").lower()
    for company in worked_companies:
        comp_clean = company.lower().strip()
        if not comp_clean:
            continue
        variants = [comp_clean]
        for suffix in [" limited", " pvt ltd", " private limited", " technologies", " innovations", " global", " hotels"]:
            if comp_clean.endswith(suffix):
                variants.append(comp_clean[:-len(suffix)].strip())
        for v in variants:
            if len(v) >= 3 and v in q_low:
                return True
    return False


def resolve_chip_choice(question: str, chips: list, personals: dict):
    """
    Picks the best chip/button element based on question context and candidate profile.
    Guarantees returning an element with non-empty text or None.
    Handles notice periods, locations, skills, education, and interview attendance.
    Never returns a 'Skip' option as an intentional choice.
    """
    valid_chips = []
    chip_map = {}
    skip_phrases = ["skip this question", "skip question", "skip for now"]
    for c in chips:
        try:
            txt = (c.text or c.get_attribute("innerText") or "").strip()
            if txt:
                lower_txt = txt.lower()
                if any(p in lower_txt for p in skip_phrases) or lower_txt == "skip":
                    continue
                valid_chips.append(c)
                chip_map[lower_txt] = c
        except Exception:
            continue

    if not valid_chips:
        return None

    q = (question or "").lower()

    # 0. Interview Mode preference: Virtual vs On-site / F2F
    if any(k in q for k in ["mode of interview", "interview mode", "virtual or", "on-site or", "onsite or", "f2f or", "face to face or"]):
        for text, elem in chip_map.items():
            if any(pos in text for pos in ["virtual", "online", "remote"]):
                return elem
        for text, elem in chip_map.items():
            if any(pos in text for pos in ["on-site", "onsite", "f2f", "face to face"]):
                return elem

    # 1. Interview Attendance / Virtual Interview / Drive / Session / Date availability
    # e.g. "Surely will u attend virtual interview on 24th March (Tuesday)"
    # Chips: ["No - Not sure", "Yes will attend the virtual interview on 24th March (Tuesday)"]
    if any(k in q for k in ["interview", "attend", "virtual", "drive", "walkin", "walk-in", "f2f", "face to face", "onsite", "on-site", "saturday", "sunday", "march", "slot"]):
        # Prioritize explicit affirmative options that do not contain negation
        for text, elem in chip_map.items():
            if any(pos in text for pos in ["yes", "will attend", "available", "agree", "confirm", "accept", "sure"]) and not any(neg in text for neg in ["no", "not sure", "cannot", "unable", "decline"]):
                return elem
        for text, elem in chip_map.items():
            if text.startswith("yes"):
                return elem

    # 2. Education - Year of Passing / Qualification
    if any(k in q for k in ["10th", "10 th", "matric", "secondary"]):
        y10 = str(personals.get("class_10_year", "2016"))
        for text, elem in chip_map.items():
            if y10 in text:
                return elem

    if any(k in q for k in ["12th", "12 th", "intermediate", "higher secondary"]):
        y12 = str(personals.get("class_12_year", "2018"))
        for text, elem in chip_map.items():
            if y12 in text:
                return elem

    if re.search(r'\b(ug|undergraduate|under graduation|bachelor|graduation|graduate|b\.?tech|b\.?e|college|qualification|degree)\b', q):
        y_grad = str(personals.get("graduation_year", "2023"))
        for text, elem in chip_map.items():
            if y_grad in text:
                return elem
        for pref in ["b.tech", "bachelor", "graduate", "b.e", "any graduate"]:
            for text, elem in chip_map.items():
                if pref in text:
                    return elem

    # 3. Interview Timeslot / Time
    if any(k in q for k in ["timeslot", "time slot", "mention time", "am to", "pm to"]) or (
        "time" in q and any(k in q for k in ["interview", "slot", "10 am", "11 am", "12 pm", "1 pm", "2 pm", "3 pm", "4 pm"])
    ):
        pref_time = str(personals.get("preferred_interview_time", "1:30 PM")).lower()
        for text, elem in chip_map.items():
            if "1:30" in text or "1 pm" in text or "2 pm" in text or pref_time in text:
                return elem

    # 4. Notice period question (strictly for notice/joining, excluding interview attendance)
    if any(k in q for k in ["notice period", "notice", "how soon", "when can you join", "days to join", "joining time"]) or (
        "joining" in q and not any(k in q for k in ["interview", "attend", "call"])
    ):
        preferred_labels = ["1 month", "30 days", "15 days or less", "serving notice", "immediate", "30", "15"]
        for pref in preferred_labels:
            for text, elem in chip_map.items():
                if pref in text:
                    return elem
        for text, elem in chip_map.items():
            if "30" in text or "1 month" in text or "immediate" in text:
                return elem
        return valid_chips[0]

    # 5. Location / Work preference / Commute / Relocation / Shift
    if any(k in q for k in ["comfortable", "willing", "relocate", "commute", "gurgaon", "gurugram", "noida", "delhi", "office", "hybrid", "on-site", "work from office", "shift", "ready to work"]):
        # Affirmative over negative
        for text, elem in chip_map.items():
            if any(pos in text for pos in ["yes", "agree", "ready", "willing", "comfortable"]) and not any(neg in text for neg in ["no", "not sure", "cannot", "unable"]):
                return elem
        for text, elem in chip_map.items():
            if any(loc.lower() in text for loc in ["gurgaon", "gurugram", "noida", "delhi"]):
                return elem

    # 6. Experience questions with numeric pills or range options
    if any(k in q for k in ["years of experience", "total experience", "how many years", "experience in", "eperience", "experiance"]):
        exp_val = float(personals.get("total_experience_years", 3.5))
        # Look for range chips like "3-5 years", "<4 years", "3 to 5 Yrs", etc.
        for text, elem in chip_map.items():
            # Check for <X years
            m_lt = re.search(r'<\s*(\d+(?:\.\d+)?)\s*(?:years?|yrs?)?', text)
            if m_lt and exp_val < float(m_lt.group(1)):
                return elem
            # Check for X-Y years or X to Y years
            m_range = re.search(r'(\d+(?:\.\d+)?)\s*(?:-|to)\s*(\d+(?:\.\d+)?)\s*(?:years?|yrs?)?', text)
            if m_range:
                low, high = float(m_range.group(1)), float(m_range.group(2))
                if low <= exp_val <= high:
                    return elem
            # Direct value match
            if str(exp_val) in text or str(int(exp_val)) in text:
                return elem
        return valid_chips[0]

    # 6.5 CTC / Salary range chips
    if any(k in q for k in ["ctc", "salary", "compensation", "package", "drawn", "annual"]):
        is_expected = any(k in q for k in ["expected", "ectc", "desired", "expectation"])
        target_ctc = float(personals.get("expected_ctc_lpa", 24)) if is_expected else float(personals.get("current_ctc_lpa", 20))
        for text, elem in chip_map.items():
            m_range = re.search(r'(\d+(?:\.\d+)?)\s*(?:-|to)\s*(\d+(?:\.\d+)?)\s*(?:lpa|lakhs?|lac|lacs?)?', text)
            if m_range:
                low, high = float(m_range.group(1)), float(m_range.group(2))
                if low <= target_ctc <= high:
                    return elem
            if str(int(target_ctc)) in text or str(target_ctc) in text:
                return elem

    # 7. Ex-employee / previous company / cooling off questions
    if is_prior_company_question(q):
        worked_cos = get_candidate_worked_companies(personals)
        if is_candidate_worked_company_mentioned(q, worked_cos):
            # Candidate DID work with this company -> select "Yes"
            for text, elem in chip_map.items():
                if text == "yes" or text.startswith("yes") or "agree" in text or "confirm" in text:
                    return elem
        else:
            # Candidate did NOT work with this company -> select "No"
            for text, elem in chip_map.items():
                if text == "no" or text.startswith("no") or "not" in text:
                    return elem

    # 8. Military / Veteran / Armed Forces status (e.g. "Have you ever served in the military?")
    if any(k in q for k in ["military", "veteran", "armed forces", "served in the"]):
        for text, elem in chip_map.items():
            if any(neg in text for neg in ["never served", "no", "not served", "none"]):
                return elem

    # 9. Affirmative over negative preference (for general yes/no choices)
    for text, elem in chip_map.items():
        if (text == "yes" or text.startswith("yes") or "agree" in text or "confirm" in text or "available" in text) and not any(neg in text for neg in ["no", "not sure", "not available", "cannot"]):
            return elem

    # 10. Match primary skills in chips if candidate has them
    for text, elem in chip_map.items():
        if any(tech in text for tech in ["python", "sql", "snowflake", "aws", "pyspark", "spark", "databricks", "dbt", "etl", "azure", "gcp"]):
            return elem

    # Fallback to the first valid non-empty chip
    return valid_chips[0]


def resolve_text_question(question: str, personals: dict, skills_exp: dict, whole_number: bool = False) -> str:
    """Returns the accurate answer string for a given screening question."""
    q = (question or "").lower()
    is_wn = whole_number or any(k in q for k in ["whole number", "between 0 and 99", "0-99", "0 to 99", "0 and 99"])

    # 1. QUANTITATIVE / YEARS OF EXPERIENCE QUESTIONS
    # e.g. "How many years of hands-on experience do you have in Snowflake?", "How many years of experience in SQL?", "Total experience"
    # CRITICAL: These must be evaluated before any affirmative Yes/No checks so "do you have" doesn't trigger "Yes"!
    is_years_q = any(k in q for k in [
        "how many years", "how many yrs", "how many year",
        "years of", "yrs of", "how much experience",
        "experience in years", "experience in yrs", "total years",
        "relevant experience", "overall experience", "total experience",
        "work experience", "rel exp", "relevant to", "relevant in"
    ]) or (
        any(w in q for w in ["experience", "eperience", "experiance"]) and
        any(k in q for k in ["how many", "number of", "in years", "in yrs", "years", "yrs"])
    )

    if is_years_q:
        # Check if a specific skill from skills_exp is named in the question
        for skill, years in skills_exp.items():
            pattern = r'\b' + re.escape(skill) + r'\b'
            if re.search(pattern, q):
                return sanitize_whole_number(years, 0, 99) if is_wn else str(years)
        # Fallback to total/relevant experience for general or unmatched skills
        exp = personals.get("total_experience_years", 3.5)
        return sanitize_whole_number(exp, 0, 99) if is_wn else str(exp)

    # 2. Proficiency / Rating / Scale questions
    # e.g. "How strong is your Python experience?", "Rate your skill in SQL on a scale of 1-10"
    if any(k in q for k in ["how strong", "rate your", "rate yourself", "rating", "proficiency level", "on a scale of", "scale of 1", "scale 1"]):
        if is_wn:
            return "4" if ("5" in q and "10" not in q) else "8"
        if any(scale in q for scale in ["1-10", "1 to 10", "1 - 10"]):
            return "8"
        if any(scale in q for scale in ["1-5", "1 to 5", "1 - 5"]):
            return "4"
        return "Advanced (3+ years)"

    # 3. Specific skill experience (e.g. "Python experience", "Working with AWS")
    # If the question is an affirmative Yes/No question (e.g. "Do you have experience with DBT?", "Have you worked in DBT?")
    # and not asking for a number of years, return "Yes" for skills in candidate's profile.
    is_yn_skill_q = (
        any(q.startswith(w) for w in ["do you have", "have you worked", "do you possess", "are you having", "are you experienced", "do you know", "have you done", "are you proficient", "have you used"]) or
        any(k in q for k in ["(yes/no)", "yes or no", "yes/ no", "yes / no", "(y/n)"])
    ) and not is_years_q and not is_wn

    if is_yn_skill_q:
        for skill in skills_exp:
            pattern = r'\b' + re.escape(skill) + r'\b'
            if re.search(pattern, q):
                return "Yes"

    if any(w in q for w in ["experience", "eperience", "experiance", "exp", "proficiency", "hands-on", "hands on", "working with", "knowledge of"]):
        for skill, years in skills_exp.items():
            pattern = r'\b' + re.escape(skill) + r'\b'
            if re.search(pattern, q):
                return sanitize_whole_number(years, 0, 99) if is_wn else str(years)

    # 4. Government ID / PAN / Aadhaar / Passport
    if any(k in q for k in ["pan card", "pan number", "pan no", "pancard"]):
        return str(personals.get("pan_card_number", "HMDPK5264C"))
    if any(k in q for k in ["aadhaar", "aadhar"]):
        return str(personals.get("aadhaar", "NA"))
    if "passport" in q:
        return str(personals.get("passport", "Yes"))
    if any(k in q for k in ["gov id", "id number"]):
        return str(personals.get("pan_card_number", "HMDPK5264C"))

    # 5. Date of Birth (DOB)
    if any(k in q for k in ["dob", "date of birth", "birth date", "birthdate"]):
        return str(personals.get("dob", "15/08/1999"))

    # 6. Statutory & Employment Documents (PF, UAN, Form 16, Payslips)
    # e.g. "Do have PF & Form 16?", "Are you having PF and UAN number", "Do you have Form 16?"
    if any(k in q for k in ["pf", "form 16", "form-16", "uan", "provident fund", "salary slip", "payslip", "relieving letter", "experience letter", "bank statement"]):
        return "Yes"

    # 7. Interview Timeslot / Time questions / Available timing
    # e.g. "Available timing", "24th March (Tuesday).Mention Time from 10 am to 4pm...", "What is your preferred time slot?"
    if any(k in q for k in ["mention time", "timeslot", "time slot", "what time", "preferred time", "suitable time", "interview time", "available timing", "timing"]) or (
        "time" in q and any(k in q for k in ["am to", "pm to", "10 am", "11 am", "12 pm", "1 pm", "2 pm", "3 pm", "4 pm", "slot"])
    ):
        return str(personals.get("preferred_interview_time", "1:30 PM"))

    # 7.1 Interview Mode Preference (Virtual / Flexible)
    if any(k in q for k in ["mode of interview", "interview mode", "interview type", "preferred interview mode", "preferred mode of interview"]):
        return "Virtual"

    # 8. Interview Attendance / Availability / Drive / Session / Mode
    # e.g. "Are you available upcoming Saturday for first round", "Surely will u attend virtual interview", "Will you attend"
    if any(k in q for k in [
        "attend", "virtual interview", "f2f", "face to face", "drive", "walkin", "walk-in",
        "onsite", "on-site", "in-person", "in person", "available upcoming", "available on",
        "will you attend", "ready to attend", "willing to attend", "come for interview",
        "come to office for", "come for face to face", "appear for interview", "available for interview"
    ]):
        return "Yes"

    # 8.1 Active Offers in Hand / Holding Offers (must evaluate before general CTC)
    if any(k in q for k in ["holding any offer", "holding offer", "any offer", "active offer", "other offer", "offered ctc", "counter offer"]):
        has_offer = personals.get("holding_offer", False)
        if not has_offer:
            return "0" if is_wn else "No"
        offered_ctc = personals.get("offered_ctc_lpa", personals.get("expected_ctc_lpa", 24))
        return sanitize_whole_number(offered_ctc, 0, 99) if is_wn else str(offered_ctc)

    # 8.9 Both Current & Expected CTC composite question
    # e.g. "What is your current and expected CTC?", "Please mention your Current CTC & Expected CTC."
    if any(k in q for k in ["current and expected", "current ctc & expected", "current ctc and expected", "cctc and ectc", "cctc & ectc", "current & expected", "current ctc/expected ctc"]):
        c_ctc = personals.get("current_ctc_lpa", 20)
        e_ctc = personals.get("expected_ctc_lpa", 24)
        if is_wn:
            return sanitize_whole_number(c_ctc, 0, 99)
        return f"{c_ctc} LPA / {e_ctc} LPA"

    # 9. Current CTC / Fixed Annual / Last Drawn
    # e.g. "Current/Last Drawn Fixed (Annual)...", "Current Fixed", "Current CTC"
    if any(k in q for k in [
        "current ctc", "cctc", "present ctc", "current salary", "current annual",
        "fixed ctc", "fixed salary", "fixed annual", "drawn fixed", "last drawn",
        "current fixed", "annual fixed", "fixed component", "fixed (annual)", "fixed gross",
        "base salary", "basic salary"
    ]):
        c_ctc = personals.get("current_ctc_lpa", 20)
        return sanitize_whole_number(c_ctc, 0, 99) if is_wn else str(c_ctc)

    # 10. Expected CTC
    if any(k in q for k in ["expected ctc", "ectc", "desired salary", "expected salary", "salary expectation", "minimum ctc"]):
        e_ctc = personals.get("expected_ctc_lpa", 24)
        return sanitize_whole_number(e_ctc, 0, 99) if is_wn else str(e_ctc)

    # 11. General CTC / Salary
    if "ctc" in q or "salary" in q or "compensation" in q:
        g_ctc = personals.get("expected_ctc_lpa", 24)
        return sanitize_whole_number(g_ctc, 0, 99) if is_wn else str(g_ctc)

    # 12. Notice Period & Last Working Day
    if any(k in q for k in ["lwd", "last working day", "last working date"]):
        return "30" if is_wn else "30 Days"
    if any(k in q for k in ["notice period", "notice", "days to join", "how many days", "joining time", "serving notice"]):
        if "month" in q:
            return "1" if is_wn else "1 Month"
        if "day" in q or is_wn:
            return str(personals.get("notice_period_days", 30))
        return "30 Days"

    # 13. Education - Marks / Percentage & Career Gaps
    if any(k in q for k in ["gap", "gaps", "career break", "break in education", "education gap"]):
        return "No"

    # 13.1 Education - Composite (Year of Passing, Percentage/CGPA)
    # e.g. "10th - SSLC (Year of Passing, Percentage/CGPA)", "Graduation (Year of Passing, Percentage/CGPA)"
    if any(k in q for k in ["year of passing", "year completed", "passing year", "batch", "year of"]) and any(k in q for k in ["percentage", "percent", "%", "marks", "cgpa"]):
        if any(k in q for k in ["10th", "10 th", "class 10", "class 10th", "matric", "ssc"]):
            return "75" if is_wn else f"{personals.get('class_10_year', '2016')}, 75%"
        if any(k in q for k in ["12th", "12 th", "class 12", "class 12th", "intermediate", "hsc", "10+2"]):
            return "75" if is_wn else f"{personals.get('class_12_year', '2018')}, 75%"
        if any(k in q for k in ["graduation", "bachelor", "ug", "b.tech", "btech", "highest education", "highest educational"]):
            return "75" if is_wn else f"{personals.get('graduation_year', '2023')}, 75%"

    if any(k in q for k in ["percentage", "percent", "%", "marks", "cgpa", "above 50", "above 60", "above 65", "above 70"]):
        if any(w in q for w in ["whether", "is above", "is greater", "more than", "are you having"]):
            return "Yes"
        return "75%" if not is_wn else "75"

    # 13.3 Applied through vendors / direct agency
    if any(k in q for k in ["applied jobs direct", "other vendors", "applied through vendor", "applied through any vendor", "applied via vendor"]):
        return "No"

    # 14. Education - Class 10th / Matriculation
    if any(k in q for k in ["10th", "10 th", "class 10", "class 10th", "class-10", "matric", "matriculation", "secondary school", "ssc"]):
        return str(personals.get("class_10_year", "2016"))

    # 15. Education - Class 12th / Intermediate / Higher Secondary
    if any(k in q for k in ["12th", "12 th", "class 12", "class 12th", "class-12", "intermediate", "higher secondary", "hsc", "10+2"]):
        return str(personals.get("class_12_year", "2018"))

    # 16. Education - Graduation / UG / Bachelor / College / B.Tech
    if re.search(r'\b(ug|undergraduate|under graduation|bachelor|graduation|graduate|b\.?tech|b\.?e|college)\b', q) or any(k in q for k in ["bachelor", "graduation", "graduate", "btech", "college duration"]):
        if any(k in q for k in ["duration", "tenure", "years from", "from - to", "range"]):
            return str(personals.get("graduation_years", "2019 - 2023"))
        if any(k in q for k in ["year", "completed", "passing", "passout", "pass out", "batch", "when"]):
            return str(personals.get("graduation_year", "2023"))
        if any(k in q for k in ["stream", "specialization", "branch"]):
            return "Computer Science & Engineering"
        return "B.Tech"
    if any(k in q for k in ["qualification", "degree", "education", "highest education"]):
        return "B.Tech"

    # 16.9 Current Payroll Organization / Employer / Payroll Company
    # (Must be checked BEFORE is_prior_company_question so 'Which is your Payroll Company?' returns candidate's employer)
    if any(k in q for k in ["payroll company", "payroll organization", "current payroll", "current employer", "current organization", "present company", "present employer", "current organization"]):
        return str(personals.get("current_company", "Lemon Tree Hotels Limited"))

    # 17. Ex-employee / previous affiliation / prior application / cooling off questions
    # e.g. "Have you worked in / applied to Deloitte earlier?", "Have you worked with cognizant before?", "Are you an ex-employee of TCS?"
    if is_prior_company_question(q, skills_exp=skills_exp):
        worked_cos = get_candidate_worked_companies(personals)
        if is_candidate_worked_company_mentioned(q, worked_cos):
            return "Yes"
        else:
            if any(k in q for k in ["mention na", "type na", "enter na", "write na", "if no: na", "if no: mention na"]):
                return "NA"
            return str(personals.get("is_ex_employee", "No"))

    # 18. Registration IDs / Employee IDs
    if any(k in q for k in ["tcs registration", "ep no", "ep number", "registration-ep"]):
        return "Not Registered"

    # 19. Current Company / Employer / Organization / Payroll
    if any(k in q for k in ["company", "employer", "organization", "firm", "workplace", "payroll company"]):
        return str(personals.get("current_company", "Lemon Tree Hotels Limited"))

    # 20. Open-ended / Descriptive / Why are you interested / About yourself
    if any(k in q for k in ["why are you interested", "why you are interested", "why do you want", "why should we hire", "tell us about", "about yourself", "cover letter", "pitch", "brief summary", "introduce yourself"]):
        return str(personals.get("resume_headline", "Data Engineer with 3+ years of expertise in designing scalable data pipelines and ETL processes using Python, SQL, Spark, and AWS."))

    # 21. Location / City / Relocation City
    if any(k in q for k in ["city", "residing", "relocate", "location", "where do you live"]):
        if any(q.startswith(w) for w in ["are you", "have you", "do you", "can you", "will you"]) and not any(k in q for k in ["which", "what", "select", "enter", "name"]):
            return "Yes"
        if "preferred" in q or "desired" in q:
            return "Gurugram, Noida, Delhi NCR"
        return str(personals.get("current_city", "Gurugram"))
    if any(k in q for k in ["preferred location", "preferred city", "desired location"]):
        return "Gurugram, Noida, Delhi NCR"

    # 22. Job Title / Designation
    if any(k in q for k in ["designation", "job title", "current role", "current designation"]):
        return "Data Engineer"

    # 23. Contact Details
    if any(k in q for k in ["phone", "mobile", "contact number", "whatsapp"]):
        return str(personals.get("phone", "9667267972"))
    if "email" in q:
        return str(personals.get("email", "ankit.k.j1999@gmail.com"))

    # 23.1 Profile and Portfolio Links
    if any(k in q for k in ["linkedin", "linked in", "linkedin profile", "linkedin url"]):
        return str(personals.get("linkedin_url", "https://www.linkedin.com/in/ankitkj1999"))
    if any(k in q for k in ["website", "portfolio", "github", "git hub", "blog", "personal website", "personal url"]):
        return str(personals.get("portfolio_url", "https://ankitkj1999.github.io"))

    # 24. Reason for job change
    if any(k in q for k in ["reason for change", "reason for job change", "why are you looking"]):
        return "Career growth and technical opportunities"

    # 25. General Affirmative / Declarative (Yes/No)
    # (Since quantitative/experience/ID questions are handled above, this now safely handles real yes/no questions)
    if any(q.startswith(w) for w in ["are you", "have you", "do you", "do have", "can you", "will you", "would you", "is there", "did you"]) or any(k in q for k in ["willing", "comfortable", "ready", "open to", "agree", "confirm"]):
        if any(neg in q for neg in [
            "ex-", "former employee", "past employee", "criminal", "convicted", "fired", "terminated",
            "worked in / applied", "worked earlier", "applied earlier", "worked before", "applied before",
            "previously worked", "previously applied", "previously employed", "cooling off", "cooling-off",
            "worked with us", "worked for us", "military", "veteran", "armed forces"
        ]):
            return "No"
        return "Yes"

    # 26. Absolute Fallback
    exp = personals.get("total_experience_years", 3.5)
    return sanitize_whole_number(exp, 0, 99) if is_wn else str(exp)


def match_best_option(answer: str, options: list[str]) -> str | None:
    ans_lower = (answer or "").lower()
    for opt in options:
        if ans_lower in opt.lower():
            return opt
    return options[0] if options else None


def check_apply_success(driver: WebDriver, apply_btn=None) -> bool:
    """
    Checks for success indicators across button states, confirmation toasts, redirected URLs, and DOM text.
    Handles instant 1-Click applies, myapply redirects, banners, and questionnaire completion.
    """
    try:
        curr_url = (driver.current_url or "").lower()
        # On Neo agent page, global page source checks are unsafe because of chat logs and feed cards
        if "job-apply-agent" in curr_url:
            return False

        # 0. Check if current URL was redirected to Naukri's application confirmation page
        if any(u in curr_url for u in ["myapply/saveapply", "myapply", "saveapply"]):
            return True

        # 1. Check if the clicked apply button changed state to 'Applied'
        if apply_btn:
            try:
                b_text = (apply_btn.text or "").strip().lower()
                b_cls = (apply_btn.get_attribute("class") or "").lower()
                if b_text in ["applied", "already applied"] or "applied" in b_cls:
                    return True
            except Exception:
                pass

        # 2. Check elements indicating applied state (e.g. span.already-applied, div.applied-job-content, button.already-applied)
        try:
            applied_elems = driver.find_elements(
                By.XPATH,
                "//*[contains(@class, 'already-applied') or contains(@class, 'applied-job') or contains(@class, 'apply-button-container')] | "
                "//button[contains(@class, 'apply') or @id='apply-button'] | //a[contains(@class, 'apply')] | "
                "//span[contains(@class, 'already-applied')]"
            )
            for ae in applied_elems:
                try:
                    if ae.is_displayed():
                        t = (ae.text or "").strip().lower()
                        cls = (ae.get_attribute("class") or "").lower()
                        if t in ["applied", "already applied"] or "applied to" in t or "already-applied" in cls:
                            return True
                except Exception:
                    continue
        except Exception:
            pass

        # 3. Check for success banners, toasts, or snackbars
        success_banners = driver.find_elements(
            By.XPATH,
            "//div[contains(@class, 'success') or contains(@class, 'toast') or contains(@class, 'apply-message') or contains(@class, 'snackbar')] | "
            "//span[contains(@class, 'success')]"
        )
        for sb in success_banners:
            try:
                if sb.is_displayed():
                    stext = (sb.text or "").lower()
                    if any(p in stext for p in ["applied", "application submitted", "successfully"]):
                        return True
            except Exception:
                continue

        # 4. Check chatbot messages strictly for completion phrases (never greeting phrases)
        try:
            bot_msgs = driver.find_elements(By.XPATH, "//div[contains(@class, 'botMsg')] | //div[contains(@class, 'bot-msg')] | //div[contains(@class, 'msg-text')]")
            for bm in reversed(bot_msgs):
                bt = (bm.text or "").strip().lower()
                # Exclude the greeting: "Hi ..., thank you for showing interest. Kindly answer all the recruiter's questions"
                if "kindly answer" in bt or "showing interest" in bt:
                    continue
                if any(p in bt for p in [
                    "thank you for your responses",
                    "thank you for your response",
                    "responses have been recorded",
                    "responses recorded",
                    "successfully applied",
                    "application submitted",
                ]):
                    return True
        except Exception:
            pass

        # 5. Check full page source for confirmation phrases (unambiguous phrases only)
        page_text = driver.page_source.lower()
        success_phrases = [
            "successfully applied",
            "application submitted",
            "applied successfully",
            "you have applied to this job",
            "thank you for your responses",
            "thank you for your response",
            "multiapplyresp",
        ]
        return any(p in page_text for p in success_phrases)
    except Exception:
        return False


def check_drawer_completed(drawer) -> bool:
    """
    Checks strictly INSIDE the drawer WebElement if the questionnaire has finished.
    Does not inspect global page_source or background chat history.
    """
    if not drawer:
        return False
    try:
        # 1. Check messages strictly inside drawer
        bot_msgs = drawer.find_elements(
            By.XPATH,
            ".//div[contains(@class, 'botMsg')] | .//div[contains(@class, 'bot-msg')] | "
            ".//li[contains(@class, 'botItem')] | .//div[contains(@class, 'msg-text')] | "
            ".//p[contains(@class, 'botMsg')]"
        )
        for bm in reversed(bot_msgs):
            bt = (bm.text or "").strip().lower()
            if "kindly answer" in bt or "showing interest" in bt or "missing details" in bt:
                continue
            if any(p in bt for p in [
                "thank you for your responses",
                "thank you for your response",
                "responses have been recorded",
                "responses recorded",
                "successfully applied",
                "application submitted",
                "applied successfully",
                "your response has been",
                "responses are submitted",
            ]):
                return True

        # 2. Check for explicit success container inside drawer
        success_nodes = drawer.find_elements(
            By.XPATH,
            ".//*[contains(@class, 'success') or contains(@class, 'applied-message') or contains(@class, 'confirm')]//span | "
            ".//*[contains(@class, 'success') or contains(@class, 'applied-message') or contains(@class, 'confirm')]//p"
        )
        for sn in success_nodes:
            st = (sn.text or "").strip().lower()
            if any(p in st for p in ["thank you", "application submitted", "successfully applied", "recorded"]):
                return True
    except Exception:
        pass
    return False



def check_apply_error(driver: WebDriver) -> tuple[bool, str]:
    """
    Detects if Naukri displayed an error message, rate limit, or daily application limit.
    Returns (has_error, error_message).
    """
    try:
        error_patterns = [
            "error while processing your request",
            "try again later",
            "daily application limit",
            "daily limit",
            "limit reached",
            "limit exceeded",
            "maximum applications",
            "unable to process your request",
            "something went wrong",
        ]

        # 1. Check for visible toast, alert, or snackbar banners
        error_elems = driver.find_elements(
            By.XPATH,
            "//div[contains(@class, 'error') or contains(@class, 'toast') or contains(@class, 'alert') or contains(@class, 'snackbar') or contains(@class, 'server-err') or contains(@class, 'serverError')] | "
            "//span[contains(@class, 'error') or contains(@class, 'err')] | "
            "//p[contains(@class, 'error')]"
        )
        for el in error_elems:
            try:
                if el.is_displayed():
                    txt = (el.text or "").strip()
                    lower_t = txt.lower()
                    for pat in error_patterns:
                        if pat in lower_t:
                            return True, txt
            except Exception:
                continue

        # 2. Check full page source for the exact error messages
        page_src = (driver.page_source or "").lower()
        if "error while processing your request" in page_src:
            return True, "There was an error while processing your request, please try again later"
        if "something went wrong" in page_src and "try again" in page_src:
            return True, "Something went wrong. Please Try again later"
        if "daily application limit" in page_src or "reached your daily" in page_src:
            return True, "Daily application limit reached on Naukri"
        if "limit exceeded" in page_src or "maximum applications reached" in page_src:
            return True, "Application limit exceeded on Naukri"

    except Exception:
        pass

    return False, ""


def close_drawer(driver: WebDriver) -> None:
    """Closes the side panel drawer if a close button exists."""
    try:
        close_btn = driver.find_element(
            By.XPATH,
            "//div[contains(@class, 'crossIcon')] | "
            "//div[contains(@class, 'chatBot-ic-cross')] | "
            "//div[contains(@class, 'drawer')]//span[contains(@class, 'cross') or contains(@class, 'close')] | "
            "//span[contains(@class, 'close-chat')]"
        )
        if close_btn.is_displayed():
            driver.execute_script("arguments[0].click();", close_btn)
    except Exception:
        pass


def get_checkbox_label_and_target(driver: WebDriver, cb):
    """
    Returns (clickable_target, label_text) for a native or styled checkbox element.
    Checks explicit <label for='...'>, ancestor/sibling labels, aria-labels, and parent containers.
    """
    target = cb
    text = ""
    try:
        cb_id = cb.get_attribute("id")
        if cb_id:
            labels = driver.find_elements(By.XPATH, f"//label[@for='{cb_id}']")
            if labels and labels[0].text.strip():
                text = labels[0].text.strip()
                target = labels[0]
    except Exception:
        pass
    if not text:
        try:
            parent_labels = cb.find_elements(By.XPATH, "./ancestor::label | ./following-sibling::label | ./parent::label | ./ancestor::div[contains(@class, 'checkbox') or contains(@class, 'check-box')]")
            if parent_labels:
                t = parent_labels[0].text.strip()
                if t:
                    text = t
                    target = parent_labels[0]
        except Exception:
            pass
    if not text:
        try:
            sibling_text = cb.find_elements(By.XPATH, "./following-sibling::* | ./preceding-sibling::*")
            for st in sibling_text:
                t = st.text.strip()
                if t:
                    text = t
                    break
        except Exception:
            pass
    if not text:
        text = cb.get_attribute("aria-label") or cb.get_attribute("value") or ""
    return target, text.strip()


def handle_drawer_checkboxes(driver: WebDriver, drawer, question: str, personals: dict, job_title: str = "", company: str = "") -> bool:
    """
    Detects and intelligently handles checkboxes in the questionnaire drawer.
    Distinguishes between:
    - Yes/No questions (e.g. 'Have you worked in DBT?' -> select 'Yes' ONLY, exclude 'Skip' & 'No')
    - Ex-employee / prior affiliation ('Have you worked in / applied to Deloitte earlier?' -> select 'No' ONLY)
    - Multi-select skills / cities (select candidate skills / locations, excluding 'Skip' / 'None')
    - Terms & declarations (select agreement checkbox)
    Guarantees 'Skip this question' or 'None of the above' is NEVER selected when valid choices exist.
    """
    try:
        q_low = (question or "").lower()
        checked_any = False

        skip_phrases = [
            "skip this question", "skip question", "skip for now", "skip",
            "none of the above", "none of these", "none", "neither",
            "not applicable", "n/a", "no experience"
        ]

        # Check if question is asking about prior employment / application / ex-employee
        is_prior_employment = is_prior_company_question(q_low)
        worked_cos = get_candidate_worked_companies(personals)
        is_my_company = is_candidate_worked_company_mentioned(q_low, worked_cos)

        # 1. Native checkbox inputs
        checkboxes = drawer.find_elements(By.XPATH, ".//input[@type='checkbox']")
        if checkboxes:
            options_data = []
            for cb in checkboxes:
                target, lbl = get_checkbox_label_and_target(driver, cb)
                options_data.append((cb, target, lbl))

            has_yes = any(lbl.lower() == "yes" or lbl.lower().startswith("yes") for _, _, lbl in options_data)
            has_no = any(lbl.lower() == "no" or lbl.lower().startswith("no") for _, _, lbl in options_data)

            selected_labels = []

            for cb, target, lbl in options_data:
                lbl_low = lbl.lower()

                # Rule A: NEVER check skip or none options
                if any(sp in lbl_low for sp in skip_phrases):
                    try:
                        driver.execute_script("""
                            if (arguments[0].checked) {
                                arguments[0].checked = false;
                                arguments[0].dispatchEvent(new Event('change', { bubbles: true }));
                            }
                        """, cb)
                    except Exception:
                        pass
                    continue

                should_check = False

                if has_yes and has_no:
                    # Yes/No Question:
                    if is_prior_employment:
                        if is_my_company:
                            # Prior employment with company candidate actually worked for -> Select "Yes" only
                            if lbl_low == "yes" or lbl_low.startswith("yes"):
                                should_check = True
                        else:
                            # Prior employment with other company -> Select "No" only
                            if lbl_low == "no" or lbl_low.startswith("no"):
                                should_check = True
                    else:
                        # Skills (like DBT, Python, SQL), tools, certifications, relocation -> Select "Yes" only
                        if lbl_low == "yes" or lbl_low.startswith("yes"):
                            should_check = True
                else:
                    # Multi-select options (cities, skills, terms)
                    if any(k in q_low for k in ["location", "locations", "city", "cities", "residing", "relocate"]):
                        preferred_locs = [l.lower() for l in personals.get("target_locations", [])] + [
                            "bengaluru", "bangalore", "hyderabad", "pune", "mumbai", "delhi", "noida", "gurgaon", "gurugram"
                        ]
                        if not lbl_low or any(loc in lbl_low for loc in preferred_locs):
                            should_check = True
                    else:
                        # Skills or general positive options
                        should_check = True

                if should_check:
                    try:
                        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", target)
                        time.sleep(0.15)
                        driver.execute_script("arguments[0].click();", target)
                        driver.execute_script("""
                            if (!arguments[0].checked) {
                                arguments[0].checked = true;
                                arguments[0].dispatchEvent(new Event('change', { bubbles: true }));
                            }
                        """, cb)
                        checked_any = True
                        selected_labels.append(lbl or "Option")
                        time.sleep(0.15)
                    except Exception as e:
                        logger.debug(f"Error checking checkbox: {e}")
                else:
                    # Ensure explicitly unchecked
                    try:
                        driver.execute_script("""
                            if (arguments[0].checked) {
                                arguments[0].checked = false;
                                arguments[0].dispatchEvent(new Event('change', { bubbles: true }));
                            }
                        """, cb)
                    except Exception:
                        pass

            if checked_any:
                logger.info(f"  -> Selected checkbox options for \"{question[:50]}...\": {selected_labels}")

        # 2. Look for custom styled checkboxes / multiselect labels (without native inputs)
        if not checked_any:
            custom_cbs = drawer.find_elements(
                By.XPATH,
                ".//div[contains(@class, 'multiselect')]//label | "
                ".//div[contains(@class, 'multiSelect')]//li | "
                ".//label[contains(@class, 'checkbox') or contains(@class, 'check-box')] | "
                ".//div[contains(@class, 'checkbox-item') or contains(@class, 'custom-checkbox')] | "
                ".//span[contains(@class, 'checkbox')]"
            )
            visible_cbs = [c for c in custom_cbs if c.is_displayed()]
            if visible_cbs:
                c_data = []
                for c in visible_cbs:
                    t = (c.text or c.get_attribute("innerText") or "").strip()
                    c_data.append((c, t))

                has_yes = any(t.lower() == "yes" or t.lower().startswith("yes") for _, t in c_data)
                has_no = any(t.lower() == "no" or t.lower().startswith("no") for _, t in c_data)

                selected_custom = []

                for c_cb, txt in c_data:
                    t_low = txt.lower()
                    if any(sp in t_low for sp in skip_phrases):
                        continue

                    should_click = False
                    if has_yes and has_no:
                        if is_prior_employment:
                            if is_my_company:
                                if t_low == "yes" or t_low.startswith("yes"):
                                    should_click = True
                            else:
                                if t_low == "no" or t_low.startswith("no"):
                                    should_click = True
                        else:
                            if t_low == "yes" or t_low.startswith("yes"):
                                should_click = True
                    else:
                        should_click = True

                    if should_click:
                        try:
                            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", c_cb)
                            time.sleep(0.15)
                            driver.execute_script("arguments[0].click();", c_cb)
                            checked_any = True
                            selected_custom.append(txt or "Option")
                            time.sleep(0.15)
                        except Exception:
                            pass

                if checked_any:
                    logger.info(f"  -> Selected custom checkbox options: {selected_custom}")

        # 3. Look for multi-select location chips (excluding skips)
        if not checked_any:
            is_multi_loc = any(k in q_low for k in ["location", "locations", "cities", "city", "multiple", "available location", "work location", "pick"])
            if is_multi_loc:
                valid_chips = get_valid_chips(drawer)
                if len(valid_chips) > 1:
                    logger.info(f"  -> Multi-location question detected: selecting available location chips...")
                    for chip in valid_chips:
                        try:
                            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", chip)
                            time.sleep(0.15)
                            driver.execute_script("arguments[0].click();", chip)
                            checked_any = True
                            time.sleep(0.15)
                        except Exception:
                            pass

        if checked_any:
            record_screening_question(
                job_title=job_title,
                company=company,
                question=question or "Checkbox Question",
                field_type="checkbox",
                answer="Selected intelligent options",
                status="answered"
            )
            time.sleep(0.5)
            # Unblock disabled state on send button container if present
            driver.execute_script("""
                var sendDiv = arguments[0].querySelector('.send');
                if (sendDiv) { sendDiv.classList.remove('disabled'); }
            """, drawer)
            time.sleep(0.3)

            # Click Save / Send / Next / Continue / Submit
            send_btn = find_drawer_button(drawer, ["save", "send", "submit", "next", "continue", "done"])
            if send_btn and send_btn.is_displayed():
                btn_label = (send_btn.text or "Save").strip()
                logger.info(f"  -> Clicking '{btn_label}' after selecting options...")
                try:
                    send_btn.click()
                except Exception:
                    driver.execute_script("arguments[0].click();", send_btn)
                time.sleep(2)
            return True

    except Exception as e:
        logger.debug(f"Error handling drawer checkboxes: {e}")

    return False


def parse_dob_string(dob_str: str = "15/08/1999") -> dict:
    """Parses date of birth into day (DD), month (MM), year (YYYY) components."""
    dob_str = str(dob_str or "15/08/1999").strip()
    parts = re.split(r'[-/.\s]+', dob_str)
    day, month, year = "15", "08", "1999"
    if len(parts) >= 3:
        if len(parts[0]) == 4:  # YYYY-MM-DD
            year, month, day = parts[0], parts[1], parts[2]
        else:  # DD-MM-YYYY (or MM-DD-YYYY)
            day, month, year = parts[0], parts[1], parts[2]

    try:
        d_val = f"{int(day):02d}"
    except Exception:
        d_val = "15"
    try:
        m_val = f"{int(month):02d}"
    except Exception:
        m_val = "08"
    try:
        y_val = f"{int(year)}"
    except Exception:
        y_val = "1999"

    return {
        "day": d_val,
        "month": m_val,
        "year": y_val,
        "slash": f"{d_val}/{m_val}/{y_val}",
        "dash": f"{d_val}-{m_val}-{y_val}",
        "iso": f"{y_val}-{m_val}-{d_val}",
    }


def handle_drawer_dob_picker(driver: WebDriver, drawer, personals: dict, current_question: str = "", job_title: str = "", company: str = "") -> bool:
    """
    Detects and handles date of birth / date picker components in the application drawer.
    Supports Naukri's exact 3-field date of birth widget (day, month, year) as well as
    HTML5 date inputs and custom datepicker fields.
    """
    try:
        q_low = (current_question or "").lower()
        is_dob_context = any(k in q_low for k in [
            "dob", "date of birth", "birth date", "birthdate",
            "select your date of birth", "enter your date of birth"
        ])

        # 1. Check for Naukri's specific 3-part DOB container / inputs
        day_inps = drawer.find_elements(By.XPATH, ".//input[@name='day' or (contains(@class, 'dob__input') and contains(@class, 'day')) or contains(@id, 'DobInputDay')]")
        month_inps = drawer.find_elements(By.XPATH, ".//input[@name='month' or (contains(@class, 'dob__input') and contains(@class, 'month')) or contains(@id, 'DobInputMonth')]")
        year_inps = drawer.find_elements(By.XPATH, ".//input[@name='year' or (contains(@class, 'dob__input') and contains(@class, 'year')) or contains(@id, 'DobInputYear')]")

        has_triplet = bool(day_inps and month_inps and year_inps)
        triplet_visible = has_triplet and any(i.is_displayed() for i in (day_inps + month_inps + year_inps))

        if triplet_visible or (is_dob_context and has_triplet):
            dob_info = parse_dob_string(personals.get("dob", "15/08/1999"))
            d_val = dob_info["day"]
            m_val = dob_info["month"]
            y_val = dob_info["year"]
            formatted_dob = dob_info["slash"]

            logger.info(f"  -> Detected Naukri Date of Birth picker. Filling Day='{d_val}', Month='{m_val}', Year='{y_val}'...")

            d_elem = day_inps[0]
            m_elem = month_inps[0]
            y_elem = year_inps[0]

            try:
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", d_elem)
                time.sleep(0.3)
            except Exception:
                pass

            # Fill via JavaScript with real value setter and dispatching input/change/blur
            driver.execute_script("""
                function setAndDispatch(input, val) {
                    if (!input) return;
                    input.focus();
                    var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value');
                    if (setter && setter.set) {
                        setter.set.call(input, val);
                    } else {
                        input.value = val;
                    }
                    input.dispatchEvent(new Event('input', { bubbles: true }));
                    input.dispatchEvent(new Event('change', { bubbles: true }));
                    input.dispatchEvent(new Event('blur', { bubbles: true }));
                }
                setAndDispatch(arguments[0], arguments[3]);
                setAndDispatch(arguments[1], arguments[4]);
                setAndDispatch(arguments[2], arguments[5]);
            """, d_elem, m_elem, y_elem, d_val, m_val, y_val)
            time.sleep(0.4)

            # Unblock disabled state on send button container if present
            driver.execute_script("""
                var sendDiv = document.querySelector('.send') || arguments[0].querySelector('.send');
                if (sendDiv) { sendDiv.classList.remove('disabled'); }
            """, drawer)
            time.sleep(0.2)

            # Trigger Enter on the year input (Naukri's handleEnter submits when 4 digits are present)
            try:
                y_elem.send_keys(Keys.ENTER)
                time.sleep(1.5)
            except Exception:
                pass

            # Also click Save / Send button if still displayed and ready
            send_btn = find_drawer_button(drawer, ["save", "send", "submit", "next", "continue", "done"])
            if send_btn and send_btn.is_displayed():
                btn_label = (send_btn.text or "Save").strip()
                logger.info(f"  -> Clicking '{btn_label}' button for Date of Birth...")
                try:
                    send_btn.click()
                except Exception:
                    driver.execute_script("arguments[0].click();", send_btn)
                time.sleep(2)

            record_screening_question(
                job_title=job_title,
                company=company,
                question=current_question or "Date of Birth",
                field_type="dob_picker",
                answer=formatted_dob,
                options=[],
                status="answered"
            )
            return True

        # 2. Check for HTML5 date input or custom datepicker field
        date_inputs = drawer.find_elements(
            By.XPATH,
            ".//input[@type='date'] | "
            ".//input[contains(@class, 'datepicker') or contains(@class, 'date-picker') or contains(@class, 'hasDatepicker') or contains(@placeholder, 'DD/MM/YYYY') or contains(@placeholder, 'DD-MM-YYYY')]"
        )
        visible_date_inputs = [di for di in date_inputs if di.is_displayed()]
        if visible_date_inputs and (is_dob_context or "date" in q_low):
            target_di = visible_date_inputs[0]
            dob_info = parse_dob_string(personals.get("dob", "15/08/1999"))
            inp_type = (target_di.get_attribute("type") or "").lower()
            val_to_fill = dob_info["iso"] if inp_type == "date" else dob_info["slash"]

            logger.info(f"  -> Detected date input field (type={inp_type}). Setting date '{val_to_fill}'...")
            driver.execute_script("""
                arguments[0].focus();
                arguments[0].removeAttribute('readonly');
                var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value');
                if (setter && setter.set) {
                    setter.set.call(arguments[0], arguments[1]);
                } else {
                    arguments[0].value = arguments[1];
                }
                arguments[0].dispatchEvent(new Event('input', { bubbles: true }));
                arguments[0].dispatchEvent(new Event('change', { bubbles: true }));
                arguments[0].dispatchEvent(new Event('blur', { bubbles: true }));
            """, target_di, val_to_fill)
            time.sleep(0.5)

            send_btn = find_drawer_button(drawer, ["save", "send", "submit", "next", "continue", "done"])
            if send_btn and send_btn.is_displayed():
                btn_label = (send_btn.text or "Save").strip()
                logger.info(f"  -> Clicking '{btn_label}' button...")
                try:
                    send_btn.click()
                except Exception:
                    driver.execute_script("arguments[0].click();", send_btn)
                time.sleep(2)

            record_screening_question(
                job_title=job_title,
                company=company,
                question=current_question or "Date of Birth",
                field_type="date_input",
                answer=val_to_fill,
                options=[],
                status="answered"
            )
            return True

    except Exception as e:
        logger.debug(f"Error handling drawer DOB picker: {e}")

    return False


def fill_text_input(driver: WebDriver, drawer, input_elem, answer_text: str, question: str = "") -> bool:
    """Fills a single text input or contenteditable div and reliably clicks Save / Send."""
    try:
        # Check if whole number is required
        if is_whole_number_required(input_elem, question, drawer):
            clean_answer = sanitize_whole_number(answer_text, 0, 99)
            if clean_answer != str(answer_text):
                logger.info(f"  -> Whole number required (0-99): sanitized '{answer_text}' -> '{clean_answer}'")
                answer_text = clean_answer

        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", input_elem)
        time.sleep(0.3)
        input_elem.click()
        time.sleep(0.2)

        is_contenteditable = input_elem.get_attribute("contenteditable") == "true"
        if is_contenteditable:
            # Thoroughly clear previous text
            driver.execute_script("""
                arguments[0].focus();
                arguments[0].innerText = '';
                arguments[0].dispatchEvent(new Event('input', { bubbles: true }));
                arguments[0].dispatchEvent(new Event('change', { bubbles: true }));
            """, input_elem)
            time.sleep(0.2)
            input_elem.send_keys(Keys.CONTROL + "a")
            input_elem.send_keys(Keys.BACKSPACE)
            time.sleep(0.2)

            # Type with real keystrokes so React state registers the value
            input_elem.send_keys(str(answer_text))
            time.sleep(0.4)

            driver.execute_script("""
                arguments[0].dispatchEvent(new Event('input', { bubbles: true }));
                arguments[0].dispatchEvent(new Event('change', { bubbles: true }));
            """, input_elem)
            time.sleep(0.2)
        else:
            input_elem.send_keys(Keys.CONTROL + "a")
            input_elem.send_keys(Keys.BACKSPACE)
            input_elem.clear()
            driver.execute_script("""
                arguments[0].value = '';
                arguments[0].dispatchEvent(new Event('input', { bubbles: true }));
                arguments[0].dispatchEvent(new Event('change', { bubbles: true }));
            """, input_elem)
            time.sleep(0.2)
            input_elem.send_keys(str(answer_text))
            time.sleep(0.4)
            driver.execute_script("""
                arguments[0].dispatchEvent(new Event('input', { bubbles: true }));
                arguments[0].dispatchEvent(new Event('change', { bubbles: true }));
            """, input_elem)
            time.sleep(0.2)

        # Immediate validation check: if Naukri rendered an error (e.g. "Enter a whole number between 0 and 99")
        try:
            val_errors = drawer.find_elements(
                By.XPATH,
                ".//*[contains(@class, 'err') or contains(@class, 'error') or contains(@class, 'warning')]"
            )
            for ve in val_errors:
                if ve.is_displayed():
                    v_txt = (ve.text or "").strip()
                    if any(k in v_txt.lower() for k in ["whole number", "between 0 and 99", "0-99", "valid number", "0 to 99"]):
                        logger.warning(f"  ⚠️ Validation error on field: '{v_txt}'. Auto-correcting to a whole number integer...")
                        fixed_val = sanitize_whole_number(answer_text, 0, 99)
                        if is_contenteditable:
                            driver.execute_script("arguments[0].innerText = '';", input_elem)
                        else:
                            driver.execute_script("arguments[0].value = '';", input_elem)
                        input_elem.send_keys(Keys.CONTROL + "a")
                        input_elem.send_keys(Keys.BACKSPACE)
                        input_elem.send_keys(fixed_val)
                        driver.execute_script("""
                            arguments[0].dispatchEvent(new Event('input', { bubbles: true }));
                            arguments[0].dispatchEvent(new Event('change', { bubbles: true }));
                        """, input_elem)
                        time.sleep(0.3)
                        break
        except Exception:
            pass

        # Remove disabled class from send button wrapper if React hasn't unblocked it yet
        driver.execute_script("""
            var sendDiv = arguments[0].querySelector('.send');
            if (sendDiv) { sendDiv.classList.remove('disabled'); }
        """, drawer)
        time.sleep(0.2)

        # Look for Save / Send button strictly inside drawer
        send_btn = find_drawer_button(drawer, ["save", "send", "submit", "next", "arrow", "icon-send"])
        clicked = False
        if send_btn and send_btn.is_displayed():
            btn_label = (send_btn.text or "Save").strip()
            logger.info(f"  -> Clicking '{btn_label}' button...")
            try:
                send_btn.click()
                clicked = True
            except Exception:
                pass
            if not clicked:
                try:
                    driver.execute_script("arguments[0].click();", send_btn)
                    clicked = True
                except Exception:
                    pass

        # If send_btn wasn't found or as a guaranteed submission, send RETURN key
        if not clicked:
            input_elem.send_keys(Keys.RETURN)

        time.sleep(0.3)
        return True
    except Exception as e:
        logger.debug(f"Failed to fill input: {e}")
        return False


def handle_drawer_resume_prompt(driver: WebDriver, drawer, config: dict) -> bool:
    """
    Handles Naukri's resume upload prompt inside the chatbot drawer.
    Attempts to attach the configured resume PDF if an input[type='file'] is present,
    or clicks "I'll do it later" / "Skip" to proceed.
    """
    try:
        # Check if resume prompt is visible inside drawer
        text_nodes = drawer.find_elements(
            By.XPATH,
            ".//*[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'upload resume') or contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'attach resume') or contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'do it later')]"
        )
        visible_nodes = [t for t in text_nodes if t.is_displayed()]
        if not visible_nodes:
            return False

        logger.info("  -> Resume prompt detected in chatbot drawer.")

        # Attempt 1: Upload configured resume if a file input exists
        from resume_resolver import resolve_resume_path
        resume_path = resolve_resume_path(config)
        if resume_path and os.path.exists(resume_path):
            file_inputs = drawer.find_elements(By.XPATH, ".//input[@type='file']") or driver.find_elements(By.XPATH, "//input[@type='file']")
            for fi in file_inputs:
                try:
                    fi.send_keys(resume_path)
                    logger.info(f"  ✓ Uploaded resume file: {resume_path}")
                    time.sleep(2)
                    return True
                except Exception as e:
                    logger.debug(f"Could not send resume to file input: {e}")

        # Attempt 2: Click "I'll do it later" / "Skip" / "Later"
        later_elems = drawer.find_elements(
            By.XPATH,
            ".//*[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'later') or contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'skip')]"
        )
        for le in later_elems:
            try:
                if le.is_displayed():
                    btn_text = (le.text or "").strip()
                    if btn_text and len(btn_text) < 40:
                        logger.info(f"  -> Clicking '{btn_text}' on resume prompt...")
                        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", le)
                        time.sleep(0.3)
                        driver.execute_script("arguments[0].click();", le)
                        time.sleep(2)
                        return True
            except Exception:
                continue

    except Exception as e:
        logger.debug(f"Error handling drawer resume prompt: {e}")
    return False


def handle_form_questionnaire(driver: WebDriver, drawer, personals: dict, skills_exp: dict, job_title: str = "", company: str = "") -> bool:
    """
    Handles a full static or multi-field form questionnaire inside the drawer.
    Finds all inputs, selects, and radio groups, fills them, and clicks Submit.
    """
    # 0. Handle DOB picker if present in form
    handle_drawer_dob_picker(driver, drawer, personals, current_question="", job_title=job_title, company=company)

    # 1. Fill all text/number inputs, contenteditable divs, and textareas
    inputs = drawer.find_elements(
        By.XPATH,
        ".//div[@contenteditable='true'] | .//input[(@type='text' or @type='number' or not(@type)) and not(@type='hidden') and not(@type='radio') and not(@type='checkbox') and not(contains(@class, 'dob__input')) and not(@name='day') and not(@name='month') and not(@name='year')] | .//textarea"
    )
    for inp in inputs:
        try:
            if not inp.is_displayed():
                continue
            curr_val = (inp.get_attribute("value") or inp.text or "").strip()
            if curr_val:
                continue  # Already filled

            q_text = get_question_for_field(inp)
            answer = resolve_text_question(q_text, personals, skills_exp)
            logger.info(f"  -> Filled form field \"{answer}\" for \"{q_text[:50]}...\"")
            fill_text_input(driver, drawer, inp, answer, question=q_text)
            record_screening_question(
                job_title=job_title,
                company=company,
                question=q_text,
                field_type="form_input",
                answer=answer,
                options=[],
                status="answered"
            )
            time.sleep(0.3)
        except Exception as e:
            logger.debug(f"Error filling form input: {e}")

    # 2. Handle Dropdowns (<select>)
    selects = drawer.find_elements(By.XPATH, ".//select")
    for sel_elem in selects:
        try:
            if not sel_elem.is_displayed():
                continue
            sel = Select(sel_elem)
            q_text = get_question_for_field(sel_elem)
            answer = resolve_text_question(q_text, personals, skills_exp)
            options = [o.text for o in sel.options]
            matched = match_best_option(answer, options)
            if matched:
                sel.select_by_visible_text(matched)
                logger.info(f"  -> Selected dropdown \"{matched}\" for \"{q_text[:50]}...\"")
                record_screening_question(
                    job_title=job_title,
                    company=company,
                    question=q_text,
                    field_type="form_dropdown",
                    answer=matched,
                    options=options,
                    status="answered"
                )
        except Exception as e:
            logger.debug(f"Error selecting dropdown: {e}")

    # 3. Handle Radio button groups (<input type='radio'>)
    radio_groups = {}
    radios = drawer.find_elements(By.XPATH, ".//input[@type='radio']")
    for r in radios:
        try:
            if not r.is_displayed():
                continue
            name = r.get_attribute("name") or "default_group"
            radio_groups.setdefault(name, []).append(r)
        except Exception:
            continue

    for name, group in radio_groups.items():
        try:
            if any(r.is_selected() for r in group):
                continue
            target_radio = None
            for r in group:
                lbl_text = get_label_for_radio(r)
                if any(w in lbl_text.lower() for w in ["yes", "agree", "immediate", "1 month", "30"]):
                    target_radio = r
                    break
            if not target_radio and group:
                target_radio = group[0]

            if target_radio:
                lbl_text = get_label_for_radio(target_radio)
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", target_radio)
                driver.execute_script("arguments[0].click();", target_radio)
                record_screening_question(
                    job_title=job_title,
                    company=company,
                    question=name,
                    field_type="form_radio",
                    answer=lbl_text or "selected",
                    options=[get_label_for_radio(r) for r in group],
                    status="answered"
                )
                time.sleep(0.3)
        except Exception as e:
            logger.debug(f"Error selecting radio: {e}")

    # 4. Handle Checkboxes (Terms / Confirmation)
    checkboxes = drawer.find_elements(By.XPATH, ".//input[@type='checkbox']")
    for cb in checkboxes:
        try:
            if cb.is_displayed() and not cb.is_selected():
                driver.execute_script("arguments[0].click();", cb)
                time.sleep(0.3)
        except Exception:
            pass

    # 5. Click the Submit / Apply button
    submit_btn = find_drawer_button(drawer, ["submit application", "submit", "apply now", "apply", "confirm", "save and apply", "save", "done"])
    if submit_btn and submit_btn.is_displayed():
        btn_txt = (submit_btn.text or "").strip()
        logger.info(f"  -> Clicking '{btn_txt}' in form drawer.")
        driver.execute_script("arguments[0].click();", submit_btn)
        time.sleep(2.5)
        return check_apply_success(driver)

    return False


def handle_naukri_chatbot_drawer(driver: WebDriver, config: dict, max_steps: int = 15, job_title: str = "", company: str = "") -> bool:
    """
    Handles Naukri's application scenarios:
    1. Detects instant 1-click apply if application succeeded without a side panel.
    2. If a multi-field questionnaire form is open, fills all fields and clicks submit.
    3. If a conversational chatbot is open, answers questions step-by-step.
    Returns True if successfully submitted, False otherwise.
    """
    time.sleep(1.0)
    personals = config.get("personals", {})
    skills_exp = config.get("skills_experience", {})
    is_neo_page = "job-apply-agent" in (driver.current_url or "").lower()

    if not job_title:
        try:
            h1 = driver.find_elements(By.XPATH, "//h1[contains(@class, 'title') or contains(@class, 'jd-header-title')]")
            if h1:
                job_title = (h1[0].text or "").strip()
        except Exception:
            pass
    if not company:
        try:
            c_elem = driver.find_elements(By.XPATH, "//div[contains(@class, 'company-name')] | //a[contains(@class, 'company-name')]")
            if c_elem:
                company = (c_elem[0].text or "").strip()
        except Exception:
            pass

    # 1. Locate the questionnaire drawer / modal first
    drawer = find_drawer(driver)

    # 2. If not found in main document, check if an iframe holds the questionnaire
    if not drawer:
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for frame in iframes:
            try:
                if not frame.is_displayed():
                    continue
                driver.switch_to.frame(frame)
                sub_drawer = find_drawer(driver) or driver.find_element(By.TAG_NAME, "body")
                if is_real_questionnaire_drawer(sub_drawer):
                    drawer = sub_drawer
                    break
                driver.switch_to.default_content()
            except Exception:
                driver.switch_to.default_content()

    # 3. If no drawer is detected: Check if 1-click apply succeeded directly (standard job listings only)
    if not drawer:
        if not is_neo_page:
            time.sleep(1.5)
            if check_apply_success(driver):
                logger.info("  ✓ Instant 1-Click apply succeeded directly (no side panel questions).")
                return True
        logger.info("  [Info] No questionnaire drawer detected and apply not confirmed.")
        return False

    logger.info("  -> Side panel questionnaire drawer opened. Answering screening questions...")

    # 4. Check if this is a static multi-field form (multiple inputs / selects / radios without chatbot structure)
    visible_inputs = get_visible_inputs(drawer)
    has_radios = bool(drawer.find_elements(By.XPATH, ".//input[@type='radio']"))
    has_selects = bool(drawer.find_elements(By.XPATH, ".//select"))
    is_chat = bool(drawer.find_elements(
        By.XPATH,
        ".//div[contains(@class, 'botMsg')] | .//div[contains(@class, 'bot-msg')] | "
        ".//li[contains(@class, 'botItem')] | .//div[contains(@class, 'chatbot_Drawer')] | "
        ".//div[contains(@class, '_chatBotContainer')] | .//div[contains(@class, 'sendMsgbtn_container')]"
    ))

    if not is_chat and (len(visible_inputs) > 1 or has_radios or has_selects):
        logger.info(f"  -> Detected static multi-field questionnaire form. Filling all fields...")
        form_success = handle_form_questionnaire(driver, drawer, personals, skills_exp, job_title=job_title, company=company)
        if form_success or check_drawer_completed(drawer) or (not is_neo_page and check_apply_success(driver)):
            logger.info("  ✓ Multi-field questionnaire submitted successfully!")
            close_drawer(driver)
            try:
                driver.switch_to.default_content()
            except Exception:
                pass
            return True

    # 5. Conversational Chatbot loop (step-by-step RIA chat)
    step = 0
    last_action = ""
    repeat_count = 0
    questions_answered_count = 0

    while step < max_steps:
        step += 1
        time.sleep(1.5)

        # Check for error / rate limit banner first
        has_err, err_msg = check_apply_error(driver)
        if has_err:
            logger.warning(f"  ⚠️ Error/Limit banner detected in drawer: \"{err_msg}\"")
            return False

        if check_drawer_completed(drawer) or (not is_neo_page and check_apply_success(driver)):
            logger.info("  ✓ Application submitted successfully through side panel!")
            close_drawer(driver)
            try:
                driver.switch_to.default_content()
            except Exception:
                pass
            return True

        # Refresh drawer
        drawer = find_drawer(driver) or drawer

        # If drawer is no longer displayed/present and we answered at least 1 question, submit succeeded!
        try:
            if not drawer.is_displayed() and questions_answered_count > 0:
                logger.info("  ✓ Questionnaire drawer closed after answering questions. Application complete!")
                return True
        except Exception:
            if questions_answered_count > 0:
                logger.info("  ✓ Questionnaire drawer detached after answering questions. Application complete!")
                return True

        # Check for Final Submit / Apply button first if available and ready
        submit_btn = find_drawer_button(drawer, ["submit application", "apply now", "confirm apply", "done", "save and apply"])
        if submit_btn and submit_btn.is_displayed():
            btn_txt = (submit_btn.text or "").strip()
            v_inputs = get_visible_inputs(drawer)
            empty_inps = [i for i in v_inputs if not (i.get_attribute("value") or i.text or "").strip()]
            if not empty_inps:
                logger.info(f"  -> Clicking '{btn_txt}' in questionnaire drawer.")
                driver.execute_script("arguments[0].click();", submit_btn)
                time.sleep(2)
                if check_drawer_completed(drawer) or (not is_neo_page and check_apply_success(driver)):
                    logger.info("  ✓ Application submitted successfully!")
                    close_drawer(driver)
                    try:
                        driver.switch_to.default_content()
                    except Exception:
                        pass
                    return True
                questions_answered_count += 1

        current_question = get_latest_bot_question(drawer)
        if any(k in current_question.lower() for k in ["something went wrong", "try again later", "error while processing"]):
            logger.warning(f"  ⚠️ Application error message detected inside drawer: \"{current_question}\"")
            return False
        visible_inputs = get_visible_inputs(drawer)
        visible_chips = get_valid_chips(drawer)
        visible_selects = get_visible_selects(drawer)

        answered = False

        # Handle resume upload prompt ("Upload Resume / I'll do it later")
        if handle_drawer_resume_prompt(driver, drawer, config):
            time.sleep(1.5)
            continue

        # Handle Date of Birth / Date picker prompt
        if handle_drawer_dob_picker(driver, drawer, personals, current_question=current_question, job_title=job_title, company=company):
            time.sleep(2)
            continue

        # Handle Checkboxes / Multi-select options (e.g. "Pick available location", multiple cities, terms)
        if handle_drawer_checkboxes(driver, drawer, current_question, personals, job_title=job_title, company=company):
            time.sleep(2)
            continue

        # Identify available input element
        # In conversational chatbot drawers, the contenteditable input container is persistent across questions
        ce_inputs = [i for i in visible_inputs if i.get_attribute("contenteditable") == "true"]
        empty_inputs = [i for i in visible_inputs if i.get_attribute("contenteditable") != "true" and not (i.get_attribute("value") or "").strip()]
        available_input = ce_inputs[0] if ce_inputs else (empty_inputs[0] if empty_inputs else None)

        # A. Handle Clickable Chips / Radio Buttons / Quick-Replies
        if visible_chips:
            target_chip = resolve_chip_choice(current_question, visible_chips, personals)
            if target_chip:
                chip_txt = (target_chip.text or target_chip.get_attribute("innerText") or "").strip()
                action_key = f"chip_{current_question}_{chip_txt}"
                if action_key == last_action:
                    repeat_count += 1
                else:
                    last_action = action_key
                    repeat_count = 0

                if repeat_count < 2:
                    effective_q = current_question or get_question_for_chip(target_chip)
                    q_disp = f' for "{effective_q[:50]}..."' if effective_q else ""
                    logger.info(f"  -> Selected option: \"{chip_txt}\"{q_disp}")
                    record_screening_question(
                        job_title=job_title,
                        company=company,
                        question=effective_q or chip_txt,
                        field_type="chip_choice",
                        answer=chip_txt,
                        options=[(c.text or c.get_attribute("innerText") or "").strip() for c in visible_chips if (c.text or c.get_attribute("innerText") or "").strip()],
                        status="answered"
                    )
                    try:
                        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", target_chip)
                        time.sleep(0.3)
                        driver.execute_script("arguments[0].click();", target_chip)

                        # Also ensure radio input itself is checked if present
                        try:
                            radios = target_chip.find_elements(
                                By.XPATH,
                                ".//input[@type='radio'] | "
                                "./preceding-sibling::input[@type='radio'] | "
                                "./ancestor::div[contains(@class, 'ssrc__radio-btn-container') or contains(@class, 'radio-btn') or contains(@class, 'radio')]//input[@type='radio']"
                            )
                            for r in radios:
                                driver.execute_script("""
                                    const r = arguments[0];
                                    try { r.click(); } catch(e){}
                                    r.checked = true;
                                    r.dispatchEvent(new Event('change', { bubbles: true }));
                                    r.dispatchEvent(new Event('input', { bubbles: true }));
                                """, r)
                        except Exception:
                            pass

                        # Unblock disabled state on send button container if present
                        driver.execute_script("""
                            var sendDiv = arguments[0].querySelector('.send');
                            if (sendDiv) { sendDiv.classList.remove('disabled'); }
                        """, drawer)
                        time.sleep(0.4)

                        # Look for Save / Send / Next button strictly inside drawer
                        send_btn = find_drawer_button(drawer, ["save", "send", "submit", "next", "continue", "done"])
                        if send_btn and send_btn.is_displayed():
                            btn_label = (send_btn.text or "Save").strip()
                            logger.info(f"  -> Clicking '{btn_label}' button...")
                            try:
                                driver.execute_script("""
                                    const d = arguments[0];
                                    const btn = arguments[1];
                                    const sendDiv = d.querySelector('.send');
                                    if (sendDiv) { sendDiv.classList.remove('disabled'); }
                                    btn.click();
                                """, drawer, send_btn)
                            except Exception:
                                driver.execute_script("arguments[0].click();", send_btn)

                        answered = True
                        questions_answered_count += 1
                        time.sleep(2)
                        continue
                    except Exception as e:
                        logger.debug(f"Failed to click chip: {e}")

        # B. Handle Text Input (when no chips are provided or chip choice didn't answer)
        if not answered and available_input:
            q_text = get_question_for_field(available_input)
            effective_q = current_question if current_question and len(current_question) > 5 else q_text
            answer_text = resolve_text_question(effective_q, personals, skills_exp)

            action_key = f"input_{effective_q}_{answer_text}"
            if action_key == last_action:
                repeat_count += 1
            else:
                last_action = action_key
                repeat_count = 0

            if repeat_count < 2:
                logger.info(f"  -> Filled answer \"{answer_text}\" for \"{effective_q[:50]}...\"")
                fill_success = fill_text_input(driver, drawer, available_input, answer_text, question=effective_q)
                if fill_success:
                    record_screening_question(
                        job_title=job_title,
                        company=company,
                        question=effective_q,
                        field_type="text",
                        answer=answer_text,
                        options=[],
                        status="answered"
                    )
                    answered = True
                    questions_answered_count += 1
                    time.sleep(2)
                    continue

        # C. Handle Dropdowns (<select>)
        if not answered and visible_selects:
            sel_elem = visible_selects[-1]
            try:
                sel = Select(sel_elem)
                q_text = get_question_for_field(sel_elem)
                effective_q = current_question if current_question and len(current_question) > 5 else q_text
                answer_text = resolve_text_question(effective_q, personals, skills_exp)
                options = [o.text for o in sel.options]
                matched_option = match_best_option(answer_text or "Yes", options)
                if matched_option:
                    sel.select_by_visible_text(matched_option)
                    logger.info(f"  -> Selected dropdown option: \"{matched_option}\" for \"{effective_q[:50]}...\"")
                    record_screening_question(
                        job_title=job_title,
                        company=company,
                        question=effective_q,
                        field_type="dropdown",
                        answer=matched_option,
                        options=options,
                        status="answered"
                    )
                    answered = True
                    questions_answered_count += 1
                    send_btn = find_drawer_button(drawer, ["save", "send", "submit", "next"])
                    if send_btn and send_btn.is_displayed():
                        driver.execute_script("arguments[0].click();", send_btn)
                    time.sleep(2)
                    continue
            except Exception as e:
                logger.debug(f"Failed to select dropdown: {e}")

        # D. Optional skip fallback ONLY if completely devoid of answerable fields
        if not answered and not visible_chips and not available_input and not visible_selects:
            skip_btn = find_drawer_button(drawer, ["skip this question", "skip question", "skip"])
            if skip_btn and skip_btn.is_displayed():
                btn_txt = (skip_btn.text or "Skip").strip()
                logger.info(f"  -> No input fields found; proceeding via optional '{btn_txt}'...")
                record_screening_question(
                    job_title=job_title,
                    company=company,
                    question=current_question or "Optional Step",
                    field_type="optional_skip",
                    answer=btn_txt,
                    status="skipped"
                )
                driver.execute_script("arguments[0].click();", skip_btn)
                time.sleep(2)
                continue

        # E. Fallback if repeating
        if repeat_count >= 2:
            logger.warning("  ! Questionnaire action repeated without progress. Attempting final submit...")
            gen_submit = find_drawer_button(drawer, ["save", "submit", "apply", "continue", "next", "done"])
            if gen_submit and gen_submit.is_displayed():
                driver.execute_script("arguments[0].click();", gen_submit)
                time.sleep(2)
                if check_drawer_completed(drawer) or (not is_neo_page and check_apply_success(driver)):
                    logger.info("  ✓ Application submitted successfully!")
                    close_drawer(driver)
                    try:
                        driver.switch_to.default_content()
                    except Exception:
                        pass
                    return True
            break

        if not answered:
            time.sleep(1)

    close_drawer(driver)
    try:
        driver.switch_to.default_content()
    except Exception:
        pass
    if is_neo_page:
        return questions_answered_count > 0 or check_drawer_completed(drawer)
    return check_apply_success(driver)

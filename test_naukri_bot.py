import os
import json
import pytest
from job_applier import (
    is_title_relevant,
    is_location_match,
    parse_experience_range,
    is_experience_suitable,
    find_naukri_apply_button,
    is_hard_quota_limit,
)
from chatbot_handler import (
    resolve_text_question,
    resolve_chip_choice,
    check_apply_success,
    sanitize_whole_number,
    is_whole_number_required,
    fill_text_input,
    handle_drawer_checkboxes,
)


def test_title_relevance_filter():
    bad_words = [
        "Full Stack", "Frontend", "Android", "iOS", "UI/UX", "Web Developer",
        "Lead", "Principal", "Architect", "Engineering Manager", "Director", "Intern",
        "Tester", "Testing", "QA", "SDET", "Virtual Business", "Relationship Manager", "RM",
        "Sales", "SRE", "DevOps", "Data Scientist", "Scientist", "Senior Resource"
    ]
    mandatory_words = [
        "data engineer", "data engineering", "data engg", "data eng", "data developer",
        "big data", "pyspark", "spark", "databricks", "etl", "data platform", "data pipeline"
    ]

    # Should be rejected by blacklist
    assert is_title_relevant("Senior Full Stack Developer", bad_words, mandatory_words) is False
    assert is_title_relevant("Frontend Engineer", bad_words, mandatory_words) is False
    assert is_title_relevant("Lead Data Engineer", bad_words, mandatory_words) is False
    assert is_title_relevant("Principal Data Engineer", bad_words, mandatory_words) is False
    assert is_title_relevant("Data Architect", bad_words, mandatory_words) is False
    assert is_title_relevant("Etl Tester-INFY 26", bad_words, mandatory_words) is False
    assert is_title_relevant("Data Scientist_ NLP GenAI", bad_words, mandatory_words) is False
    assert is_title_relevant("SRE / Devops / Automation / Production Support", bad_words, mandatory_words) is False
    assert is_title_relevant("Walk-in || Data Engineer", bad_words + ["Walk-in"], mandatory_words) is False

    # Should be rejected by mandatory whitelist (irrelevant roles)
    assert is_title_relevant("Virtual Business-RM", bad_words, mandatory_words) is False
    assert is_title_relevant("Senior Resource", bad_words, mandatory_words) is False
    assert is_title_relevant("Senior Software Engineer(Odoo, Python)", bad_words, mandatory_words) is False
    assert is_title_relevant("Tech S And T Product Engineer", bad_words, mandatory_words) is False

    # Should be accepted
    assert is_title_relevant("Data Engineer", bad_words, mandatory_words) is True
    assert is_title_relevant("AWS Data Engineer", bad_words, mandatory_words) is True
    assert is_title_relevant("PySpark / Spark Developer", bad_words, mandatory_words) is True
    assert is_title_relevant("Senior ETL Developer - Databricks", bad_words, mandatory_words) is True
    assert is_title_relevant("Big Data Engineer", bad_words, mandatory_words) is True
    assert is_title_relevant("Sr Engineer-Data Engg", bad_words, mandatory_words) is True
    assert is_title_relevant("Data Developer", bad_words, mandatory_words) is True
    assert is_title_relevant("Azure Data Eng Consultant", bad_words, mandatory_words) is True


def test_is_hard_quota_limit():
    assert is_hard_quota_limit("Daily application limit reached for your account") is True
    assert is_hard_quota_limit("You have reached your daily limit") is True
    assert is_hard_quota_limit("Maximum applications limit exceeded") is True
    assert is_hard_quota_limit("quota reached") is True

    # Transient single-job errors should NOT be classified as hard daily quota limit
    assert is_hard_quota_limit("There was an error while processing your request, please try again later") is False
    assert is_hard_quota_limit("Something went wrong") is False
    assert is_hard_quota_limit("Unable to process your request") is False
    assert is_hard_quota_limit("") is False


def test_parse_experience_range():
    assert parse_experience_range("3-5 Yrs") == (3, 5)
    assert parse_experience_range("2 - 6 years") == (2, 6)
    assert parse_experience_range("3 to 7 Yrs") == (3, 7)
    assert parse_experience_range("5+ Yrs") == (5, 10)
    assert parse_experience_range("3 Yrs") == (3, 3)
    assert parse_experience_range("0 - 1 Yrs") == (0, 1)
    assert parse_experience_range("Not Disclosed") == (None, None)
    assert parse_experience_range("") == (None, None)


def test_is_experience_suitable():
    candidate_exp = 3
    min_allowed = 1
    max_allowed = 5
    max_stretch = 1

    # Suitable roles
    ok, _ = is_experience_suitable("3-5 Yrs", candidate_exp, min_allowed, max_allowed, max_stretch)
    assert ok is True

    ok, _ = is_experience_suitable("2-4 Yrs", candidate_exp, min_allowed, max_allowed, max_stretch)
    assert ok is True

    ok, _ = is_experience_suitable("1-3 Yrs", candidate_exp, min_allowed, max_allowed, max_stretch)
    assert ok is True

    ok, _ = is_experience_suitable("3-8 Yrs", candidate_exp, min_allowed, max_allowed, max_stretch)
    assert ok is True

    ok, _ = is_experience_suitable("4-6 Yrs", candidate_exp, min_allowed, max_allowed, max_stretch)
    assert ok is True  # 4 is within stretch (3 + 1)

    # Unsuitable roles (too high experience)
    ok, reason = is_experience_suitable("5-10 Yrs", candidate_exp, min_allowed, max_allowed, max_stretch)
    assert ok is False
    assert "min 5" in reason

    ok, reason = is_experience_suitable("8-13 Yrs", candidate_exp, min_allowed, max_allowed, max_stretch)
    assert ok is False

    ok, reason = is_experience_suitable("6+ Yrs", candidate_exp, min_allowed, max_allowed, max_stretch)
    assert ok is False

    # Unsuitable roles (too low experience / fresher)
    ok, reason = is_experience_suitable("0-0 Yrs", candidate_exp, min_allowed=2, max_allowed=5, max_stretch=1)
    assert ok is False


def test_resolve_text_questions():
    personals = {
        "current_ctc_lpa": 13,
        "expected_ctc_lpa": 18,
        "notice_period_days": 30,
        "total_experience_years": 3.5,
        "current_company": "Lemon Tree Hotels Limited",
        "current_city": "Gurugram",
        "class_10_year": "2016",
        "class_12_year": "2018",
        "graduation_year": "2023",
        "graduation_years": "2019 - 2023",
        "preferred_interview_time": "1:30 PM",
        "phone": "9667267972",
        "email": "ankit.k.j1999@gmail.com",
    }
    skills_exp = {
        "python": 3,
        "sql": 3,
        "aws": 3,
        "spark": 3,
        "pyspark": 3,
        "gcp": 2,
        "dbt": 2,
    }

    # CTC
    assert resolve_text_question("Please share your current CTC in LPA", personals, skills_exp) == "13"
    assert resolve_text_question("What is your expected CTC (annual)", personals, skills_exp) == "18"

    # Notice Period
    assert resolve_text_question("How many days is your notice period?", personals, skills_exp) == "30"

    # Experience
    assert resolve_text_question("How many years of experience in PySpark?", personals, skills_exp) == "3"
    assert resolve_text_question("Total years of experience in data engineering", personals, skills_exp) == "3.5"

    # Timeslot & Interview availability
    assert resolve_text_question("24th March (Tuesday).Mention Time from 10 am to 4pm...", personals, skills_exp) == "1:30 PM"
    assert resolve_text_question("What is your preferred timeslot for interview?", personals, skills_exp) == "1:30 PM"
    assert resolve_text_question("Are your available upcoming Saturday for first round", personals, skills_exp) == "Yes"
    assert resolve_text_question("Surely will u attend virtual interview on 24th March?", personals, skills_exp) == "Yes"

    # Education completion years (crucial: must not match skill experience numbers like 2)
    assert resolve_text_question("10th or diploma Which year completed? No Data Analytics...", personals, skills_exp) == "2016"
    assert resolve_text_question("12th or If done only Diploma please mention...", personals, skills_exp) == "2018"
    assert resolve_text_question("Ug or Bachelor or Graduation , If you done PG please mention graduation year", personals, skills_exp) == "2023"
    assert resolve_text_question("College duration (from - to years)", personals, skills_exp) == "2019 - 2023"

    # Personal details
    assert resolve_text_question("What is your current company name?", personals, skills_exp) == "Lemon Tree Hotels Limited"
    assert resolve_text_question("What is your current city / location?", personals, skills_exp) == "Gurugram"
    assert resolve_text_question("Highest qualification / degree", personals, skills_exp) == "B.Tech"

    # PAN Card / Government ID
    assert resolve_text_question("What is your PAN Card Number?", personals, skills_exp) == "HMDPK5264C"
    assert resolve_text_question("Please enter PAN number", personals, skills_exp) == "HMDPK5264C"

    # Ex-Employee & Prior Company Questions
    assert resolve_text_question("Are you ex-infosys employee ?if yes mention your id", personals, skills_exp) == "No"
    assert resolve_text_question("Have you worked in / applied to Deloitte earlier?...", personals, skills_exp) == "No"
    assert resolve_text_question("Have you worked for deloitte before", personals, skills_exp) == "No"
    assert resolve_text_question("Have you applied to Deloitte earlier?", personals, skills_exp) == "No"

    # Skill Affirmative & Quantitative Questions (DBT)
    assert resolve_text_question("Do you have experince with DBT", personals, skills_exp) == "Yes"
    assert resolve_text_question("Do you have experience with DBT?", personals, skills_exp) == "Yes"
    assert resolve_text_question("Have you worked with DBT?", personals, skills_exp) == "Yes"
    assert resolve_text_question("How many years of experience do you have with DBT?", personals, skills_exp) == "2"

    # Affirmative
    assert resolve_text_question("Are you comfortable working in Gurugram?", personals, skills_exp) == "Yes"

    # Quantitative questions with "do you have" must return experience years, NEVER "Yes"!
    assert resolve_text_question("How many years of hands-on experience do you have in Snowflake?", personals, skills_exp) == "3.5"
    assert resolve_text_question("How many years of hands-on experience do you have in Healthcare?", personals, skills_exp) == "3.5"
    assert resolve_text_question("How many years of eperience do you have in Real world projects?", personals, skills_exp) == "3.5"

    # Rating / Proficiency questions
    assert resolve_text_question("How strong is your Python experience?", personals, skills_exp) == "Advanced (3+ years)"
    assert resolve_text_question("Rate your Python experience (0-99)", personals, skills_exp, whole_number=True) == "8"

    # DOB & Timing & LWD
    assert resolve_text_question("What is your DOB?", personals, skills_exp) == "15/08/1999"
    assert resolve_text_question("Date of Birth...", personals, skills_exp) == "15/08/1999"
    assert resolve_text_question("Available timing...", personals, skills_exp) == "1:30 PM"
    assert resolve_text_question("what is Your LWD?...", personals, skills_exp) == "30 Days"

    # Fixed Annual CTC
    assert resolve_text_question("Current/Last Drawn Fixed (Annual)...", personals, skills_exp) == "13"

    # Documents (PF & Form 16)
    assert resolve_text_question("Do have PF & Form 16?(if Yes Please share the result)", personals, skills_exp) == "Yes"

    # Gaps & Educational percentage
    assert resolve_text_question("Do you have any gaps in education/career? If having please mention", personals, skills_exp) == "No"
    assert resolve_text_question("Whether your educational % is above 50 in the 10th...", personals, skills_exp) == "Yes"


def test_resolve_chip_choices():
    class DummyChip:
        def __init__(self, text):
            self.text = text

        def get_attribute(self, name):
            return self.text

    personals = {
        "total_experience_years": 3.5,
        "class_10_year": "2016",
        "class_12_year": "2018",
        "graduation_year": "2023",
        "preferred_interview_time": "1:30 PM",
    }

    # TCS Virtual Interview Radio Button Widget
    tcs_chips = [
        DummyChip("No - Not sure"),
        DummyChip("Yes will attend the virtual interview on 24th March (Tuesday)")
    ]
    chosen_tcs = resolve_chip_choice(
        "Surely will u attend virtual interview on 24th March (Tuesday)",
        tcs_chips,
        personals
    )
    assert chosen_tcs is not None
    assert chosen_tcs.text == "Yes will attend the virtual interview on 24th March (Tuesday)"

    # Notice period chips vs interview availability distinction
    chosen_avail = resolve_chip_choice(
        "Are you available upcoming Saturday for first round?",
        tcs_chips,
        personals
    )
    assert chosen_avail.text == "Yes will attend the virtual interview on 24th March (Tuesday)"

    # Notice period chips
    notice_chips = [DummyChip("3 Months"), DummyChip("2 Months"), DummyChip("1 Month"), DummyChip("Serving Notice")]
    chosen = resolve_chip_choice("what is your notice period?", notice_chips, personals)
    assert chosen.text == "1 Month"

    # Work preference / commute
    location_chips = [DummyChip("No"), DummyChip("Yes")]
    chosen_loc = resolve_chip_choice("Are you comfortable working from office in Gurugram?", location_chips, personals)
    assert chosen_loc.text == "Yes"

    # Education chips
    grad_chips = [DummyChip("2021"), DummyChip("2022"), DummyChip("2023"), DummyChip("2024")]
    chosen_grad = resolve_chip_choice("Which year did you complete your graduation / UG?", grad_chips, personals)
    assert chosen_grad.text == "2023"

    # CRITICAL: Empty chips must be completely ignored and never selected!
    chips_with_empty = [DummyChip(""), DummyChip("   "), DummyChip("Yes"), DummyChip("No")]
    chosen_non_empty = resolve_chip_choice("Are you willing to relocate?", chips_with_empty, personals)
    assert chosen_non_empty.text == "Yes"

    # All empty chips should return None
    all_empty = [DummyChip(""), DummyChip("   ")]
    assert resolve_chip_choice("Any question?", all_empty, personals) is None

    # CRITICAL: Skip options must be filtered out and never selected
    chips_with_skip = [DummyChip("Skip this question"), DummyChip("3-5 years"), DummyChip("<4 years")]
    chosen_skip = resolve_chip_choice("How many years of experience do you have in Snowflake?", chips_with_skip, personals)
    assert chosen_skip is not None
    assert chosen_skip.text == "3-5 years"

    # If only skip option is present, resolve_chip_choice must return None so text input can be filled
    only_skip = [DummyChip("Skip this question"), DummyChip("Skip")]
    assert resolve_chip_choice("Describe your past projects", only_skip, personals) is None


def test_find_naukri_apply_button_excludes_save():
    class DummyButton:
        def __init__(self, text, cls="", btn_id=""):
            self.text = text
            self.cls = cls
            self.btn_id = btn_id

        def is_displayed(self):
            return True

        def get_attribute(self, name):
            if name == "class":
                return self.cls
            if name == "id":
                return self.btn_id
            return None

    class DummyDriver:
        def __init__(self, buttons):
            self.buttons = buttons

        def find_element(self, by, val):
            raise Exception("No ID")

        def find_elements(self, by, val):
            return self.buttons

    # Scenario: Container has both Save and Apply buttons
    save_btn = DummyButton(text="Save", cls="styles_save-job-button")
    apply_btn = DummyButton(text="Apply", cls="styles_apply-button")

    driver = DummyDriver([save_btn, apply_btn])
    result = find_naukri_apply_button(driver)

    assert result is not None
    assert result.text == "Apply"


def test_is_location_match():
    targets = ["Gurgaon", "Noida", "Delhi / NCR"]

    # Matching locations
    assert is_location_match("Gurugram", targets) is True
    assert is_location_match("Gurgaon, Haryana", targets) is True
    assert is_location_match("Noida, Uttar Pradesh", targets) is True
    assert is_location_match("Delhi / NCR", targets) is True
    assert is_location_match("Hybrid - Gurugram, Noida", targets) is True
    assert is_location_match("Remote", targets) is True
    assert is_location_match("Work from home", targets) is True

    # Non-matching locations for Delhi NCR
    assert is_location_match("Pune", targets) is False
    assert is_location_match("Bengaluru / Bangalore", targets) is False
    assert is_location_match("Hyderabad", targets) is False
    assert is_location_match("Mumbai", targets) is False

    # Secondary Tech Hub targets
    fallback_targets = ["Bengaluru", "Hyderabad", "Pune", "Mumbai"]
    assert is_location_match("Bengaluru", fallback_targets) is True
    assert is_location_match("Bangalore", fallback_targets) is True
    assert is_location_match("Hyderabad, Telangana", fallback_targets) is True
    assert is_location_match("Secunderabad", fallback_targets) is True
    assert is_location_match("Pune, Maharashtra", fallback_targets) is True
    assert is_location_match("Navi Mumbai", fallback_targets) is True
    assert is_location_match("Thane", fallback_targets) is True
    assert is_location_match("Remote", fallback_targets) is True
    assert is_location_match("Noida", fallback_targets) is False

    # Pan-India targets
    assert is_location_match("Kolkata", ["All India"]) is True
    assert is_location_match("Ahmedabad", ["Pan India"]) is True


def test_handle_drawer_resume_prompt():
    from chatbot_handler import handle_drawer_resume_prompt

    class DummyElem:
        def __init__(self, text=""):
            self.text = text
            self.clicked = False

        def is_displayed(self):
            return True

        def click(self):
            self.clicked = True

    class DummyDrawer:
        def __init__(self, prompt_text="Upload Resume\nI'll do it later", later_text="I'll do it later"):
            self.prompt_elem = DummyElem(prompt_text)
            self.later_elem = DummyElem(later_text)

        def find_elements(self, by, val):
            if "later" in val:
                return [self.later_elem]
            if "upload resume" in val:
                return [self.prompt_elem]
            return []

    class DummyDriver:
        def __init__(self):
            self.script_clicked = []

        def find_elements(self, by, val):
            return []

        def execute_script(self, script, elem):
            self.script_clicked.append(elem)

    drawer = DummyDrawer()
    driver = DummyDriver()
    config = {"personals": {"default_resume_path": ""}}

    handled = handle_drawer_resume_prompt(driver, drawer, config)
    assert handled is True
    assert drawer.later_elem in driver.script_clicked


def test_check_apply_success_redirect_and_elements():
    class DummyElem:
        def __init__(self, text="", cls=""):
            self.text = text
            self.cls = cls

        def is_displayed(self):
            return True

        def get_attribute(self, name):
            if name == "class":
                return self.cls
            return ""

    class DummyDriver:
        def __init__(self, url="https://www.naukri.com/job-listings", elements=None, page_source=""):
            self.current_url = url
            self.elements = elements or []
            self.page_source = page_source

        def find_elements(self, by, val):
            return self.elements

    # Scenario 1: URL redirected to myapply/saveApply
    driver_url = DummyDriver(url="https://www.naukri.com/myapply/saveApply?multiApplyResp=%7B%22123%22%3A200%7D")
    assert check_apply_success(driver_url) is True

    # Scenario 2: Span with already-applied class and Applied text
    span_applied = DummyElem(text="Applied", cls="styles_already-applied__4KDhw already-applied")
    driver_span = DummyDriver(elements=[span_applied])
    assert check_apply_success(driver_span) is True

    # Scenario 3: Div with applied-job-content
    div_applied = DummyElem(text='Applied to "Data Engineer"', cls="applied-job-content")
    driver_div = DummyDriver(elements=[div_applied])
    assert check_apply_success(driver_div) is True


def test_get_valid_chips_radios():
    from chatbot_handler import get_valid_chips

    class DummyChipElem:
        def __init__(self, text="", cls="", child_radios=0):
            self.text = text
            self.cls = cls
            self.child_radios = child_radios

        def is_displayed(self):
            return True

        def get_attribute(self, name):
            if name == "class":
                return self.cls
            if name == "innerText":
                return self.text
            return ""

        def find_elements(self, by, val):
            if "botMsg" in val:
                return []
            if "input[@type='radio']" in val:
                return [1] * self.child_radios
            return []

    class DummyDrawer:
        def __init__(self, chips):
            self.chips = chips

        def find_elements(self, by, val):
            return self.chips

    # Container that wraps multiple radios (should be excluded)
    wrapper = DummyChipElem(
        text="No - Not sure Yes will attend",
        cls="singleselect-radiobutton-container",
        child_radios=2
    )
    # Individual options (should be included)
    radio_no = DummyChipElem(text="No - Not sure", cls="ssrc__label", child_radios=0)
    radio_yes = DummyChipElem(
        text="Yes will attend the virtual interview on 24th March (Tuesday)",
        cls="ssrc__label",
        child_radios=0
    )

    # Skip options (should be excluded)
    chip_skip1 = DummyChipElem(text="Skip this question", cls="chip", child_radios=0)
    chip_skip2 = DummyChipElem(text="Skip", cls="chip", child_radios=0)

    drawer = DummyDrawer([wrapper, radio_no, radio_yes, chip_skip1, chip_skip2])
    valid = get_valid_chips(drawer)

    assert len(valid) == 2
    assert valid[0].text == "No - Not sure"
    assert valid[1].text == "Yes will attend the virtual interview on 24th March (Tuesday)"


def test_check_apply_error():
    from chatbot_handler import check_apply_error

    class DummyElem:
        def __init__(self, text=""):
            self.text = text

        def is_displayed(self):
            return True

    class DummyDriverWithError:
        def __init__(self, err_text="", page_source=""):
            self._err_text = err_text
            self.page_source = page_source

        def find_elements(self, by, val):
            if self._err_text:
                return [DummyElem(self._err_text)]
            return []

    # Scenario 1: Visible error element with Naukri rate limit text
    d1 = DummyDriverWithError(err_text="There was an error while processing your request, please try again later")
    has_err, msg = check_apply_error(d1)
    assert has_err is True
    assert "error while processing your request" in msg

    # Scenario 2: Page source contains daily limit phrase
    d2 = DummyDriverWithError(page_source="<div>Daily application limit reached for your account.</div>")
    has_err, msg = check_apply_error(d2)
    assert has_err is True
    assert "Daily application limit" in msg

    # Scenario 3: Clean page with no errors
    d3 = DummyDriverWithError(page_source="<div>Application submitted successfully</div>")
    has_err, msg = check_apply_error(d3)
    assert has_err is False


def test_handle_drawer_checkboxes():
    from chatbot_handler import handle_drawer_checkboxes

    class DummyCheckbox:
        def __init__(self, selected=False):
            self._selected = selected
            self.clicked = False

        def is_displayed(self):
            return True

        def is_selected(self):
            return self._selected

        def find_elements(self, by, val):
            return []

        def get_attribute(self, name):
            if name == "type":
                return "checkbox"
            return ""

    class DummyButton:
        def __init__(self, text="Save"):
            self.text = text
            self.clicked = False

        def is_displayed(self):
            return True

        def get_attribute(self, name):
            return ""

        def click(self):
            self.clicked = True

    class DummyDrawerWithCheckboxes:
        def __init__(self, checkboxes, send_btn=None):
            self.checkboxes = checkboxes
            self.send_btn = send_btn

        def find_elements(self, by, val):
            if "checkbox" in val and "input" in val:
                return self.checkboxes
            if "send" in val or "button" in val:
                return [self.send_btn] if self.send_btn else []
            return []

    class DummyDriver:
        def execute_script(self, script, *args):
            if "click" in script and args:
                args[0].clicked = True

        def find_elements(self, by, xpath):
            return []

    cb1 = DummyCheckbox(selected=False)
    cb2 = DummyCheckbox(selected=False)
    save_btn = DummyButton(text="Save")
    drawer = DummyDrawerWithCheckboxes([cb1, cb2], send_btn=save_btn)
    driver = DummyDriver()

    result = handle_drawer_checkboxes(driver, drawer, "Pick available location with multiple locations", {})
    assert result is True
    assert cb1.clicked is True
    assert cb2.clicked is True
    assert save_btn.clicked is True


def test_engage_header_notifications():
    from profile_booster import engage_header_notifications

    class DummyNotifElem:
        def __init__(self, text="Application viewed", is_unread=True):
            self.text = text
            self.is_unread = is_unread
            self.classes = "nI-gNb-ncr__menu-item nI-gNb-ncr__menu-item-unread" if is_unread else "nI-gNb-ncr__menu-item"

        def is_displayed(self):
            return True

        def get_attribute(self, name):
            if name == "class":
                return self.classes
            return ""

        def find_elements(self, by, val):
            return []

    class DummyUl:
        def __init__(self, items):
            self.items = items

        def is_displayed(self):
            return True

        def find_elements(self, by, val):
            if "./li" in val or "li" in val:
                return self.items
            return []

    class DummyDriver:
        def __init__(self):
            self.current_url = "https://www.naukri.com/mnjuser/homepage"
            self.visited_urls = []
            self.script_calls = []
            self.items = [
                DummyNotifElem("Your resume was viewed by Accenture", is_unread=True),
                DummyNotifElem("Your application was shortlisted by Microsoft", is_unread=False),
            ]

        def get(self, url):
            self.visited_urls.append(url)
            self.current_url = url

        def find_elements(self, by, val):
            if "icon-wrapper" in val or "Notifications" in val or "div[4]/button" in val:
                return [DummyNotifElem("BellButton")]
            if "naukri-drawer" in val or "div[4]/div" in val or "notif" in val:
                return [DummyUl(self.items)]
            if "close" in val or "cross" in val:
                return [DummyNotifElem("CloseBtn")]
            return []

        def execute_script(self, script, *args):
            self.script_calls.append(script)

    driver = DummyDriver()
    count = engage_header_notifications(driver, max_taps=2)
    assert count == 2
    assert any("mouseover" in call for call in driver.script_calls)
    assert any("scrollIntoView" in call for call in driver.script_calls)
    assert any("click" in call for call in driver.script_calls)


def test_open_recruiter_menu_and_click_link():
    from profile_booster import open_recruiter_menu_and_click_link

    class DummyElem:
        def __init__(self, text=""):
            self.text = text
            self.clicked = False

        def is_displayed(self):
            return True

        def find_elements(self, by, val):
            if "badge" in val:
                return [DummyElem("2")]
            return []

    class DummyDriver:
        def __init__(self, has_button=True):
            self.has_button = has_button
            self.visited_urls = []
            self.script_calls = []

        def get(self, url):
            self.visited_urls.append(url)

        def find_elements(self, by, val):
            if self.has_button and ("div[5]/button" in val or "drawer__icon" in val):
                return [DummyElem("MenuBtn")]
            if self.has_button and ("div[1]/a" in val or "performance" in val):
                return [DummyElem("Link21")]
            return []

        def execute_script(self, script, *args):
            self.script_calls.append(script)

    # When menu button and link are present in header
    driver_with_drawer = DummyDriver(has_button=True)
    clicked = open_recruiter_menu_and_click_link(
        driver_with_drawer,
        link_xpath="/html/body/div[3]/div[2]/div[5]/div/div[2]/div/div[3]/div[2]/div[1]/a",
        fallback_url="https://www.naukri.com/mnjuser/performance",
        link_label="Search Appearances (2.1)"
    )
    assert clicked is True
    assert len(driver_with_drawer.script_calls) == 2  # Clicked button 2, then link 2.1

    # When menu button is absent, gracefully falls back to direct URL
    driver_fallback = DummyDriver(has_button=False)
    clicked_fallback = open_recruiter_menu_and_click_link(
        driver_fallback,
        link_xpath="/html/body/div[3]/div[2]/div[5]/div/div[2]/div/div[3]/div[2]/div[1]/a",
        fallback_url="https://www.naukri.com/mnjuser/performance",
        link_label="Search Appearances (2.1)"
    )
    assert clicked_fallback is False
    assert "https://www.naukri.com/mnjuser/performance" in driver_fallback.visited_urls


def test_engage_performance_and_search_appearances():
    from profile_booster import engage_performance_and_search_appearances

    class DummyElem:
        def __init__(self, text=""):
            self.text = text
            self.clicked = False

        def is_displayed(self):
            return True

        def get_attribute(self, name):
            return ""

        def find_elements(self, by, val):
            return []

    class DummyDriver:
        def __init__(self):
            self.current_url = "https://www.naukri.com/mnjuser/homepage"
            self.visited_urls = []
            self.script_calls = []

        def get(self, url):
            self.visited_urls.append(url)
            self.current_url = url

        def find_elements(self, by, val):
            if "DownArrow" in val:
                return [DummyElem("Dropdown")]
            if "summary-card" in val or "search-appearances-card" in val:
                return [DummyElem("77 Search appearances | Top keywords: Python, Data Engineer")]
            return []

        def execute_script(self, script, *args):
            self.script_calls.append(script)

    driver = DummyDriver()
    stats = engage_performance_and_search_appearances(driver)
    assert "https://www.naukri.com/mnjuser/performance" in driver.visited_urls
    assert "77 Search appearances" in stats.get("summary", "")


def test_engage_recruiter_actions():
    from profile_booster import engage_recruiter_actions

    class DummyElem:
        def __init__(self, text="Load more"):
            self.text = text
            self.clicked = False

        def is_displayed(self):
            return True

        def get_attribute(self, name):
            return "load-more-button"

        def find_elements(self, by, val):
            return []

    class DummyDriver:
        def __init__(self):
            self.current_url = "https://www.naukri.com/mnjuser/homepage"
            self.visited_urls = []
            self.script_calls = []

        def get(self, url):
            self.visited_urls.append(url)
            self.current_url = url

        def find_elements(self, by, val):
            if "load-more-button" in val or "LOAD MORE" in val:
                return [DummyElem()]
            return []

        def execute_script(self, script, *args):
            self.script_calls.append(script)

    driver = DummyDriver()
    engage_recruiter_actions(driver)
    assert "https://www.naukri.com/mnjuser/performance#recruiterActions" in driver.visited_urls


def test_share_interest_early_access_roles():
    from profile_booster import share_interest_early_access_roles

    class DummyCard:
        def __init__(self, text="Data Engineer at Microsoft"):
            self.text = text

    class DummyButton:
        def __init__(self, text="Share Interest"):
            self.text = text

        def is_displayed(self):
            return True

        def find_element(self, by, val):
            return DummyCard("Data Engineer | Microsoft")

    class DummyDriver:
        def __init__(self):
            self.visited_urls = []
            self.script_calls = []
            self.call_count = 0

        def get(self, url):
            self.visited_urls.append(url)

        def find_elements(self, by, val):
            self.call_count += 1
            if "SHARE INTEREST" in val or "recommended" in val or "ear-jobs" in val or "section" in val:
                if self.call_count <= 4:
                    return [DummyButton("Share Interest")]
            return []

        def execute_script(self, script, *args):
            self.script_calls.append(script)

    driver = DummyDriver()
    shared = share_interest_early_access_roles(driver, max_shares=2)
    assert "https://www.naukri.com/mnjuser/recommended-earjobs" in driver.visited_urls
    assert shared == 2


def test_sanitize_whole_number():
    assert sanitize_whole_number("3.5") == "3"
    assert sanitize_whole_number(3.5) == "3"
    assert sanitize_whole_number("30 Days") == "30"
    assert sanitize_whole_number("1 Month") == "1"
    assert sanitize_whole_number("13 LPA") == "13"
    assert sanitize_whole_number("0") == "0"
    assert sanitize_whole_number("99") == "99"
    assert sanitize_whole_number("150") == "99"
    assert sanitize_whole_number("-5") == "0"
    assert sanitize_whole_number("") == "3"
    assert sanitize_whole_number(None) == "3"


def test_is_whole_number_required():
    class DummyElem:
        def __init__(self, elem_type="text", step=None, placeholder=""):
            self.elem_type = elem_type
            self.step = step
            self.placeholder = placeholder

        def get_attribute(self, name):
            if name == "type":
                return self.elem_type
            if name == "step":
                return self.step
            if name == "placeholder":
                return self.placeholder
            return ""

    num_inp = DummyElem(elem_type="number")
    assert is_whole_number_required(input_elem=num_inp) is True

    step_inp = DummyElem(elem_type="text", step="1")
    assert is_whole_number_required(input_elem=step_inp) is True

    text_inp = DummyElem(elem_type="text", placeholder="Enter whole number between 0 and 99")
    assert is_whole_number_required(input_elem=text_inp) is True

    # Question text checking
    assert is_whole_number_required(question="Enter a whole number between 0 and 99") is True
    assert is_whole_number_required(question="Total years of experience in Python (0-99)") is True


def test_resolve_text_question_whole_number_mode():
    personals = {
        "total_experience_years": 3.5,
        "current_ctc_lpa": 13,
        "expected_ctc_lpa": 18,
        "notice_period_days": 30,
    }
    skills_exp = {"python": 3, "spark": 3}

    # When whole_number is required or requested in prompt
    assert resolve_text_question("Total years of experience", personals, skills_exp, whole_number=True) == "3"
    assert resolve_text_question("Enter a whole number between 0 and 99 for experience", personals, skills_exp) == "3"
    assert resolve_text_question("Notice period in days (0-99)", personals, skills_exp) == "30"
    assert resolve_text_question("Current CTC (whole number between 0 and 99)", personals, skills_exp) == "13"


def test_fill_text_input_whole_number_autocorrect():
    class DummyInput:
        def __init__(self, elem_type="text"):
            self.elem_type = elem_type
            self.value = ""
            self.keys_sent = []

        def get_attribute(self, name):
            if name == "type":
                return self.elem_type
            if name == "contenteditable":
                return "false"
            if name == "value":
                return self.value
            return ""

        def click(self):
            pass

        def send_keys(self, *keys):
            for k in keys:
                self.keys_sent.append(str(k))
            self.value = "".join([k for k in self.keys_sent if len(k) == 1 or k.isdigit() or "." in k])

        def clear(self):
            self.value = ""

    class DummyError:
        def __init__(self, text):
            self.text = text

        def is_displayed(self):
            return True

    class DummyDrawerWithValidationError:
        def __init__(self, err_text=""):
            self.err_text = err_text

        def find_elements(self, by, val):
            if "err" in val or "error" in val:
                if self.err_text:
                    return [DummyError(self.err_text)]
            return []

    class DummyDriver:
        def execute_script(self, script, *args):
            pass

    # Scenario: Number input receives "3.5", should automatically sanitize to "3"
    driver = DummyDriver()
    drawer = DummyDrawerWithValidationError()
    input_elem = DummyInput(elem_type="number")

    success = fill_text_input(driver, drawer, input_elem, answer_text="3.5", question="Total experience")
    assert success is True
    assert "3" in input_elem.keys_sent


def test_record_screening_question(tmp_path):
    import json
    from chatbot_handler import record_screening_question

    test_file = str(tmp_path / "test_questions.json")

    record_screening_question(
        job_title="Snowflake Data Engineer",
        company="skills bridge",
        question="How many years of experience do you have in Snowflake?",
        field_type="text",
        answer="3.5",
        options=[],
        status="answered",
        filepath=test_file
    )

    record_screening_question(
        job_title="Snowflake Data Engineer",
        company="skills bridge",
        question="Do you have strong hands-on experience in KPI cataloging?",
        field_type="chip_choice",
        answer="Yes",
        options=["Yes", "No"],
        status="answered",
        filepath=test_file
    )

    with open(test_file, "r", encoding="utf-8") as f:
        records = json.load(f)

    assert len(records) == 2
    assert records[0]["job_title"] == "Snowflake Data Engineer"
    assert records[0]["answer"] == "3.5"
    assert records[1]["answer"] == "Yes"
    assert records[1]["options"] == ["Yes", "No"]


def test_get_question_for_chip():
    from chatbot_handler import get_question_for_chip

    class DummyElem:
        def __init__(self, text=""):
            self.text = text

        def get_attribute(self, name):
            return self.text

    class DummyContainer:
        def __init__(self, text=""):
            self.text = text

        def find_elements(self, by, val):
            return [DummyElem(text=self.text)]

    class DummyChipTarget:
        def __init__(self, container_text=""):
            self.container_text = container_text

        def find_elements(self, by, val):
            if "ancestor" in val:
                return [DummyContainer(self.container_text)]
            return []

    chip = DummyChipTarget("How many years of experience do you have in Data Quality?")
    q = get_question_for_chip(chip)
    assert q == "How many years of experience do you have in Data Quality?"


def test_format_and_log_run_summary(tmp_path):
    from job_applier import format_and_log_run_summary

    test_summary_file = str(tmp_path / "test_run_summary.md")
    jobs = [
        {
            "title": "Data Engineer",
            "company": "Siemens Healthcare",
            "location": "Bengaluru",
            "url": "https://www.naukri.com/job-listings-siemens-12345",
        },
        {
            "title": "GCP Data Engineer",
            "company": "Dentsu Webchutney",
            "location": "Pune, Mumbai, New Delhi",
            "url": "https://www.naukri.com/job-listings-dentsu-67890",
        },
    ]

    md_content = format_and_log_run_summary(jobs, summary_file=test_summary_file)

    assert "# 🚀 Naukri Auto Apply - Run Summary" in md_content
    assert "Total Applications in this Run**: `2`" in md_content
    assert "| 1 | Data Engineer | Siemens Healthcare | Bengaluru | [Open on Naukri](https://www.naukri.com/job-listings-siemens-12345) |" in md_content
    assert "| 2 | GCP Data Engineer | Dentsu Webchutney | Pune, Mumbai, New Delhi | [Open on Naukri](https://www.naukri.com/job-listings-dentsu-67890) |" in md_content

    # Verify file was written
    assert os.path.exists(test_summary_file)
    with open(test_summary_file, "r", encoding="utf-8") as f:
        file_text = f.read()
    assert file_text == md_content

    # Test empty list scenario
    empty_file = str(tmp_path / "empty_summary.md")
    empty_content = format_and_log_run_summary([], summary_file=empty_file)
    assert "Total Applications in this Run**: `0`" in empty_content
    assert "No jobs were applied to in this run" in empty_content


def test_hide_and_submit_recommendation_reason():
    from profile_booster import hide_and_submit_recommendation_reason

    class DummyElem:
        def __init__(self, text=""):
            self.text = text
            self.clicked = False

        def is_displayed(self):
            return True

        def find_elements(self, by, val):
            if "Tell Us Why" in val:
                return [DummyElem("Tell Us Why")]
            if "check-item" in val and "Experience" in val:
                return [DummyElem("Experience")]
            if "submit-feedback" in val or "Submit" in val:
                return [DummyElem("Submit")]
            return []

    class DummyCard:
        def __init__(self):
            self.text = "Data Engineer 8-15 Yrs"

        def find_elements(self, by, val):
            if "Hide" in val:
                return [DummyElem("Hide")]
            if "Tell Us Why" in val:
                return [DummyElem("Tell Us Why")]
            if "check-item" in val and "Experience" in val:
                return [DummyElem("Experience")]
            if "submit-feedback" in val or "Submit" in val:
                return [DummyElem("Submit")]
            return []

    class DummyDriver:
        def __init__(self):
            self.script_calls = []

        def execute_script(self, script, *args):
            self.script_calls.append(script)

    driver = DummyDriver()
    card = DummyCard()
    success = hide_and_submit_recommendation_reason(driver, card, reason="Experience")
    assert success is True
    assert any("scrollIntoView" in call for call in driver.script_calls)
    assert any("click" in call for call in driver.script_calls)


def test_optimize_and_apply_recommended_jobs():
    from profile_booster import optimize_and_apply_recommended_jobs

    class DummyCardElem:
        def __init__(self, text=""):
            self.text = text

        def get_attribute(self, name):
            if name == "data-job-id":
                return "12345"
            return ""

        def find_elements(self, by, val):
            if "title" in val:
                return [DummyCardElem("Senior QA Automation Lead")]  # Bad title: fails is_title_relevant
            if "subTitle" in val or "company" in val:
                return [DummyCardElem("SomeCorp")]
            if "ellipsis" in val and "valignM" in val:
                return [DummyCardElem("3-5 Yrs"), DummyCardElem("Gurgaon")]
            if "Hide" in val:
                return [DummyCardElem("Hide")]
            if "Tell Us Why" in val:
                return [DummyCardElem("Tell Us Why")]
            if "check-item" in val and "Job role" in val:
                return [DummyCardElem("Job role")]
            if "submit-feedback" in val:
                return [DummyCardElem("Submit")]
            return []

    class DummyDriver:
        def __init__(self):
            self.visited_urls = []
            self.script_calls = []
            self.card = DummyCardElem()

        def get(self, url):
            self.visited_urls.append(url)

        def find_elements(self, by, val):
            if "tab-wrapper" in val or "tab-list-item" in val:
                return [DummyCardElem("Top Candidate")]
            if "jobTuple" in val:
                return [self.card]
            return []

        def execute_script(self, script, *args):
            self.script_calls.append(script)

    dummy_config = {
        "search": {
            "title_bad_words": ["QA", "Lead"],
            "title_mandatory_words": ["Engineer"],
            "min_experience": 1,
            "max_experience": 6,
            "max_experience_stretch": 1.5,
            "locations": ["Gurgaon"],
        },
        "personals": {
            "total_experience_years": 3.5,
        },
        "settings": {},
    }

    driver = DummyDriver()
    summary = optimize_and_apply_recommended_jobs(driver, dummy_config, max_cards_per_tab=1)
    assert "https://www.naukri.com/mnjuser/recommendedjobs" in driver.visited_urls
    assert summary["hidden"] >= 1
    assert summary["reasons"]["Job role"] >= 1


def test_handle_drawer_checkboxes_dbt_and_deloitte():
    class MockElement:
        def __init__(self, text="", tag="div", elem_type=None, elem_id=""):
            self.text = text
            self.tag_name = tag
            self._type = elem_type
            self._id = elem_id
            self.checked = False
            self.clicked = False

        def get_attribute(self, name):
            if name == "type":
                return self._type
            if name == "id":
                return self._id
            if name in ["innerText", "aria-label", "value"]:
                return self.text
            return None

        def is_displayed(self):
            return True

        def find_elements(self, by, xpath):
            return []

    class MockCheckbox(MockElement):
        def __init__(self, text, elem_id=""):
            super().__init__(text=text, tag="input", elem_type="checkbox", elem_id=elem_id)

    class MockDrawer:
        def __init__(self, checkboxes, send_btn=None):
            self.checkboxes = checkboxes
            self.send_btn = send_btn or MockElement(text="Save")

        def find_elements(self, by, xpath):
            if "input[@type='checkbox']" in xpath:
                return self.checkboxes
            return []

    class MockDriver:
        def __init__(self):
            self.executed_scripts = []

        def execute_script(self, script, *args):
            self.executed_scripts.append(script)
            if "arguments[0].checked = true" in script and args:
                args[0].checked = True
            elif "arguments[0].checked = false" in script and args:
                args[0].checked = False
            elif "arguments[0].click()" in script and args:
                args[0].clicked = True

        def find_elements(self, by, xpath):
            return []

    personals = {"target_locations": ["Gurugram", "Noida", "Delhi / NCR"]}

    # Test 1: DBT question with 3 checkboxes: "Yes", "No", "Skip this question"
    # Must check "Yes" ONLY and leave "Skip this question" and "No" UNCHECKED!
    cb_yes = MockCheckbox("Yes", "cb_yes")
    cb_no = MockCheckbox("No", "cb_no")
    cb_skip = MockCheckbox("Skip this question", "cb_skip")
    drawer = MockDrawer([cb_yes, cb_no, cb_skip])
    driver = MockDriver()

    res = handle_drawer_checkboxes(driver, drawer, "Have you worked in DBT (Data Build Tool)?", personals)
    assert res is True
    assert cb_yes.checked is True
    assert cb_no.checked is False
    assert cb_skip.checked is False

    # Test 2: Deloitte prior employment question with "Yes", "No", "Skip this question"
    # Must check "No" ONLY and leave "Yes" and "Skip this question" UNCHECKED!
    cb_yes2 = MockCheckbox("Yes", "cb_yes2")
    cb_no2 = MockCheckbox("No", "cb_no2")
    cb_skip2 = MockCheckbox("Skip this question", "cb_skip2")
    drawer2 = MockDrawer([cb_yes2, cb_no2, cb_skip2])
    driver2 = MockDriver()

    res2 = handle_drawer_checkboxes(driver2, drawer2, "Have you worked in / applied to Deloitte earlier?", personals)
    assert res2 is True
    assert cb_yes2.checked is False
    assert cb_no2.checked is True
    assert cb_skip2.checked is False


def test_company_priority_classification():
    from external_job_tracker import get_company_priority

    # Tier 1 checks
    assert get_company_priority("Google")[0] == 1
    assert get_company_priority("Boston Consulting Group")[0] == 1
    assert get_company_priority("BCG")[0] == 1
    assert get_company_priority("Databricks India")[0] == 1
    assert get_company_priority("Apple India Pvt Ltd")[0] == 1
    assert get_company_priority("JPMorgan Chase Bank")[0] == 1

    # Tier 2 checks
    assert get_company_priority("Accenture Solutions Pvt Ltd")[0] == 2
    assert get_company_priority("EY")[0] == 2
    assert get_company_priority("Ernst & Young LLP")[0] == 2
    assert get_company_priority("PwC Service Delivery Center")[0] == 2
    assert get_company_priority("Fractal Analytics")[0] == 2
    assert get_company_priority("Barclays")[0] == 2
    assert get_company_priority("Infosys")[0] == 2

    # Tier 3 (unlisted) checks
    assert get_company_priority("Unknown Startup LLP")[0] == 3
    assert get_company_priority("Random Consultancy Services")[0] == 3

    # Word boundary checks to avoid false positives
    # e.g., 'EY' should not match 'Keyence' or 'Survey'
    assert get_company_priority("Keyence Corporation")[0] == 3
    assert get_company_priority("SurveySparrow")[0] == 3
    # 'BCG' should not match 'Abcgroup'
    assert get_company_priority("Abcgroup Technologies")[0] == 3


def test_record_external_job_and_deduplication(tmp_path):
    from external_job_tracker import record_external_job, load_external_jobs

    csv_file = str(tmp_path / "test_external_jobs.csv")
    md_file = str(tmp_path / "test_external_jobs.md")
    cfg = {"company_priority": {"tier_1_companies": ["Google", "BCG"], "tier_2_companies": ["Accenture"]}}

    # Record first job
    res1 = record_external_job(
        config=cfg,
        job_id="job_001",
        title="Senior Data Engineer",
        company="Google",
        location="Gurugram",
        experience="3-6 Yrs",
        external_url="https://careers.google.com/jobs/1",
        naukri_url="https://naukri.com/job-1",
        status="Pending",
        csv_path=csv_file,
        md_path=md_file,
    )
    assert res1["Priority Tier"] == "Tier 1 (High)"
    assert res1["Priority Score"] == "1"

    # Deduplication test: recording with same job_id should return {} and not add a new row
    res_dup = record_external_job(
        config=cfg,
        job_id="job_001",
        title="Senior Data Engineer",
        company="Google",
        location="Gurugram",
        experience="3-6 Yrs",
        external_url="https://careers.google.com/jobs/1",
        naukri_url="https://naukri.com/job-1",
        status="Pending",
        csv_path=csv_file,
        md_path=md_file,
    )
    assert res_dup == {}

    jobs = load_external_jobs(csv_file)
    assert len(jobs) == 1

    # Record second job (Tier 2)
    res2 = record_external_job(
        config=cfg,
        job_id="job_002",
        title="Data Platform Engineer",
        company="Accenture",
        location="Noida",
        experience="2-5 Yrs",
        external_url="https://accenture.com/job-2",
        naukri_url="https://naukri.com/job-2",
        status="Pending",
        csv_path=csv_file,
        md_path=md_file,
    )
    assert res2["Priority Tier"] == "Tier 2 (Medium)"

    jobs = load_external_jobs(csv_file)
    assert len(jobs) == 2


def test_external_jobs_markdown_sorting(tmp_path):
    from external_job_tracker import record_external_job

    csv_file = str(tmp_path / "test_sort_jobs.csv")
    md_file = str(tmp_path / "test_sort_jobs.md")
    cfg = {"company_priority": {"tier_1_companies": ["Google"], "tier_2_companies": ["Accenture"]}}

    # Insert Tier 3 first
    record_external_job(
        config=cfg,
        job_id="job_t3",
        title="Data Engineer",
        company="Random Corp",
        location="Delhi",
        experience="3 Yrs",
        external_url="https://random.com/apply",
        naukri_url="https://naukri.com/job-t3",
        status="Pending",
        csv_path=csv_file,
        md_path=md_file,
    )

    # Insert Tier 1
    record_external_job(
        config=cfg,
        job_id="job_t1",
        title="Lead Big Data Engineer",
        company="Google",
        location="Gurugram",
        experience="5 Yrs",
        external_url="https://google.com/apply",
        naukri_url="https://naukri.com/job-t1",
        status="Pending",
        csv_path=csv_file,
        md_path=md_file,
    )

    with open(md_file, "r", encoding="utf-8") as f:
        md_content = f.read()

    # Tier 1 section must appear before Tier 3 in markdown!
    t1_pos = md_content.find("Tier 1: High Priority")
    t3_pos = md_content.find("Tier 3: Standard Priority")
    assert t1_pos != -1
    assert t3_pos != -1
    assert t1_pos < t3_pos
    assert "Google" in md_content
    assert "Random Corp" in md_content


def test_resolve_external_url_direct_href():
    from external_job_tracker import resolve_external_url

    class MockButton:
        def __init__(self, href=None, data_href=None):
            self.href = href
            self.data_href = data_href

        def get_attribute(self, attr):
            if attr == "href":
                return self.href
            if attr == "data-href":
                return self.data_href
            return None

    btn1 = MockButton(href="https://careers.google.com/jobs/results/12345")
    assert resolve_external_url(None, btn1, "https://naukri.com/fallback") == "https://careers.google.com/jobs/results/12345"

    # Button with naukri href should fallback if no driver
    btn2 = MockButton(href="https://www.naukri.com/company-site-redirect")
    assert resolve_external_url(None, btn2, "https://naukri.com/fallback") == "https://naukri.com/fallback"


def test_resolve_external_url_tab_redirection():
    from external_job_tracker import resolve_external_url

    class MockElement:
        def get_attribute(self, attr):
            return None

    class MockDriver:
        def __init__(self):
            self.window_handles = ["win1"]
            self.current_window_handle = "win1"
            self.current_url = "https://www.naukri.com/job-123"

        def execute_script(self, script, elem):
            # Simulate click opening a new tab
            self.window_handles.append("win2")

        def switch_to_window(self, win):
            self.current_window_handle = win
            if win == "win2":
                self.current_url = "https://ey.wd3.myworkdayjobs.com/en-US/EY_Careers/job/123"

        @property
        def switch_to(self):
            class SwitchTo:
                def __init__(self, d):
                    self.d = d
                def window(self, win):
                    self.d.switch_to_window(win)
            return SwitchTo(self)

        def close(self):
            if self.current_window_handle in self.window_handles:
                self.window_handles.remove(self.current_window_handle)

    driver = MockDriver()
    elem = MockElement()
    resolved = resolve_external_url(driver, elem, "https://www.naukri.com/fallback")
    assert resolved == "https://ey.wd3.myworkdayjobs.com/en-US/EY_Careers/job/123"
    assert driver.current_window_handle == "win1"
    assert len(driver.window_handles) == 1


def test_backfill_external_jobs(tmp_path):
    import csv
    from external_job_tracker import backfill_external_jobs_from_applied_csv, load_external_jobs

    src_csv = str(tmp_path / "mock_applied_jobs.csv")
    dest_csv = str(tmp_path / "mock_external_jobs.csv")

    with open(src_csv, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Date", "Job ID", "Title", "Company", "Location", "Status", "Job URL"])
        writer.writerow(["2026-10-01 10:00:00", "app_01", "Data Engineer", "Infosys", "Noida", "Applied (Naukri)", "https://naukri.com/j1"])
        writer.writerow(["2026-10-01 11:00:00", "app_02", "Big Data Engineer", "Boston Consulting Group", "Gurugram", "External Skipped", "https://naukri.com/j2-3-to-6-years-app02"])
        writer.writerow(["2026-10-01 12:00:00", "app_03", "Data Architect", "Random Org", "Delhi", "External Skipped", "https://naukri.com/j3"])

    cfg = {"company_priority": {"tier_1_companies": ["Boston Consulting Group"]}}
    count = backfill_external_jobs_from_applied_csv(config=cfg, applied_csv=src_csv, target_csv=dest_csv)
    assert count == 2

    jobs = load_external_jobs(dest_csv)
    assert len(jobs) == 2
    bcg_job = next(j for j in jobs if "Boston Consulting Group" in j["Company"])
    assert bcg_job["Priority Tier"] == "Tier 1 (High)"
    assert bcg_job["Experience"] == "3-6 Yrs"


def test_resolve_resume_path(tmp_path):
    from resume_resolver import resolve_resume_path

    # Scenario 1: Configured path exists
    real_pdf = tmp_path / "custom_resume.pdf"
    real_pdf.write_text("%PDF-1.4 dummy")
    cfg = {"personals": {"default_resume_path": str(real_pdf)}}
    assert resolve_resume_path(cfg, base_dir=str(tmp_path)) == str(real_pdf)

    # Scenario 2: Configured path does not exist, but root PDF exists
    cfg_invalid = {"personals": {"default_resume_path": "/nonexistent/resume.pdf"}}
    root_pdf = tmp_path / "auto_found.pdf"
    root_pdf.write_text("%PDF-1.4 dummy")
    assert resolve_resume_path(cfg_invalid, base_dir=str(tmp_path)) == str(root_pdf)

    # Scenario 3: Configured path empty, subdirectory resumes/ contains PDF
    root_pdf.unlink()
    real_pdf.unlink()
    resumes_dir = tmp_path / "resumes"
    resumes_dir.mkdir()
    sub_pdf = resumes_dir / "candidate_cv.pdf"
    sub_pdf.write_text("%PDF-1.4 dummy")
    cfg_empty = {"personals": {"default_resume_path": ""}}
    assert resolve_resume_path(cfg_empty, base_dir=str(tmp_path)) == str(sub_pdf)

    # Scenario 4: No PDF anywhere returns None
    sub_pdf.unlink()
    assert resolve_resume_path(cfg_empty, base_dir=str(tmp_path)) is None


def test_generate_insights_html(tmp_path):
    import json
    import csv
    from insights_generator import generate_insights_html

    csv_file = str(tmp_path / "applied.csv")
    with open(csv_file, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Date", "Job ID", "Title", "Company", "Location", "Status", "Job URL"])
        w.writerow(["2026-10-06 20:00:00", "12345", "Data Engineer", "Google", "Gurugram", "Applied", "https://naukri.com/12345"])

    ext_csv = str(tmp_path / "external.csv")
    with open(ext_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Date Discovered", "Job ID", "Company", "Priority Tier", "Priority Score", "Title", "Location", "Experience", "Direct Apply URL", "Naukri URL", "Status", "Notes"])
        w.writerow(["2026-10-06 20:05:00", "67890", "Microsoft", "Tier 1 (High)", "1", "Azure Data Engineer", "Noida", "3-5 Yrs", "https://careers.microsoft.com/job/67890", "https://naukri.com/67890", "Pending", "Direct portal available"])

    json_file = str(tmp_path / "insights.json")
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump([
            {
                "job_title": "Data Engineer",
                "company": "Google",
                "criteria": {"Keyskills": True, "Location": True}
            }
        ], f)

    out_html = str(tmp_path / "insights.html")
    res = generate_insights_html(csv_path=csv_file, json_path=json_file, output_html_path=out_html, external_csv_path=ext_csv)
    assert os.path.isfile(res)
    with open(out_html, "r", encoding="utf-8") as f:
        content = f.read()
    assert "Google" in content
    assert "Data Engineer" in content
    assert "Microsoft" in content
    assert "Azure Data Engineer" in content
    assert "Applied Jobs History" in content
    assert "External Jobs" in content
    assert "chart.js" in content.lower()
    assert "Naukri Bot Analytics & Insights" in content




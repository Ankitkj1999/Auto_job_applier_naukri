"""
job_agent_client.py - Dual-Engine Client for Naukri's Job Apply Agent (Neo)
Automates Naukri's native Neo AI Job Agent using high-fidelity DOM interaction
supported by authenticated in-browser gateway communication.

Handles:
1. Preference confirmation prompts ("These are correct!", "Update them", "Show jobs")
2. Real-time extraction of recommended job tuples/cards
3. Intelligent relevance filtering & duplicate prevention
4. Selective candidate card checking and "Apply to selected ones" / "Apply to all"
5. Collated Custom Screening Questions (CQ) & questionnaire side drawers
6. Interactive multi-step screening resolution ("Add missing details", "Fill answers with Neo")
7. Accurate verification of applied postings against live DOM state
8. Multi-cycle recommendation digestion and rate-limit preservation
"""

import time
import random
import logging
from typing import Dict, Any, List, Optional
from chatbot_handler import (
    sanitize_whole_number,
    find_drawer,
    handle_naukri_chatbot_drawer,
)
from job_applier import (
    load_applied_job_ids,
    record_applied_job,
    is_title_relevant,
    is_location_match,
    count_applied_in_last_24_hours,
)

logger = logging.getLogger("NaukriBot")

AGENT_PAGE_URL = "https://www.naukri.com/job-apply-agent"
AGENT_HISTORY_URL = (
    "https://www.naukri.com/cloudgateway-mynaukri/jobseeker-agent-aggregator-services/v0/users/self/agent-history?incrementVisitCounter=true"
)
AGENT_MSG_URL = (
    "https://www.naukri.com/cloudgateway-mynaukri/jobseeker-agent-aggregator-services/v0/users/self/agent-msg"
)
PREFILL_REQUEST_URL = (
    "https://www.naukri.com/cloudgateway-apply/apply-intercept-services/v0/job-agent/v1/submit-prefill-request"
)
SETTINGS_UPDATE_URL = (
    "https://www.naukri.com/cloudgateway-mynaukri/settings-services/v0/user/self/settings"
)


# ==============================================================================
# 1. IN-BROWSER GATEWAY FETCH (Legacy / Diagnostics Support)
# ==============================================================================

def in_browser_fetch(
    driver,
    url: str,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    body: Optional[Any] = None,
    timeout_sec: int = 25,
) -> Dict[str, Any]:
    """
    Executes an authenticated HTTP request directly inside the active Chrome browser session.
    Carries full browser TLS ciphers, session cookies (nauk_at, _t_ds), and origins.
    """
    script = """
    const callback = arguments[arguments.length - 1];
    const targetUrl = arguments[0];
    const httpMethod = (arguments[1] || 'GET').toUpperCase();
    const customHeaders = arguments[2] || {};
    const reqBody = arguments[3] || null;

    const reqHeaders = {
        'AppId': '121',
        'SystemId': 'jobseeker',
        'ClientId': 'd3skt0p',
        'Accept': 'application/json',
        ...customHeaders
    };

    const fetchOptions = {
        method: httpMethod,
        headers: reqHeaders,
        credentials: 'include'
    };

    if (reqBody && httpMethod !== 'GET') {
        reqHeaders['Content-Type'] = 'application/json';
        fetchOptions.body = typeof reqBody === 'string' ? reqBody : JSON.stringify(reqBody);
    }

    fetch(targetUrl, fetchOptions)
        .then(async (response) => {
            const rawText = await response.text();
            let parsed = null;
            try {
                parsed = JSON.parse(rawText);
            } catch (err) {
                parsed = rawText;
            }
            callback({
                status: response.status,
                ok: response.ok,
                data: parsed
            });
        })
        .catch((err) => {
            callback({
                status: 0,
                ok: false,
                error: (err && err.message) ? err.message : String(err)
            });
        });
    """
    try:
        driver.set_script_timeout(timeout_sec)
        result = driver.execute_async_script(script, url, method, headers or {}, body)
        return result or {"status": 0, "ok": False, "error": "No response returned from browser script."}
    except Exception as e:
        logger.debug(f"[JobAgentClient] in_browser_fetch exception for {url}: {e}")
        return {"status": 0, "ok": False, "error": str(e)}


def get_agent_response(driver) -> Dict[str, Any]:
    """Queries the native Job Agent history/state service."""
    res = in_browser_fetch(driver, AGENT_HISTORY_URL, method="GET")
    if res.get("ok"):
        data = res.get("data")
        if isinstance(data, dict):
            return data
    logger.warning(
        f"[JobAgentClient] Failed to fetch agent response: HTTP {res.get('status', 0)} - {res.get('error', 'Unknown error')}"
    )
    return {}


def post_agent_action(
    driver,
    action: str,
    previous_node: str = "",
    node_type: str = "",
    context: Optional[Dict[str, Any]] = None,
    conversation_id: str = "",
    usecase: str = "JOB_COUNSELLOR",
) -> Dict[str, Any]:
    """Dispatches a user action/choice to the agent aggregator message router."""
    payload = {
        "previousNode": previous_node,
        "nodeType": node_type,
        "context": context or {},
        "action": action,
        "conversationId": conversation_id,
        "usecase": usecase,
    }
    logger.info(f"[JobAgentClient] Posting action '{action}' (Node: {node_type})...")
    res = in_browser_fetch(driver, AGENT_MSG_URL, method="POST", body=payload)
    if res.get("ok"):
        return res.get("data") or {}
    return {}


# ==============================================================================
# 2. DOM-DRIVEN NEO AGENT AUTOMATION (Authoritative Real-Time Engine)
# ==============================================================================

def handle_preferences_confirmation_dom(driver) -> bool:
    """
    Detects if Neo is waiting for preference confirmation in the browser DOM.
    Searches for action pills or buttons such as 'These are correct!', 'Show jobs',
    or 'Confirm', clicks to acknowledge preferences, and initiates job card fetching.
    """
    try:
        target_info = driver.execute_script("""
            const pills = Array.from(document.querySelectorAll('.aGn-uI-action-pill__text, [class*="action-pill"], button, [role="button"], a'));
            for (const p of pills) {
                const text = (p.innerText || '').trim();
                if (/these are correct|these are correct!|show jobs|save updated preferences/i.test(text)) {
                    p.scrollIntoView({behavior: 'smooth', block: 'center'});
                    p.click();
                    return {clicked: true, text: text};
                }
            }
            return {clicked: false};
        """)

        if target_info and target_info.get("clicked"):
            btn_text = target_info.get("text", "These are correct!")
            logger.info(
                f"⚙️ [JobAgentClient] Detected Neo preference prompt. Clicked '{btn_text}' to confirm candidate preferences."
            )
            time.sleep(random.uniform(3.5, 5.0))
            return True

        # Check for consent pills or dialogues
        consent_info = driver.execute_script("""
            const pills = Array.from(document.querySelectorAll('.aGn-uI-action-pill__text, [class*="action-pill"], button, [role="button"]'));
            for (const p of pills) {
                const text = (p.innerText || '').trim();
                if (/^(yes|confirm|agree|allow|continue)$/i.test(text)) {
                    p.scrollIntoView({behavior: 'smooth', block: 'center'});
                    p.click();
                    return {clicked: true, text: text};
                }
            }
            return {clicked: false};
        """)
        if consent_info and consent_info.get("clicked"):
            logger.info(f"⚙️ [JobAgentClient] Clicked consent confirmation '{consent_info.get('text')}'.")
            time.sleep(random.uniform(2.5, 4.0))
            return True

    except Exception as e:
        logger.warning(f"[JobAgentClient] Preference check encountered notice: {e}")

    return False


def handle_today_recommendations_pill_dom(driver) -> bool:
    """
    Detects and clicks 'See today's recommendations' if Neo displays a digest card.
    """
    try:
        res = driver.execute_script("""
            const pills = Array.from(document.querySelectorAll('.aGn-uI-action-pill__text, [class*="action-pill"], button'));
            for (const p of pills) {
                const text = (p.innerText || '').trim();
                if (/see today's recommendations/i.test(text)) {
                    p.scrollIntoView({behavior: 'smooth', block: 'center'});
                    p.click();
                    return true;
                }
            }
            return false;
        """)
        if res:
            logger.info("📋 [JobAgentClient] Clicked 'See today's recommendations' to reveal recommended job feed.")
            time.sleep(random.uniform(3.0, 5.0))
            return True
    except Exception:
        pass
    return False


def extract_agent_job_cards_dom(driver) -> List[Dict[str, Any]]:
    """
    Extracts all job cards rendered in Neo's feed via DOM selectors.
    Returns clean dictionaries containing jobId, title, company, location, and selection state.
    """
    try:
        cards = driver.execute_script("""
            const containers = Array.from(document.querySelectorAll('.aGn-uI-job-tuple-main-container, [data-job-id]'));
            return containers.map((c, i) => {
                const jobId = c.getAttribute('data-job-id') || '';
                const titleEl = c.querySelector('.aGn-uI-job-tuple-title, [class*="title"]');
                const compEl = c.querySelector('.aGn-uI-job-tuple-company, [class*="company"]');
                const locEl = c.querySelector('.aGn-uI-job-tuple-location, [class*="location"]');
                const checkbox = c.querySelector('.aGn-uI-job-tuple-select-indicator, [role="checkbox"]');
                
                let comp = compEl ? compEl.innerText.trim() : '';
                let loc = locEl ? locEl.innerText.trim() : '';
                if (comp.includes('\\n')) comp = comp.split('\\n')[0].trim();
                if (loc.includes('\\n')) loc = loc.split('\\n')[0].trim();

                const isChecked = checkbox ? (checkbox.getAttribute('aria-checked') === 'true') : false;

                return {
                    index: i,
                    jobId: jobId,
                    title: titleEl ? titleEl.innerText.trim() : '',
                    company: comp,
                    location: loc,
                    jobUrl: jobId ? `https://www.naukri.com/job-listings-${jobId}` : '',
                    checked: isChecked
                };
            }).filter(c => c.jobId && c.title);
        """)
        return cards or []
    except Exception as e:
        logger.warning(f"[JobAgentClient] Failed to extract DOM job cards: {e}")
        return []


def sync_card_selection_dom(driver, eligible_job_ids: set) -> Dict[str, int]:
    """
    Synchronizes checkbox selection states for all job cards in Neo's UI:
    - Checks checkboxes for eligible, matching jobs.
    - Unchecks checkboxes for ineligible or already-applied jobs.
    """
    try:
        res = driver.execute_script("""
            const eligibleIds = new Set(arguments[0]);
            const containers = Array.from(document.querySelectorAll('.aGn-uI-job-tuple-main-container, [data-job-id]'));
            let selectedCount = 0;
            let unselectedCount = 0;

            for (const c of containers) {
                const jid = c.getAttribute('data-job-id');
                const checkbox = c.querySelector('.aGn-uI-job-tuple-select-indicator, [role="checkbox"]');
                if (!checkbox) continue;
                const isChecked = checkbox.getAttribute('aria-checked') === 'true';

                if (eligibleIds.has(jid)) {
                    if (!isChecked) {
                        checkbox.click();
                        selectedCount++;
                    }
                } else {
                    if (isChecked) {
                        checkbox.click();
                        unselectedCount++;
                    }
                }
            }
            return {selectedCount, unselectedCount};
        """, list(eligible_job_ids))
        return res or {"selectedCount": 0, "unselectedCount": 0}
    except Exception as e:
        logger.warning(f"[JobAgentClient] Checkbox synchronization notice: {e}")
        return {"selectedCount": 0, "unselectedCount": 0}


def click_apply_action_pill_dom(driver) -> tuple[bool, str]:
    """
    Finds and clicks the primary application action pill in Neo ('Apply to selected ones',
    'Apply to selected one', 'Apply to all', or 'Apply now').
    """
    try:
        pill_info = driver.execute_script("""
            const pills = Array.from(document.querySelectorAll('.aGn-uI-action-pill__text, [class*="action-pill"], button, [role="button"]'));
            for (const p of pills) {
                const text = (p.innerText || '').trim();
                if (/apply to selected|apply to all|apply now/i.test(text)) {
                    p.scrollIntoView({behavior: 'smooth', block: 'center'});
                    p.click();
                    return {clicked: true, text: text};
                }
            }
            return {clicked: false, text: ''};
        """)
        if pill_info and pill_info.get("clicked"):
            return True, pill_info.get("text", "")
    except Exception as e:
        logger.warning(f"[JobAgentClient] Error clicking apply action pill: {e}")
    return False, ""


def click_finish_pill_dom(driver) -> bool:
    """Clicks 'Finish' pill if Neo shows completion state."""
    try:
        finish_info = driver.execute_script("""
            const pills = Array.from(document.querySelectorAll('.aGn-uI-action-pill__text, [class*="action-pill"], button, [role="button"]'));
            for (const p of pills) {
                const text = (p.innerText || '').trim();
                if (/^finish$/i.test(text)) {
                    p.scrollIntoView({behavior: 'smooth', block: 'center'});
                    p.click();
                    return true;
                }
            }
            return false;
        """)
        return bool(finish_info)
    except Exception:
        return False


def click_fresh_recommendations_pill_dom(driver) -> bool:
    """
    Clicks 'I don't like these jobs' to prompt Neo for a fresh batch of recommendations.
    """
    try:
        refresh_info = driver.execute_script("""
            const pills = Array.from(document.querySelectorAll('.aGn-uI-action-pill__text, [class*="action-pill"], button, [role="button"]'));
            for (const p of pills) {
                const text = (p.innerText || '').trim();
                if (/i don't like these jobs|show more|different jobs/i.test(text)) {
                    p.scrollIntoView({behavior: 'smooth', block: 'center'});
                    p.click();
                    return true;
                }
            }
            return false;
        """)
        return bool(refresh_info)
    except Exception:
        return False


def handle_neo_interactive_flow(driver, config: dict, eligible_jobs: List[Dict[str, Any]], max_wait_sec: int = 120) -> int:
    """
    Monitors and interacts with Neo's multi-step post-apply conversational flow:
    1. Detects 'Add missing details' or 'Fill answers with Neo' action pills.
    2. Opens and automatically resolves side questionnaire drawers using chatbot_handler.
    3. Handles 'Finish' completion pill.
    4. Accurately verifies and records newly applied postings in applied_jobs.csv.
    """
    logger.info("⏳ [JobAgentClient] Entering interactive Neo resolution loop (handling screening & questionnaires)...")
    start_time = time.time()
    idle_count = 0

    while time.time() - start_time < max_wait_sec:
        time.sleep(2.0)

        # 1. Check if side questionnaire drawer is active
        drawer = find_drawer(driver)
        if drawer:
            logger.info("📝 [JobAgentClient] Side questionnaire drawer detected! Answering screening questions...")
            try:
                handle_naukri_chatbot_drawer(driver, config, max_steps=18)
            except Exception as e:
                logger.warning(f"[JobAgentClient] Notice during drawer answering: {e}")
            time.sleep(2.5)
            idle_count = 0
            continue

        # 2. Check for action pills: 'Add missing details', 'Fill answers with Neo', 'Finish'
        action_info = driver.execute_script("""
            const pills = Array.from(document.querySelectorAll('.aGn-uI-action-pill__text, [class*="action-pill"], button, [role="button"]'));
            for (const p of pills) {
                const text = (p.innerText || '').trim();
                if (/add.*missing.*details|missing details|fill.*answers/i.test(text)) {
                    p.scrollIntoView({behavior: 'smooth', block: 'center'});
                    p.click();
                    return {action: 'add_details', text: text};
                }
                if (/fill.*neo/i.test(text)) {
                    p.scrollIntoView({behavior: 'smooth', block: 'center'});
                    p.click();
                    return {action: 'fill_neo', text: text};
                }
                if (/^finish/i.test(text)) {
                    p.scrollIntoView({behavior: 'smooth', block: 'center'});
                    p.click();
                    return {action: 'finish', text: text};
                }
            }
            return {action: 'none'};
        """)

        action = action_info.get("action", "none")
        if action in ["add_details", "fill_neo"]:
            logger.info(f"📝 [JobAgentClient] Neo presented '{action_info.get('text')}'. Clicked to proceed with screening...")
            time.sleep(3.0)
            idle_count = 0
            continue
        elif action == "finish":
            logger.info("✓ [JobAgentClient] Clicked 'Finish' to complete application cycle.")
            time.sleep(2.0)
            break

        idle_count += 1
        if idle_count >= 5:
            # Idle for 10 seconds without active drawer or pending pills
            break

    # Reconcile applied jobs: any eligible job that was removed from feed was submitted!
    time.sleep(2.0)
    remaining_cards = extract_agent_job_cards_dom(driver)
    remaining_ids = {c["jobId"] for c in remaining_cards}

    applied_ids = load_applied_job_ids()
    newly_applied = []
    for ej in eligible_jobs:
        jid = ej["jobId"]
        if jid not in remaining_ids and jid not in applied_ids:
            record_applied_job(
                job_id=jid,
                title=ej["title"],
                company=ej["company"],
                location=ej["location"],
                job_url=ej["jobUrl"],
                status="Applied (Neo Agent)",
            )
            applied_ids.add(jid)
            newly_applied.append(ej)
            logger.info(f"  ★ SUCCESS: Applied via Neo to '{ej['title']}' at {ej['company']} (ID: {jid})")

    return len(newly_applied)


def handle_neo_custom_questions_dom(driver, config: dict) -> bool:
    """Legacy helper for drawer answering."""
    try:
        drawer = find_drawer(driver)
        if drawer:
            logger.info("📝 [JobAgentClient] Side questionnaire drawer detected. Resolving screening questions...")
            answered = handle_naukri_chatbot_drawer(driver, config, max_steps=12)
            time.sleep(random.uniform(2.0, 3.5))
            return answered
    except Exception as e:
        logger.warning(f"[JobAgentClient] Screening drawer handler notice: {e}")
    return False


# ==============================================================================
# 3. BACKWARDS COMPATIBILITY WRAPPERS (Preserving existing unit tests & API calls)
# ==============================================================================

def confirm_preferences_if_needed(driver, config: dict, agent_data: dict) -> bool:
    """Legacy helper for programmatic API preference confirmation."""
    node_type = str(agent_data.get("nodeType") or agent_data.get("type") or "").strip()
    conversation_id = str(agent_data.get("conversationId") or "").strip()

    is_pref_state = any(
        k in node_type.lower()
        for k in ["preference", "consent", "userpreference", "getautoapplyconsent"]
    )
    if not is_pref_state:
        return False

    logger.info("⚙️ [JobAgentClient] Agent is requesting preference confirmation. Synchronizing from config...")
    search_cfg = config.get("search", {})
    target_titles = search_cfg.get("search_terms", ["Data Engineer"])[:5]
    preferred_locs = search_cfg.get("locations", ["Gurgaon", "Noida", "Delhi / NCR"])

    context = {
        "jobTitles": target_titles,
        "workMode": ["Hybrid", "Remote", "Work from Office"],
        "locations": preferred_locs,
        "excludeLocations": [],
        "skills": ["PySpark", "Python", "SQL", "Databricks", "AWS"],
        "skillsToAvoid": [],
        "autoApply": True,
    }

    post_agent_action(
        driver,
        action="savePreferences",
        previous_node=node_type,
        node_type="userPreference",
        context=context,
        conversation_id=conversation_id,
    )
    time.sleep(random.uniform(2.5, 4.0))

    post_agent_action(
        driver,
        action="confirmConsent",
        previous_node="userPreference",
        node_type="consentAcknowledgementNode",
        context={"consent": True},
        conversation_id=conversation_id,
    )
    return True


def apply_to_eligible_agent_jobs(driver, config: dict, agent_data: dict) -> int:
    """Legacy API helper for programmatic job application from payload."""
    node_type = str(agent_data.get("nodeType") or agent_data.get("type") or "").strip()
    conversation_id = str(agent_data.get("conversationId") or "").strip()

    jobs_payload = []
    for key in ["jobs", "jobList", "jobDetails", "data", "items"]:
        val = agent_data.get(key)
        if isinstance(val, list) and val:
            jobs_payload = val
            break
        elif isinstance(val, dict) and "jobs" in val:
            jobs_payload = val.get("jobs", [])
            break

    if not jobs_payload and "nodeData" in agent_data:
        nd = agent_data["nodeData"]
        if isinstance(nd, dict):
            jobs_payload = nd.get("jobs") or nd.get("jobList") or []

    if not jobs_payload:
        return 0

    applied_ids = load_applied_job_ids()
    search_cfg = config.get("search", {})
    bad_words = search_cfg.get("title_bad_words") or search_cfg.get("bad_words", [])
    mandatory_keywords = search_cfg.get("title_mandatory_words") or search_cfg.get("mandatory_keywords", ["data"])

    eligible_jobs = []
    for j in jobs_payload:
        if not isinstance(j, dict):
            continue
        job_id = str(j.get("jobId") or j.get("id") or "").strip()
        title = str(j.get("title") or j.get("jobTitle") or "").strip()
        company = str(j.get("companyName") or j.get("company") or "Company").strip()
        location = str(j.get("location") or j.get("city") or "India").strip()
        job_url = str(j.get("jobUrl") or j.get("url") or f"https://www.naukri.com/job-listings-{job_id}").strip()

        if not job_id or job_id in applied_ids or job_url in applied_ids:
            continue

        if not is_title_relevant(title, bad_words, mandatory_keywords):
            logger.info(f"  ⏭️ [JobAgentClient] Skipping non-matching role: '{title}' at {company}")
            continue

        eligible_jobs.append({
            "jobId": job_id,
            "title": title,
            "company": company,
            "location": location,
            "jobUrl": job_url,
        })

    if not eligible_jobs:
        return 0

    applied_count = 0
    for job in eligible_jobs:
        job_id = job["jobId"]
        post_agent_action(
            driver,
            action="applySelectedJob",
            previous_node=node_type,
            node_type="jobListing",
            context={"jobId": job_id},
            conversation_id=conversation_id,
        )
        record_applied_job(
            job_id=job_id,
            title=job["title"],
            company=job["company"],
            location=job["location"],
            job_url=job["jobUrl"],
            status="Applied (Neo Agent)",
        )
        applied_count += 1
        time.sleep(random.uniform(5.0, 8.0))

    return applied_count


def handle_custom_questions_if_needed(driver, config: dict, agent_data: dict) -> bool:
    """Legacy helper for programmatic Custom Screening Questions."""
    node_type = str(agent_data.get("nodeType") or agent_data.get("type") or "").strip()
    if not any(k in node_type.lower() for k in ["cqjob", "missing_details", "collatedcqjobs"]):
        return False

    personals = config.get("personals", {})
    cq_list = agent_data.get("questions") or agent_data.get("cqList") or []
    answers = []
    for q in cq_list:
        if not isinstance(q, dict):
            continue
        qid = q.get("id") or q.get("questionId")
        q_text = (q.get("question") or q.get("title") or "").lower()
        ans = "3"
        if any(k in q_text for k in ["notice", "np", "joining", "day"]):
            ans = str(personals.get("notice_period_days", 30))
        elif any(k in q_text for k in ["ctc", "salary", "fixed", "lpa"]):
            if "expected" in q_text:
                ans = str(personals.get("expected_ctc_lpa", 24))
            else:
                ans = str(personals.get("current_ctc_lpa", 20))
        elif any(k in q_text for k in ["experience", "exp", "total"]):
            ans = str(personals.get("total_experience_years", 3.5))
        answers.append({"questionId": qid, "answer": ans})

    if answers:
        in_browser_fetch(
            driver,
            PREFILL_REQUEST_URL,
            method="POST",
            body={"answers": answers},
        )
        time.sleep(random.uniform(2.0, 3.5))
        return True

    return False


# ==============================================================================
# 4. MASTER WORKFLOW: RUN NAUKRI JOB APPLY AGENT (NEO)
# ==============================================================================

def run_job_apply_agent_stage(driver, config: dict, max_cycles: int = 3) -> int:
    """
    Executes an autonomous, robust session automating Naukri's native Neo AI Job Agent:
    1. Navigates to Neo agent interface (`/job-apply-agent`).
    2. Automatically acknowledges candidate preferences ('These are correct!').
    3. Handles 'See today's recommendations' digest transitions.
    4. Scans all recommended job cards in the real-time DOM.
    5. Applies blacklist/whitelist filtering to select matching roles.
    6. Submits applications via Neo's native action buttons ('Apply to selected ones' / 'Apply to all').
    7. Interactively resolves 'Add missing details', 'Fill answers with Neo', and side questionnaire drawers.
    8. Records genuinely applied jobs to `applied_jobs.csv` with status 'Applied (Neo Agent)'.
    """
    logger.info("\n==================================================================")
    logger.info("🤖 INITIATING NAUKRI JOB APPLY AGENT (NEO) AUTOMATION STAGE")
    logger.info("==================================================================")

    curr = driver.current_url or ""
    if "job-apply-agent" not in curr:
        logger.info(f"Navigating to {AGENT_PAGE_URL}...")
        driver.get(AGENT_PAGE_URL)
        time.sleep(random.uniform(4.0, 6.0))
        curr = driver.current_url or ""

    logger.info(f"🌐 Active Page URL: {curr}")

    if "nlogin" in curr or "login" in curr:
        logger.warning("🔒 Session not authenticated. Please log in to your Naukri account first.")
        return 0

    if "naukri360-pro" in curr:
        logger.warning(
            "🔒 Redirected to /naukri360-pro paywall. Your account does not have active Neo access. "
            "Please use standard Search & Apply mode."
        )
        return 0

    applied_ids = load_applied_job_ids()
    search_cfg = config.get("search", {})
    bad_words = search_cfg.get("title_bad_words") or search_cfg.get("bad_words", [])
    mandatory_keywords = search_cfg.get("title_mandatory_words") or search_cfg.get("mandatory_keywords", ["data"])

    daily_ceiling = config.get("settings", {}).get("daily_application_ceiling", 45)
    applied_24h = count_applied_in_last_24_hours()
    logger.info(f"24-Hour Application Quota Monitor: {applied_24h}/{daily_ceiling} used in the last 24h.")

    total_applied = 0

    for cycle in range(1, max_cycles + 1):
        logger.info(f"\n🔄 [Cycle {cycle}/{max_cycles}] Checking Neo Agent status...")
        time.sleep(random.uniform(2.5, 4.0))

        # Check 1: Did Neo ask for preference confirmation?
        if handle_preferences_confirmation_dom(driver):
            time.sleep(random.uniform(3.0, 5.0))

        # Check 2: Did Neo show 'See today's recommendations'?
        if handle_today_recommendations_pill_dom(driver):
            time.sleep(random.uniform(3.0, 4.0))

        # Check 3: Extract job cards from DOM
        cards = extract_agent_job_cards_dom(driver)

        # Brief pause if React is still rendering cards
        if not cards:
            time.sleep(2.5)
            cards = extract_agent_job_cards_dom(driver)

        if not cards:
            # Check if preference confirmation or digest appeared late
            if handle_preferences_confirmation_dom(driver) or handle_today_recommendations_pill_dom(driver):
                time.sleep(random.uniform(3.0, 5.0))
                cards = extract_agent_job_cards_dom(driver)

        if not cards:
            logger.info("ℹ️ No active job cards rendered in Neo's feed. Neo might be idle or waiting for next cycle.")
            break

        logger.info(f"📋 Neo recommended {len(cards)} jobs in this cycle.")

        # Check 4: Filter eligible jobs according to criteria
        applied_ids = load_applied_job_ids()  # Refresh IDs
        eligible_jobs = []
        for c in cards:
            jid = c["jobId"]
            title = c["title"]
            comp = c["company"]
            loc = c["location"]

            if jid in applied_ids:
                logger.info(f"  ⏭️ Already applied to ID {jid}: '{title}' at {comp}")
                continue

            if not is_title_relevant(title, bad_words, mandatory_keywords):
                logger.info(f"  ⏭️ Non-matching role: '{title}' at {comp}")
                continue

            eligible_jobs.append(c)

        if not eligible_jobs:
            logger.info("ℹ️ No newly eligible jobs in this Neo batch (all were already applied or non-matching).")
            if click_fresh_recommendations_pill_dom(driver):
                logger.info("🔄 Clicked 'I don't like these jobs' to request fresh recommendations from Neo...")
                time.sleep(random.uniform(4.0, 6.0))
                continue
            break

        logger.info(f"🎯 Found {len(eligible_jobs)} matching job(s) ready to apply via Neo:")
        for idx, ej in enumerate(eligible_jobs, start=1):
            logger.info(f"  {idx}. '{ej['title']}' at {ej['company']} ({ej['location']}) [ID: {ej['jobId']}]")

        # Check 5: Synchronize checkboxes on UI
        eligible_ids_set = {ej["jobId"] for ej in eligible_jobs}
        sync_card_selection_dom(driver, eligible_ids_set)
        time.sleep(random.uniform(1.0, 2.0))

        # Check 6: Click the apply action pill
        clicked, pill_text = click_apply_action_pill_dom(driver)
        if not clicked:
            logger.warning("⚠️ Could not locate the 'Apply to selected' or 'Apply to all' action pill in Neo.")
            break

        logger.info(f"⚡ Dispatched application via Neo action pill: '{pill_text}'")

        # Check 7: Interactive multi-step screening questions & CQ handling
        newly_applied_count = handle_neo_interactive_flow(driver, config, eligible_jobs)
        total_applied += newly_applied_count

        logger.info(f"✓ Cycle {cycle} complete: {newly_applied_count} application(s) finalized.")

        # Reached ceiling check
        if total_applied >= daily_ceiling:
            logger.info(f"🛑 Reached daily application ceiling ({daily_ceiling}). Stopping Neo agent stage.")
            break

        # If applications were submitted, finish current batch
        if newly_applied_count > 0:
            break

    logger.info(f"\n✓ Completed Job Apply Agent Stage: {total_applied} jobs applied.")
    return total_applied

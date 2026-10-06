import os
import re
import csv
import time
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger("NaukriBot")

EXTERNAL_JOBS_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "external_jobs.csv")
EXTERNAL_JOBS_MD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "external_jobs_tracker.md")
APPLIED_JOBS_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "applied_jobs.csv")

DEFAULT_TIER_1 = [
    "Google", "Alphabet", "Microsoft", "Amazon", "AWS", "Meta", "Facebook", "Apple", "Netflix",
    "Uber", "Atlassian", "Salesforce", "Adobe", "Stripe", "Databricks", "Snowflake", "Palantir",
    "Boston Consulting Group", "BCG", "McKinsey", "Bain", "Goldman Sachs", "Morgan Stanley",
    "JPMorgan", "JP Morgan", "Walmart", "Target", "LinkedIn", "Oracle", "Cisco", "Nvidia", "Airbnb"
]

DEFAULT_TIER_2 = [
    "Accenture", "Deloitte", "PwC", "PricewaterhouseCoopers", "EY", "Ernst & Young", "KPMG",
    "Capgemini", "Cognizant", "Infosys", "TCS", "Tata Consultancy Services", "Wipro", "HCL",
    "LTIMindtree", "Persistent", "Genpact", "Fidelity", "Macquarie", "Barclays", "HSBC",
    "American Express", "Amex", "Standard Chartered", "Citi", "Citigroup", "Deutsche Bank",
    "Societe Generale", "UBS", "Amdocs", "Siemens", "Robert Bosch", "Bosch", "SAP", "Fractal",
    "Fractal Analytics", "LatentView", "Tiger Analytics", "Mu Sigma", "Publicis Sapient",
    "Birlasoft", "Coforge", "Mphasis", "Tech Mahindra", "Zensar", "Hexaware", "L&T Technology"
]


def match_company_in_list(company_name: str, target_list: list[str]) -> bool:
    """
    Checks if company_name matches any company in target_list.
    Uses regex word boundaries for short acronyms (e.g. EY, BCG, SAP, TCS)
    and substring/word matching for multi-word or long company names.
    """
    if not company_name or not target_list:
        return False

    c_norm = re.sub(r'\(.*?\)', '', company_name).strip()

    for target in target_list:
        t_clean = target.strip()
        if not t_clean:
            continue
        
        # Word boundary regex pattern
        pattern = r"(?<!\w)" + re.escape(t_clean) + r"(?!\w)"
        if re.search(pattern, company_name, re.IGNORECASE) or re.search(pattern, c_norm, re.IGNORECASE):
            return True

    return False


def get_company_priority(company_name: str, config: dict = None) -> tuple[int, str]:
    """
    Determines company priority tier and numeric sorting rank.
    Returns: (rank, tier_name)
      - Rank 1: 'Tier 1 (High)'
      - Rank 2: 'Tier 2 (Medium)'
      - Rank 3: 'Tier 3 (Standard)'
    """
    tier_1 = DEFAULT_TIER_1
    tier_2 = DEFAULT_TIER_2

    if config and isinstance(config, dict):
        priority_cfg = config.get("company_priority", {})
        if priority_cfg.get("tier_1_companies"):
            tier_1 = priority_cfg["tier_1_companies"]
        if priority_cfg.get("tier_2_companies"):
            tier_2 = priority_cfg["tier_2_companies"]

    if match_company_in_list(company_name, tier_1):
        return (1, "Tier 1 (High)")
    if match_company_in_list(company_name, tier_2):
        return (2, "Tier 2 (Medium)")
    return (3, "Tier 3 (Standard)")


def resolve_external_url(driver, apply_btn, default_url: str = "") -> str:
    """
    Resolves the actual destination URL when 'Apply on Company Site' is clicked.
    First inspects element attributes (href, data-href).
    If not directly available, clicks the button, monitors any opened window/tab,
    captures the redirected URL, closes the temporary window, and safely restores
    focus to the original tab.
    Falls back to default_url (Naukri job URL) on any issue.
    """
    if not apply_btn:
        return default_url

    # 1. Check direct attributes
    try:
        href = apply_btn.get_attribute("href") or apply_btn.get_attribute("data-href") or ""
        if href and href.startswith("http") and "naukri.com" not in href:
            return href
    except Exception:
        pass

    if not driver:
        return default_url

    original_window = None
    try:
        original_window = driver.current_window_handle
        handles_before = set(driver.window_handles)
    except Exception:
        return default_url

    try:
        driver.execute_script("arguments[0].click();", apply_btn)
        time.sleep(2.0)

        handles_after = driver.window_handles
        new_handles = [h for h in handles_after if h not in handles_before]

        if new_handles:
            # Switched to newly opened external application tab
            target_handle = new_handles[-1]
            driver.switch_to.window(target_handle)
            time.sleep(1.5)
            resolved_url = driver.current_url
            try:
                driver.close()
            except Exception:
                pass
            driver.switch_to.window(original_window)
            if resolved_url and resolved_url.startswith("http"):
                return resolved_url
        else:
            # Same tab redirect
            if driver.current_url != default_url and driver.current_url.startswith("http"):
                resolved_url = driver.current_url
                try:
                    driver.back()
                    time.sleep(1.0)
                except Exception:
                    pass
                return resolved_url
    except Exception as e:
        logger.debug(f"Could not resolve external URL via click: {e}")
        try:
            current_handles = set(driver.window_handles)
            for h in current_handles - handles_before:
                try:
                    driver.switch_to.window(h)
                    driver.close()
                except Exception:
                    pass
            if original_window in driver.window_handles:
                driver.switch_to.window(original_window)
        except Exception:
            pass

    return default_url


def load_external_jobs(csv_path: str = None) -> list[dict]:
    """Reads all external jobs from CSV."""
    path = csv_path or EXTERNAL_JOBS_CSV
    if not os.path.isfile(path):
        return []

    jobs = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                jobs.append(row)
    except Exception as e:
        logger.warning(f"Could not read {path}: {e}")
    return jobs


def load_external_job_ids(csv_path: str = None) -> set:
    """Returns set of known job IDs and URLs from external_jobs.csv."""
    jobs = load_external_jobs(csv_path)
    known = set()
    for row in jobs:
        jid = (row.get("Job ID") or "").strip()
        nurl = (row.get("Naukri URL") or "").strip()
        durl = (row.get("Direct Apply URL") or "").strip()
        if jid:
            known.add(jid)
        if nurl:
            known.add(nurl)
        if durl and durl != nurl:
            known.add(durl)
    return known


def record_external_job(
    config: dict,
    job_id: str,
    title: str,
    company: str,
    location: str,
    experience: str,
    external_url: str,
    naukri_url: str,
    status: str = "Pending",
    notes: str = "",
    csv_path: str = None,
    md_path: str = None,
) -> dict:
    """
    Appends an external job record to external_jobs.csv and updates external_jobs_tracker.md.
    Avoids duplicate entries by Job ID / Naukri URL.
    """
    target_csv = csv_path or EXTERNAL_JOBS_CSV
    target_md = md_path or EXTERNAL_JOBS_MD

    file_exists = os.path.isfile(target_csv)
    known_ids = load_external_job_ids(target_csv)

    if job_id and job_id in known_ids:
        logger.debug(f"External job ID {job_id} already recorded.")
        return {}
    if naukri_url and naukri_url in known_ids:
        logger.debug(f"External job URL {naukri_url} already recorded.")
        return {}

    priority_score, priority_tier = get_company_priority(company, config)
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    job_data = {
        "Date Discovered": date_str,
        "Job ID": job_id,
        "Company": company,
        "Priority Tier": priority_tier,
        "Priority Score": str(priority_score),
        "Title": title,
        "Location": location,
        "Experience": experience,
        "Direct Apply URL": external_url or naukri_url,
        "Naukri URL": naukri_url,
        "Status": status,
        "Notes": notes,
    }

    try:
        with open(target_csv, "a", encoding="utf-8", newline="") as f:
            headers = [
                "Date Discovered",
                "Job ID",
                "Company",
                "Priority Tier",
                "Priority Score",
                "Title",
                "Location",
                "Experience",
                "Direct Apply URL",
                "Naukri URL",
                "Status",
                "Notes",
            ]
            writer = csv.DictWriter(f, fieldnames=headers)
            if not file_exists:
                writer.writeheader()
            writer.writerow(job_data)
        
        logger.info(f"  ★ [{priority_tier}] Logged external job for manual apply: {company} - '{title}'")
        update_external_jobs_markdown(config, csv_path=target_csv, md_path=target_md)
    except Exception as e:
        logger.warning(f"Failed to record external job: {e}")

    return job_data


def update_external_jobs_markdown(
    config: dict = None,
    csv_path: str = None,
    md_path: str = None,
) -> None:
    """
    Reads all records from external_jobs.csv, sorts them by priority and date,
    and writes a markdown tracking dashboard.
    """
    target_csv = csv_path or EXTERNAL_JOBS_CSV
    target_md = md_path or EXTERNAL_JOBS_MD

    jobs = load_external_jobs(target_csv)
    if not jobs:
        return

    # Recalculate priority scores dynamically if config is provided to allow updated rules
    for j in jobs:
        comp = j.get("Company", "")
        p_score, p_tier = get_company_priority(comp, config)
        j["_sort_score"] = p_score
        j["Priority Tier"] = p_tier

    # Sort criteria:
    # 1. Priority score (1 -> 2 -> 3)
    # 2. Status ('Pending' before 'Applied')
    # 3. Date Discovered (newest first)
    def sort_key(row):
        score = row.get("_sort_score", 3)
        status = (row.get("Status") or "Pending").strip().lower()
        status_rank = 0 if "pending" in status else 1
        date_val = row.get("Date Discovered", "")
        return (score, status_rank, -int(date_val.replace("-", "").replace(":", "").replace(" ", "") or 0))

    jobs.sort(key=sort_key)

    total_jobs = len(jobs)
    pending_count = sum(1 for j in jobs if "pending" in (j.get("Status") or "").lower())
    applied_count = total_jobs - pending_count

    tier_1_jobs = [j for j in jobs if j.get("_sort_score") == 1]
    tier_2_jobs = [j for j in jobs if j.get("_sort_score") == 2]
    tier_3_jobs = [j for j in jobs if j.get("_sort_score") == 3]

    lines = [
        "# 🌐 External Company Jobs Tracker",
        "",
        f"- **Last Updated:** `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`",
        f"- **Total External Jobs Tracked:** `{total_jobs}` (🌟 Tier 1: `{len(tier_1_jobs)}` | 🔷 Tier 2: `{len(tier_2_jobs)}` | ⚪ Tier 3: `{len(tier_3_jobs)}`)",
        f"- **Application Progress:** `{applied_count}` Applied | `{pending_count}` Pending",
        "",
        "> 💡 **How to Use:**",
        "> These jobs redirect to company career portals (Workday, Greenhouse, Taleo, etc.).",
        "> 1. Click **Apply on Portal** to directly open the company's application page.",
        "> 2. Once submitted, mark the status `- [x] Applied` in this file or update `external_jobs.csv`.",
        "",
        "---",
        "",
    ]

    def render_section(title: str, job_list: list[dict]):
        if not job_list:
            return
        lines.append(f"## {title} ({len(job_list)} Opportunities)")
        lines.append("")
        lines.append("| Status | Company | Role | Exp | Location | Direct Apply Link | Naukri Ref | Discovered |")
        lines.append("| :---: | :--- | :--- | :---: | :--- | :---: | :---: | :---: |")

        for item in job_list:
            status = (item.get("Status") or "Pending").strip()
            chk = "[x] Applied" if "applied" in status.lower() else "[ ] Pending"
            comp = item.get("Company", "Unknown")
            role = item.get("Title", "Data Engineer")
            exp = item.get("Experience", "") or "—"
            loc = item.get("Location", "") or "—"
            durl = item.get("Direct Apply URL", "") or item.get("Naukri URL", "")
            nurl = item.get("Naukri URL", "")
            date_part = (item.get("Date Discovered", "")).split(" ")[0]

            direct_link = f"[Apply on Portal]({durl})" if durl else "—"
            naukri_link = f"[Naukri Post]({nurl})" if nurl else "—"

            # Clean pipes to prevent breaking markdown tables
            comp_clean = comp.replace("|", "-")
            role_clean = role.replace("|", "-")
            loc_clean = loc.replace("|", "-")

            lines.append(f"| {chk} | **{comp_clean}** | {role_clean} | {exp} | {loc_clean} | {direct_link} | {naukri_link} | {date_part} |")
        lines.append("")

    render_section("🌟 Tier 1: High Priority (Product Giants & Strategy Consulting)", tier_1_jobs)
    render_section("🔷 Tier 2: Medium Priority (Global MNCs & Top IT Consultancies)", tier_2_jobs)
    render_section("⚪ Tier 3: Standard Priority (Other Companies & Fast-Growing Tech)", tier_3_jobs)

    try:
        with open(target_md, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        logger.debug(f"Updated {target_md} successfully.")
    except Exception as e:
        logger.warning(f"Could not update {target_md}: {e}")


def backfill_external_jobs_from_applied_csv(config: dict = None, applied_csv: str = None, target_csv: str = None) -> int:
    """
    Reads previously skipped external jobs from applied_jobs.csv and backfills them into external_jobs.csv.
    Ensures existing users immediately get their past skipped top companies prioritized.
    """
    src_csv = applied_csv or APPLIED_JOBS_CSV
    dest_csv = target_csv or EXTERNAL_JOBS_CSV

    if not os.path.isfile(src_csv):
        return 0

    known_ids = load_external_job_ids(dest_csv)
    backfilled_count = 0

    try:
        with open(src_csv, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                status = (row.get("Status") or "").strip()
                if "external" not in status.lower():
                    continue

                job_id = (row.get("Job ID") or "").strip()
                job_url = (row.get("Job URL") or "").strip()
                if job_id and job_id in known_ids:
                    continue
                if job_url and job_url in known_ids:
                    continue

                company = (row.get("Company") or "Unknown").strip()
                title = (row.get("Title") or "").strip()
                location = (row.get("Location") or "").strip()
                date_str = (row.get("Date") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")).strip()

                # Extract experience from Naukri URL if present (e.g. '3-to-6-years')
                exp_match = re.search(r'(\d+)-to-(\d+)-years', job_url)
                exp = f"{exp_match.group(1)}-{exp_match.group(2)} Yrs" if exp_match else ""

                p_score, p_tier = get_company_priority(company, config)

                job_data = {
                    "Date Discovered": date_str,
                    "Job ID": job_id,
                    "Company": company,
                    "Priority Tier": p_tier,
                    "Priority Score": str(p_score),
                    "Title": title,
                    "Location": location,
                    "Experience": exp,
                    "Direct Apply URL": job_url,
                    "Naukri URL": job_url,
                    "Status": "Pending",
                    "Notes": "Backfilled from previous runs",
                }

                # Append to dest_csv
                file_exists = os.path.isfile(dest_csv)
                with open(dest_csv, "a", encoding="utf-8", newline="") as out_f:
                    headers = [
                        "Date Discovered",
                        "Job ID",
                        "Company",
                        "Priority Tier",
                        "Priority Score",
                        "Title",
                        "Location",
                        "Experience",
                        "Direct Apply URL",
                        "Naukri URL",
                        "Status",
                        "Notes",
                    ]
                    writer = csv.DictWriter(out_f, fieldnames=headers)
                    if not file_exists:
                        writer.writeheader()
                    writer.writerow(job_data)

                if job_id:
                    known_ids.add(job_id)
                if job_url:
                    known_ids.add(job_url)
                backfilled_count += 1

        if backfilled_count > 0:
            update_external_jobs_markdown(config, csv_path=dest_csv)
            logger.info(f"Backfilled {backfilled_count} external jobs into {dest_csv}")

    except Exception as e:
        logger.warning(f"Error backfilling external jobs: {e}")

    return backfilled_count

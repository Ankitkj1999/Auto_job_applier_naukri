"""
keyword_optimizer.py - Naukri Resdex SEO & Keyword Placement Engine

Optimizes candidate visibility and recruiter engagement by:
1. Structuring high-converting keyword clusters for Data Engineering roles.
2. Front-loading high-intent keywords (Role + YOE + Core Tech Stack) within the first 60-70 chars
   so they are never truncated on desktop or mobile recruiter search cards.
3. Incorporating high-conversion recruiter triggers (e.g., '30 Days Notice').
4. Scoring headlines on a 100-point Engaging Candidate Index (front-load density, tech coverage, CTR hooks).
5. Closed-loop learning from Naukri 'Search Appearances' keywords to prioritize trending recruiter terms.
"""

import os
import re
import json
import logging
from typing import Dict, List, Tuple, Optional, Any
from datetime import datetime

logger = logging.getLogger("NaukriBot")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SEARCH_KEYWORDS_FILE = os.path.join(BASE_DIR, "search_appearances_keywords.json")
MAX_HEADLINE_LENGTH = 250

# High-converting keyword clusters designed specifically for Data Engineering & Cloud Data roles
OPTIMIZED_KEYWORD_CLUSTERS = [
    {
        "id": "lakehouse_pyspark_databricks",
        "theme": "PySpark & Databricks Lakehouse Specialist",
        "headline": "Data Engineer (3.5 YOE) | PySpark, Databricks, AWS, SQL | Scalable ETL/ELT & Lakehouse Pipelines | 30 Days Notice",
        "primary_role": "Data Engineer",
        "core_skills": ["PySpark", "Databricks", "AWS", "SQL", "Apache Spark"],
        "architecture_focus": "Lakehouse & ETL/ELT",
    },
    {
        "id": "aws_cloud_bigdata",
        "theme": "AWS Big Data & Cloud Pipeline Engineer",
        "headline": "AWS Data Engineer | 3.5 YOE | AWS (Glue, EMR, Redshift, S3), PySpark, Python, SQL, Airflow | Big Data Pipelines | 30 Days Notice",
        "primary_role": "AWS Data Engineer",
        "core_skills": ["AWS", "Glue", "EMR", "Redshift", "PySpark", "Python", "SQL", "Airflow"],
        "architecture_focus": "Cloud Big Data Pipelines",
    },
    {
        "id": "data_warehouse_snowflake",
        "theme": "Cloud Data Warehouse & Analytics Platform",
        "headline": "Data Platform Engineer | 3.5 YOE | Snowflake, Redshift, AWS, PySpark, SQL, Airflow | Cloud Data Warehouse & ETL | 30 Days Notice",
        "primary_role": "Data Platform Engineer",
        "core_skills": ["Snowflake", "Redshift", "AWS", "PySpark", "SQL", "Airflow"],
        "architecture_focus": "Cloud Data Warehousing & ETL",
    },
    {
        "id": "streaming_realtime_distributed",
        "theme": "Distributed Systems & Streaming Pipelines",
        "headline": "Senior Data Engineer | 3.5 YOE | PySpark, Kafka, AWS, Python, SQL | Distributed Big Data & Streaming Pipelines | 30 Days Notice",
        "primary_role": "Senior Data Engineer",
        "core_skills": ["PySpark", "Kafka", "AWS", "Python", "SQL"],
        "architecture_focus": "Streaming & Distributed Big Data",
    },
    {
        "id": "etl_architecture_datalake",
        "theme": "Enterprise ETL/ELT Architecture & Data Lakehouse",
        "headline": "Data Engineer | 3.5 YOE | Python, PySpark, SQL, AWS, Airflow | Scalable ETL/ELT Architecture & Data Lakehouse | 30 Days Notice",
        "primary_role": "Data Engineer",
        "core_skills": ["Python", "PySpark", "SQL", "AWS", "Airflow"],
        "architecture_focus": "Enterprise ETL Architecture",
    },
]

# Comprehensive Profile Summary tailored for 1000-char ATS and Resdex optimization
OPTIMIZED_PROFILE_SUMMARY = (
    "Results-driven Data Engineer with 3.5+ years of experience designing, building, and "
    "optimizing scalable batch and real-time ETL/ELT pipelines, distributed data processing systems, "
    "and cloud data warehouses.\n\n"
    "Core Technical Competencies:\n"
    "• Big Data & Compute: PySpark, Apache Spark, Databricks, Delta Lake, Hadoop, Distributed Processing\n"
    "• Cloud Infrastructure (AWS): AWS Glue, EMR, Redshift, S3, Athena, Lambda, Kinesis, IAM, CloudWatch\n"
    "• Data Warehousing & Databases: Snowflake, Amazon Redshift, PostgreSQL, MongoDB, Redis, Star/Snowflake Schemas\n"
    "• Programming & Scripting: Python (Pandas, PySpark, Boto3), Advanced SQL, Shell scripting\n"
    "• Orchestration & Tools: Apache Airflow, CI/CD, Docker, Data Quality Monitoring, Performance Tuning\n\n"
    "Serving 30 Days Notice Period. Actively seeking challenging Data Engineer / Cloud Data Platform opportunities."
)


def load_recruiter_search_keywords(filepath: str = SEARCH_KEYWORDS_FILE) -> Dict[str, Any]:
    """Loads scraped recruiter search keywords and appearances stats."""
    if os.path.isfile(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.debug(f"Could not load search keywords: {e}")
    return {
        "last_updated": None,
        "search_terms": [],
        "recruiter_companies": [],
        "raw_insights": [],
    }


def save_recruiter_search_keywords(data: Dict[str, Any], filepath: str = SEARCH_KEYWORDS_FILE) -> None:
    """Saves recruiter search keywords and trends to JSON."""
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.warning(f"Could not save search keywords to {filepath}: {e}")


def evaluate_headline_quality(headline: str) -> Dict[str, Any]:
    """
    Evaluates a candidate headline on a 100-point Engaging Candidate Index based on Naukri Resdex SEO:
    1. Length within limits (<= 250 chars) [Pass/Fail]
    2. Role title in first 30 chars (+20 pts)
    3. Experience indicator in first 45 chars (+15 pts)
    4. Front-loaded high-demand tech stack in first 70 chars (+25 pts)
    5. Architecture/domain depth (+20 pts)
    6. High-conversion trigger ('30 Days Notice' / 'Immediate') (+20 pts)
    """
    score = 0
    feedback = []
    text = (headline or "").strip()
    length = len(text)

    is_valid_length = 0 < length <= MAX_HEADLINE_LENGTH
    if not is_valid_length:
        feedback.append(f"Length {length} exceeds maximum limit of {MAX_HEADLINE_LENGTH} chars!")
        return {
            "score": 0,
            "length": length,
            "max_length": MAX_HEADLINE_LENGTH,
            "is_valid": False,
            "feedback": feedback,
            "first_70_chars": text[:70],
        }

    first_30 = text[:30].lower()
    first_45 = text[:45].lower()
    first_70 = text[:70].lower()

    # 1. Target Role Title in First 30 chars (Highest Resdex Boolean Search Weight)
    roles = ["data engineer", "aws data", "platform engineer", "big data", "etl developer"]
    if any(r in first_30 for r in roles):
        score += 20
    else:
        feedback.append("Front-loading suggestion: Place target role title (e.g. 'Data Engineer') in first 30 chars.")

    # 2. Experience Indicator in First 45 chars
    exp_indicators = ["3.5 yoe", "3+ yoe", "3 yoe", "3.5+ years", "3+ years", "3 years", "3.5 yrs", "3 yrs"]
    if any(exp in first_45 for exp in exp_indicators):
        score += 15
    else:
        feedback.append("Front-loading suggestion: Place experience (e.g. '3.5 YOE') near the front so recruiters see it on mobile cards.")

    # 3. Core High-Demand Tech Keywords in First 70 chars (Before Desktop/Mobile Truncation)
    key_tech = ["pyspark", "spark", "databricks", "aws", "sql", "python", "snowflake", "redshift", "glue", "kafka"]
    tech_count_front = sum(1 for t in key_tech if t in first_70)
    if tech_count_front >= 3:
        score += 25
    elif tech_count_front >= 1:
        score += 15
        feedback.append(f"Found {tech_count_front} tech keyword(s) in first 70 chars. Aim for at least 3 (e.g., PySpark, AWS, SQL).")
    else:
        feedback.append("No core tech stack visible in first 70 chars. Mobile recruiters won't see your skills in search results!")

    # 4. Architecture / Domain Depth
    arch_terms = ["etl", "elt", "pipeline", "lakehouse", "warehouse", "streaming", "distributed", "big data"]
    arch_count = sum(1 for a in arch_terms if a in text.lower())
    if arch_count >= 2:
        score += 20
    elif arch_count == 1:
        score += 12
    else:
        feedback.append("Consider adding architectural keywords like 'ETL/ELT', 'Lakehouse', or 'Pipelines'.")

    # 5. Conversion Magnet / Notice Period Trigger
    triggers = ["30 days notice", "15 days notice", "immediate", "serving notice", "1 month notice"]
    if any(tr in text.lower() for tr in triggers):
        score += 20
    else:
        feedback.append("High-converting trigger missing: Adding '30 Days Notice' attracts recruiters with urgent open positions.")

    return {
        "score": min(score, 100),
        "length": length,
        "max_length": MAX_HEADLINE_LENGTH,
        "is_valid": True,
        "front_loaded_chars": text[:70],
        "feedback": feedback if feedback else ["Headline perfectly optimized for Resdex ranking and recruiter CTR!"],
    }


def get_curated_headlines(config: Optional[dict] = None) -> List[str]:
    """
    Extracts candidate headline pool from config or returns default high-impact clusters.
    Ensures all returned headlines are strictly within the 250 character limit.
    """
    if config:
        personals = config.get("personals", {})
        configured = personals.get("resume_headlines")
        if configured and isinstance(configured, list) and len(configured) > 0:
            cleaned = [h.strip() for h in configured if h and h.strip() and len(h.strip()) <= MAX_HEADLINE_LENGTH]
            if cleaned:
                return cleaned

    return [c["headline"] for c in OPTIMIZED_KEYWORD_CLUSTERS]


def select_best_dynamic_headline(
    current_headline: str,
    config: Optional[dict] = None,
    recruiter_keywords: Optional[List[str]] = None,
) -> str:
    """
    Selects the next optimal, high-converting headline using intelligent keyword placement:
    1. Evaluates candidates from the pool.
    2. Cycles to a distinctly different keyword cluster to maintain search freshness.
    3. Gives extra weight to clusters matching active recruiter search terms (if available).
    4. Guarantees that the output is strictly <= 250 chars and non-identical to current.
    """
    candidates = get_curated_headlines(config)
    if not candidates:
        candidates = [c["headline"] for c in OPTIMIZED_KEYWORD_CLUSTERS]

    from profile_booster import normalize_headline_for_comparison

    norm_current = normalize_headline_for_comparison(current_headline)

    # Match current candidate
    match_idx = -1
    for idx, c in enumerate(candidates):
        if normalize_headline_for_comparison(c) == norm_current:
            match_idx = idx
            break

    # If recruiter keywords are available, find candidates that match trending search terms
    active_terms = [k.lower().strip() for k in (recruiter_keywords or []) if k]
    scored_candidates = []
    for idx, c in enumerate(candidates):
        if normalize_headline_for_comparison(c) == norm_current:
            continue
        c_low = c.lower()
        relevance_bonus = sum(2 for term in active_terms if term in c_low)
        quality = evaluate_headline_quality(c)["score"]
        # Give rotation distance bonus if we have match_idx
        rotation_bonus = 5 if match_idx != -1 and idx == (match_idx + 1) % len(candidates) else 0
        scored_candidates.append((quality + relevance_bonus + rotation_bonus, idx, c))

    if scored_candidates:
        scored_candidates.sort(key=lambda x: x[0], reverse=True)
        return scored_candidates[0][2]

    # Fallback rotation
    if match_idx != -1:
        next_idx = (match_idx + 1) % len(candidates)
        return candidates[next_idx]

    for c in candidates:
        if normalize_headline_for_comparison(c) != norm_current:
            return c

    return candidates[0]

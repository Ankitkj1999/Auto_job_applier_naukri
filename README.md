# 🚀 Naukri Auto Applier & Profile Booster

An intelligent, fully automated assistant for **Naukri.com** built for Data Engineers, Software Engineers, and tech professionals. It handles high-frequency daily profile boosting (updating your Resdex ranking to "Today"), searches targeted roles, automatically answers screening questionnaires in the chatbot drawer, and produces an interactive, zero-dependency analytics dashboard.

---

## 🌟 Key Capabilities

1. **⚡ Daily Profile Freshness (Resdex Booster):**
   - Touches resume headline and re-uploads your resume PDF.
   - Refreshes your profile's **"Last Active / Last Updated"** status to **"Today"**, keeping your profile at the top of recruiter searches.
   - Engages with recruiter notifications and optimizes job recommendation feeds.

2. **🤖 Questionnaire & Chatbot Automation:**
   - Detects Naukri's conversational application drawer.
   - Automatically answers screening questions (Notice Period, CTC, Experience by skill, Location preferences, Graduation year, etc.) and auto-stores new questions in `screening_questions.json`.

3. **📊 Standalone Analytics & Insights (`insights.html`):**
   - Automatically generates a single-file, zero-dependency visual dashboard with Chart.js.
   - Visualizes applications over time, profile match criteria rates (*Early Applicant, Keyskills, Location, Experience, Industry*), top companies, and location hubs.
   - Includes full search and filtering over your applied job history.

4. **🗂 Portable Resume Detection:**
   - Simply drop your resume (`.pdf`) into the project root directory or `resumes/` folder.
   - The bot auto-detects and uses it without requiring hardcoded absolute paths in `config.json`.

5. **🌐 External Career Portal Tracker:**
   - Detects jobs requiring direct application on external career sites (Workday, Greenhouse, Taleo, etc.).
   - Classifies companies into prioritized tiers (Tier 1 Giants, Tier 2 Top MNCs, Tier 3 Tech Startups) and maintains a checklist in [`external_jobs_tracker.md`](./external_jobs_tracker.md).

6. **🛡 Persistent, Safe Browser Profile:**
   - Stores cookies in a dedicated Chrome profile (`~/.naukri-bot-profile`).
   - Log in manually **once**; your session stays logged in without triggering OTP or captchas on subsequent runs.

---

## 🛠️ Prerequisites

- **Operating System:** Linux, macOS, or Windows (WSL / PowerShell)
- **Python:** Python 3.10 or higher
- **Google Chrome:** Installed on the host system

---

## 🚀 Quick Start (3 Steps)

### Step 1: Clone & Configure Resume
Drop your resume PDF into this directory:
```bash
cp /path/to/my_resume.pdf ./My_Resume.pdf
```
*(The bot auto-detects any `.pdf` file in the project folder if `default_resume_path` is omitted or empty).*

### Step 2: Edit `config.json`
Configure your personal information, target roles, and notice period in `config.json` (see full guide below).

### Step 3: Run the Bot
Use the built-in one-click launcher:
```bash
./start.sh
```
Or directly with Python:
```bash
python3 main.py
```

On your **first run**, Chrome will open to Naukri's login page. Log in once (via credentials, OTP, or Google). Once logged in, the bot saves the session into `~/.naukri-bot-profile` and will run automatically in future sessions.

---

## 💻 Command Reference & CLI Options

You can run specific routines directly from the CLI or shell script:

| Command | Action |
| :--- | :--- |
| `./start.sh boost` or `python main.py boost` | Refreshes resume, touches headline, and engages recruiter actions |
| `./start.sh apply` or `python main.py apply` | Searches target keywords and auto-applies to matching jobs |
| `./start.sh all` or `python main.py` | Full automation (Boost Profile + Apply) |
| `./start.sh tracker` or `python main.py tracker` | Views and syncs the External Priority Jobs checklist |
| `./start.sh insights` or `python main.py insights` | Builds/refreshes the self-contained `insights.html` dashboard |

---

## ⚙️ `config.json` Configuration Guide

All behaviors are customized through `config.json`:

### 1. `personals` (Candidate Profile & Answers)
```json
{
  "personals": {
    "full_name": "Your Name",
    "email": "your.email@example.com",
    "phone": "9876543210",
    "current_city": "Gurugram",
    "target_locations": ["Gurugram", "Noida", "Delhi / NCR"],
    "notice_period_days": 30,
    "notice_period_months": "1 Month",
    "current_ctc_lpa": 13,
    "expected_ctc_lpa": 18,
    "total_experience_years": 3.5,
    "current_company": "Current Employer Name",
    "graduation_year": "2023",
    "graduation_years": "2019 - 2023",
    "preferred_interview_time": "1:30 PM",
    "dob": "15/08/1999",
    "resume_headline": "Data Engineer with 3+ years in Python, SQL, Spark & AWS...",
    "default_resume_path": ""
  }
}
```
*Note: If `default_resume_path` is left empty or not found, the bot automatically scans the project directory for any `.pdf` resume.*

### 2. `search` (Search & Filtering Criteria)
```json
{
  "search": {
    "search_terms": ["Data Engineer", "PySpark Developer", "AWS Data Engineer"],
    "freshness_days": 3,
    "locations": ["Gurgaon", "Noida", "Delhi / NCR"],
    "fallback_locations": ["Bengaluru", "Hyderabad", "Pune"],
    "experience": 3,
    "experience_levels": [3, 4],
    "min_experience": 1,
    "max_experience": 6,
    "max_applications_per_run": 65,
    "max_pages_per_keyword": 10,
    "title_mandatory_words": ["data engineer", "spark", "etl", "aws data"],
    "title_bad_words": ["Frontend", "Full Stack", "Sales", "Intern", "QA"]
  }
}
```

### 3. `skills_experience` (Chatbot Skill Mapping)
Maps specific technical skills to years of experience. When chatbot questionnaires ask questions like *"How many years of experience do you have in Snowflake?"*, the bot looks up the answer here:
```json
{
  "skills_experience": {
    "python": 3,
    "sql": 3,
    "aws": 3,
    "spark": 3,
    "pyspark": 3,
    "databricks": 3,
    "snowflake": 3,
    "airflow": 2
  }
}
```

### 4. `settings` & `company_priority`
* **`headless`**: Set to `false` (recommended) to monitor the browser or `true` for silent background execution.
* **`company_priority`**: Define `tier_1_companies` and `tier_2_companies` to categorize external portal jobs in `external_jobs_tracker.md`.

---

## ⏰ Automated Daily Schedule (Cron Job)

To run the profile booster automatically every weekday morning at 9:00 AM:
```bash
crontab -e
```
Add the following line:
```cron
0 9 * * 1-5 /home/ankit/Documents/Code/Auto_job_applier_naukri/start.sh boost >> /home/ankit/Documents/Code/Auto_job_applier_naukri/cron.log 2>&1
```

---

## 📊 Analytics Dashboard

Open `insights.html` in your web browser:
```bash
# Linux
xdg-open insights.html

# macOS
open insights.html
```
The dashboard runs completely offline without requiring any server, displaying application trends, top companies, match criteria percentages, and full submission history.

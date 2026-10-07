import os
import csv
import json
import logging
from typing import Dict, Any, List

logger = logging.getLogger("NaukriBot")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APPLIED_JOBS_CSV = os.path.join(BASE_DIR, "applied_jobs.csv")
EXTERNAL_JOBS_CSV = os.path.join(BASE_DIR, "external_jobs.csv")
INSIGHTS_JSON = os.path.join(BASE_DIR, "application_insights.json")
INSIGHTS_HTML = os.path.join(BASE_DIR, "insights.html")


def load_applied_jobs(csv_path: str = APPLIED_JOBS_CSV) -> List[Dict[str, str]]:
    """Loads applied jobs from applied_jobs.csv."""
    jobs = []
    if not os.path.isfile(csv_path):
        return jobs
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                cleaned = {k.strip(): (v or "").strip() for k, v in row.items() if k}
                if cleaned.get("Job ID") or cleaned.get("Title"):
                    jobs.append(cleaned)
    except Exception as e:
        logger.warning(f"Error reading {csv_path}: {e}")
    return jobs


def load_external_jobs(csv_path: str = EXTERNAL_JOBS_CSV) -> List[Dict[str, str]]:
    """Loads external jobs from external_jobs.csv."""
    jobs = []
    if not os.path.isfile(csv_path):
        return jobs
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                cleaned = {k.strip(): (v or "").strip() for k, v in row.items() if k}
                if cleaned.get("Job ID") or cleaned.get("Title") or cleaned.get("Company"):
                    jobs.append(cleaned)
    except Exception as e:
        logger.warning(f"Error reading {csv_path}: {e}")
    return jobs


def load_application_insights(json_path: str = INSIGHTS_JSON) -> List[Dict[str, Any]]:
    """Loads application insights from application_insights.json."""
    if not os.path.isfile(json_path):
        return []
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
    except Exception as e:
        logger.warning(f"Error reading {json_path}: {e}")
    return []


def generate_insights_html(
    csv_path: str = APPLIED_JOBS_CSV,
    json_path: str = INSIGHTS_JSON,
    output_html_path: str = INSIGHTS_HTML,
    external_csv_path: str = EXTERNAL_JOBS_CSV,
) -> str:
    """
    Builds a standalone, zero-dependency HTML dashboard embedding
    applied_jobs.csv, external_jobs.csv, and application_insights.json data.
    """
    applied_jobs = load_applied_jobs(csv_path)
    external_jobs = load_external_jobs(external_csv_path)
    insights = load_application_insights(json_path)

    # Encode safely as JSON for browser script consumption
    applied_jobs_json_str = json.dumps(applied_jobs, ensure_ascii=False)
    external_jobs_json_str = json.dumps(external_jobs, ensure_ascii=False)
    insights_json_str = json.dumps(insights, ensure_ascii=False)

    html_template = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Naukri Bot Insights & Analytics Dashboard</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
  <style>
    :root {{
      --bg-color: #0f172a;
      --card-bg: #1e293b;
      --card-border: #334155;
      --text-main: #f8fafc;
      --text-muted: #94a3b8;
      --primary: #38bdf8;
      --primary-hover: #0284c7;
      --accent: #818cf8;
      --success: #34d399;
      --warning: #fbbf24;
      --danger: #f87171;
      --tier-1-bg: rgba(251, 191, 36, 0.18);
      --tier-1-border: rgba(251, 191, 36, 0.4);
      --tier-1-text: #fde047;
      --tier-2-bg: rgba(129, 140, 248, 0.18);
      --tier-2-border: rgba(129, 140, 248, 0.4);
      --tier-2-text: #a5b4fc;
      --tier-3-bg: rgba(148, 163, 184, 0.15);
      --tier-3-border: rgba(148, 163, 184, 0.3);
      --tier-3-text: #cbd5e1;
    }}
    * {{
      box-sizing: border-box;
      margin: 0;
      padding: 0;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    }}
    body {{
      background-color: var(--bg-color);
      color: var(--text-main);
      padding: 24px;
      line-height: 1.5;
    }}
    .header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding-bottom: 24px;
      border-bottom: 1px solid var(--card-border);
      margin-bottom: 24px;
      flex-wrap: wrap;
      gap: 16px;
    }}
    .title-group h1 {{
      font-size: 1.8rem;
      font-weight: 700;
      display: flex;
      align-items: center;
      gap: 10px;
    }}
    .title-group p {{
      color: var(--text-muted);
      font-size: 0.95rem;
      margin-top: 4px;
    }}
    .stats-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 16px;
      margin-bottom: 24px;
    }}
    .stat-card {{
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 12px;
      padding: 20px;
      box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
      display: flex;
      flex-direction: column;
      gap: 6px;
    }}
    .stat-label {{
      font-size: 0.82rem;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.05em;
      font-weight: 600;
    }}
    .stat-value {{
      font-size: 1.9rem;
      font-weight: 700;
      color: var(--text-main);
    }}
    .stat-subtext {{
      font-size: 0.8rem;
      color: var(--text-muted);
    }}
    .charts-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(450px, 1fr));
      gap: 20px;
      margin-bottom: 28px;
    }}
    .chart-card {{
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 12px;
      padding: 20px;
      box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
      display: flex;
      flex-direction: column;
      min-height: 340px;
    }}
    .chart-card h3 {{
      font-size: 1.1rem;
      font-weight: 600;
      margin-bottom: 16px;
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    .chart-container {{
      position: relative;
      flex: 1;
      width: 100%;
      min-height: 260px;
    }}
    .table-section {{
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 12px;
      padding: 24px;
      box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
    }}
    
    /* Navigation Tabs */
    .tabs-nav {{
      display: flex;
      gap: 8px;
      border-bottom: 2px solid var(--card-border);
      margin-bottom: 20px;
      overflow-x: auto;
    }}
    .tab-btn {{
      background: transparent;
      border: none;
      color: var(--text-muted);
      font-size: 1.05rem;
      font-weight: 600;
      padding: 12px 20px;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 10px;
      border-bottom: 3px solid transparent;
      margin-bottom: -2px;
      transition: all 0.2s ease;
      white-space: nowrap;
    }}
    .tab-btn:hover {{
      color: var(--text-main);
      background: rgba(255, 255, 255, 0.03);
      border-radius: 8px 8px 0 0;
    }}
    .tab-btn.active {{
      color: var(--primary);
      border-bottom-color: var(--primary);
    }}
    .tab-badge {{
      background: #334155;
      color: var(--text-main);
      font-size: 0.75rem;
      padding: 2px 8px;
      border-radius: 12px;
      font-weight: 700;
    }}
    .tab-btn.active .tab-badge {{
      background: rgba(56, 189, 248, 0.2);
      color: var(--primary);
    }}

    /* Table Toolbar */
    .table-toolbar {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 16px;
      flex-wrap: wrap;
      gap: 12px;
    }}
    .toolbar-left {{
      display: flex;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
    }}
    .toolbar-right {{
      display: flex;
      align-items: center;
      gap: 12px;
      color: var(--text-muted);
      font-size: 0.88rem;
    }}
    .search-input {{
      background: var(--bg-color);
      border: 1px solid var(--card-border);
      color: var(--text-main);
      padding: 9px 14px;
      border-radius: 8px;
      font-size: 0.9rem;
      outline: none;
      min-width: 280px;
      transition: border-color 0.2s;
    }}
    .search-input:focus {{
      border-color: var(--primary);
    }}
    .select-input {{
      background: var(--bg-color);
      border: 1px solid var(--card-border);
      color: var(--text-main);
      padding: 8px 12px;
      border-radius: 8px;
      font-size: 0.88rem;
      outline: none;
      cursor: pointer;
    }}
    .select-input:focus {{
      border-color: var(--primary);
    }}
    .table-wrapper {{
      overflow-x: auto;
      max-height: 600px;
      border: 1px solid var(--card-border);
      border-radius: 8px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      text-align: left;
      font-size: 0.88rem;
    }}
    th {{
      background-color: #1e293b;
      position: sticky;
      top: 0;
      z-index: 10;
      padding: 12px 14px;
      border-bottom: 2px solid var(--card-border);
      color: var(--text-muted);
      font-weight: 600;
      user-select: none;
      cursor: pointer;
    }}
    th:hover {{
      color: var(--primary);
    }}
    th .sort-icon {{
      font-size: 0.75rem;
      margin-left: 4px;
      opacity: 0.6;
    }}
    td {{
      padding: 12px 14px;
      border-bottom: 1px solid #33415560;
      color: var(--text-main);
      vertical-align: middle;
    }}
    tr:hover {{
      background-color: #33415530;
    }}
    a.job-link {{
      color: var(--primary);
      text-decoration: none;
      font-weight: 500;
      display: inline-flex;
      align-items: center;
      gap: 4px;
    }}
    a.job-link:hover {{
      text-decoration: underline;
    }}
    a.btn-direct-apply {{
      background: rgba(56, 189, 248, 0.15);
      border: 1px solid rgba(56, 189, 248, 0.4);
      color: var(--primary);
      padding: 4px 10px;
      border-radius: 6px;
      text-decoration: none;
      font-size: 0.8rem;
      font-weight: 600;
      display: inline-flex;
      align-items: center;
      gap: 4px;
      transition: all 0.2s;
    }}
    a.btn-direct-apply:hover {{
      background: var(--primary);
      color: #0f172a;
    }}
    .badge {{
      display: inline-block;
      padding: 3px 8px;
      border-radius: 6px;
      font-size: 0.75rem;
      font-weight: 600;
      white-space: nowrap;
    }}
    .badge-applied {{
      background: rgba(52, 211, 153, 0.15);
      color: var(--success);
      border: 1px solid rgba(52, 211, 153, 0.3);
    }}
    .badge-external {{
      background: rgba(251, 191, 36, 0.15);
      color: var(--warning);
      border: 1px solid rgba(251, 191, 36, 0.3);
    }}
    .badge-skipped {{
      background: rgba(148, 163, 184, 0.15);
      color: var(--text-muted);
      border: 1px solid rgba(148, 163, 184, 0.3);
    }}
    .badge-tier-1 {{
      background: var(--tier-1-bg);
      color: var(--tier-1-text);
      border: 1px solid var(--tier-1-border);
    }}
    .badge-tier-2 {{
      background: var(--tier-2-bg);
      color: var(--tier-2-text);
      border: 1px solid var(--tier-2-border);
    }}
    .badge-tier-3 {{
      background: var(--tier-3-bg);
      color: var(--tier-3-text);
      border: 1px solid var(--tier-3-border);
    }}
    .badge-pending {{
      background: rgba(56, 189, 248, 0.15);
      color: var(--primary);
      border: 1px solid rgba(56, 189, 248, 0.3);
    }}

    /* Pagination Controls */
    .pagination-bar {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-top: 16px;
      flex-wrap: wrap;
      gap: 12px;
    }}
    .pagination-info {{
      font-size: 0.88rem;
      color: var(--text-muted);
    }}
    .pagination-nav {{
      display: flex;
      align-items: center;
      gap: 6px;
    }}
    .page-btn {{
      background: var(--bg-color);
      border: 1px solid var(--card-border);
      color: var(--text-main);
      padding: 6px 12px;
      border-radius: 6px;
      cursor: pointer;
      font-size: 0.85rem;
      transition: all 0.15s;
    }}
    .page-btn:hover:not(:disabled) {{
      border-color: var(--primary);
      color: var(--primary);
    }}
    .page-btn:disabled {{
      opacity: 0.4;
      cursor: not-allowed;
    }}
    .page-btn.active {{
      background: var(--primary);
      border-color: var(--primary);
      color: #0f172a;
      font-weight: 700;
    }}
    .footer {{
      margin-top: 32px;
      text-align: center;
      color: var(--text-muted);
      font-size: 0.85rem;
    }}
    .empty-state {{
      text-align: center;
      padding: 40px;
      color: var(--text-muted);
      font-size: 0.95rem;
    }}
  </style>
</head>
<body>
  <div class="header">
    <div class="title-group">
      <h1><span>📊</span> Naukri Bot Analytics & Insights</h1>
      <p>Automated job application history, target company opportunities & profile intelligence report</p>
    </div>
    <div id="last-updated" style="color: var(--text-muted); font-size: 0.9rem;"></div>
  </div>

  <div class="stats-grid">
    <div class="stat-card">
      <span class="stat-label">Total Applied History</span>
      <span class="stat-value" id="stat-total-applied" style="color: var(--primary);">0</span>
      <span class="stat-subtext" id="stat-applied-subtext">0 direct applications</span>
    </div>
    <div class="stat-card">
      <span class="stat-label">External Opportunities</span>
      <span class="stat-value" id="stat-external-tracked" style="color: var(--warning);">0</span>
      <span class="stat-subtext" id="stat-tier1-subtext">0 Tier 1 high priority</span>
    </div>
    <div class="stat-card">
      <span class="stat-label">Unique Companies</span>
      <span class="stat-value" id="stat-unique-companies" style="color: var(--accent);">0</span>
      <span class="stat-subtext">Across all runs & tracked jobs</span>
    </div>
    <div class="stat-card">
      <span class="stat-label">Profile Match Rate</span>
      <span class="stat-value" id="stat-match-rate" style="color: var(--success);">0%</span>
      <span class="stat-subtext">Naukri recruiter score alignment</span>
    </div>
  </div>

  <div class="charts-grid">
    <div class="chart-card">
      <h3><span>📈</span> Applications Over Time (Daily)</h3>
      <div class="chart-container">
        <canvas id="timelineChart"></canvas>
      </div>
    </div>
    <div class="chart-card">
      <h3><span>🎯</span> Naukri Profile Match Breakdown</h3>
      <div class="chart-container">
        <canvas id="matchChart"></canvas>
      </div>
    </div>
    <div class="chart-card">
      <h3><span>🏢</span> Top Target Companies</h3>
      <div class="chart-container">
        <canvas id="companiesChart"></canvas>
      </div>
    </div>
    <div class="chart-card">
      <h3><span>📍</span> Applications by Location</h3>
      <div class="chart-container">
        <canvas id="locationsChart"></canvas>
      </div>
    </div>
  </div>

  <div class="table-section">
    <!-- Tabs Nav -->
    <div class="tabs-nav">
      <button class="tab-btn active" id="tabBtnApplied" onclick="switchTab('applied')">
        <span>📋</span> Applied Jobs History
        <span class="tab-badge" id="badgeAppliedCount">0</span>
      </button>
      <button class="tab-btn" id="tabBtnExternal" onclick="switchTab('external')">
        <span>🌐</span> External Jobs (Company Sites)
        <span class="tab-badge" id="badgeExternalCount">0</span>
      </button>
    </div>

    <!-- Toolbar -->
    <div class="table-toolbar">
      <div class="toolbar-left">
        <input type="text" id="searchInput" class="search-input" placeholder="Search by title, company, location...">
        <select id="statusFilter" class="select-input" onchange="handleFilterChange()">
          <option value="">All Statuses</option>
          <option value="applied">Applied Only</option>
          <option value="external">External / Company Site</option>
        </select>
        <select id="tierFilter" class="select-input" style="display: none;" onchange="handleFilterChange()">
          <option value="">All Tiers</option>
          <option value="tier 1">Tier 1 (High Priority)</option>
          <option value="tier 2">Tier 2 (Medium Priority)</option>
          <option value="tier 3">Tier 3 (Standard)</option>
        </select>
      </div>
      <div class="toolbar-right">
        <label for="pageSizeSelect">Rows per page:</label>
        <select id="pageSizeSelect" class="select-input" onchange="handlePageSizeChange(this.value)">
          <option value="50">50</option>
          <option value="100">100</option>
          <option value="250">250</option>
          <option value="500">500</option>
          <option value="all">All</option>
        </select>
      </div>
    </div>

    <!-- Applied Jobs Table View -->
    <div id="appliedTableView">
      <div class="table-wrapper">
        <table id="appliedJobsTable">
          <thead>
            <tr>
              <th onclick="handleSort('applied', 'Date')">Date <span class="sort-icon" id="sort-applied-Date">▼</span></th>
              <th onclick="handleSort('applied', 'Title')">Job Title <span class="sort-icon" id="sort-applied-Title"></span></th>
              <th onclick="handleSort('applied', 'Company')">Company <span class="sort-icon" id="sort-applied-Company"></span></th>
              <th onclick="handleSort('applied', 'Location')">Location <span class="sort-icon" id="sort-applied-Location"></span></th>
              <th onclick="handleSort('applied', 'Status')">Status <span class="sort-icon" id="sort-applied-Status"></span></th>
              <th>Link</th>
            </tr>
          </thead>
          <tbody id="appliedTableBody"></tbody>
        </table>
      </div>
    </div>

    <!-- External Jobs Table View -->
    <div id="externalTableView" style="display: none;">
      <div class="table-wrapper">
        <table id="externalJobsTable">
          <thead>
            <tr>
              <th onclick="handleSort('external', 'Date Discovered')">Date Discovered <span class="sort-icon" id="sort-external-Date Discovered">▼</span></th>
              <th onclick="handleSort('external', 'Title')">Job Title <span class="sort-icon" id="sort-external-Title"></span></th>
              <th onclick="handleSort('external', 'Company')">Company <span class="sort-icon" id="sort-external-Company"></span></th>
              <th onclick="handleSort('external', 'Priority Tier')">Priority Tier <span class="sort-icon" id="sort-external-Priority Tier"></span></th>
              <th onclick="handleSort('external', 'Location')">Location <span class="sort-icon" id="sort-external-Location"></span></th>
              <th onclick="handleSort('external', 'Experience')">Experience <span class="sort-icon" id="sort-external-Experience"></span></th>
              <th onclick="handleSort('external', 'Status')">Status <span class="sort-icon" id="sort-external-Status"></span></th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody id="externalTableBody"></tbody>
        </table>
      </div>
    </div>

    <!-- Pagination -->
    <div class="pagination-bar">
      <div class="pagination-info" id="paginationInfo">Showing 0 of 0 entries</div>
      <div class="pagination-nav" id="paginationNav"></div>
    </div>
  </div>

  <div class="footer">
    Generated automatically by <strong>Naukri Auto Applier & Profile Booster</strong> &bull; Standalone Analytics Report
  </div>

  <script>
    const APPLIED_DATA = {applied_jobs_json_str};
    const EXTERNAL_DATA = {external_jobs_json_str};
    const INSIGHTS_DATA = {insights_json_str};

    document.getElementById('last-updated').textContent = 'Report refreshed: ' + new Date().toLocaleString();

    // Helper: HTML Escaping
    function escapeHtml(str) {{
      if (str === null || str === undefined) return '';
      return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
    }}

    // State Management
    let currentTab = 'applied';
    let currentPage = 1;
    let pageSize = 50;
    let sortField = {{ applied: 'Date', external: 'Date Discovered' }};
    let sortAsc = {{ applied: false, external: false }}; // Default descending by date

    // 1. Calculate Summary Stats
    const totalApplied = APPLIED_DATA.length;
    const totalExternal = EXTERNAL_DATA.length;

    let appliedDirectCount = 0;
    let externalSkippedCount = 0;
    APPLIED_DATA.forEach(j => {{
      const st = (j['Status'] || '').toLowerCase();
      if (st.includes('applied')) appliedDirectCount++;
      else if (st.includes('external')) externalSkippedCount++;
    }});

    const tier1Count = EXTERNAL_DATA.filter(j => (j['Priority Tier'] || '').toLowerCase().includes('tier 1')).length;
    
    // Unique Companies combined
    const allCompanyNames = new Set([
      ...APPLIED_DATA.map(j => (j['Company'] || '').trim().toLowerCase()).filter(Boolean),
      ...EXTERNAL_DATA.map(j => (j['Company'] || '').trim().toLowerCase()).filter(Boolean)
    ]);

    document.getElementById('stat-total-applied').textContent = totalApplied.toLocaleString();
    document.getElementById('stat-applied-subtext').textContent = appliedDirectCount.toLocaleString() + ' direct applied on Naukri';
    document.getElementById('stat-external-tracked').textContent = totalExternal.toLocaleString();
    document.getElementById('stat-tier1-subtext').textContent = tier1Count.toLocaleString() + ' Tier 1 top company roles';
    document.getElementById('stat-unique-companies').textContent = allCompanyNames.size.toLocaleString();

    document.getElementById('badgeAppliedCount').textContent = totalApplied.toLocaleString();
    document.getElementById('badgeExternalCount').textContent = totalExternal.toLocaleString();

    // Match Rate calculation from INSIGHTS_DATA
    let matchTotal = 0;
    let matchSuccess = 0;
    const criteriaCounts = {{}};

    INSIGHTS_DATA.forEach(item => {{
      if (item.criteria) {{
        Object.entries(item.criteria).forEach(([crit, passed]) => {{
          if (!criteriaCounts[crit]) criteriaCounts[crit] = {{ passed: 0, total: 0 }};
          criteriaCounts[crit].total++;
          matchTotal++;
          if (passed === true) {{
            criteriaCounts[crit].passed++;
            matchSuccess++;
          }}
        }});
      }}
    }});

    const overallMatchPct = matchTotal > 0 ? Math.round((matchSuccess / matchTotal) * 100) : 0;
    document.getElementById('stat-match-rate').textContent = (matchTotal > 0 ? overallMatchPct : 100) + '%';

    // Chart Global Styling
    Chart.defaults.color = '#94a3b8';
    Chart.defaults.borderColor = '#334155';

    // 2. Render Charts
    // Timeline Chart
    const datesMap = {{}};
    APPLIED_DATA.forEach(j => {{
      const d = (j['Date'] || '').split(' ')[0];
      if (d && d.length >= 8) {{
        datesMap[d] = (datesMap[d] || 0) + 1;
      }}
    }});
    const sortedDates = Object.keys(datesMap).sort();
    const recentDates = sortedDates.slice(-14);

    new Chart(document.getElementById('timelineChart'), {{
      type: 'line',
      data: {{
        labels: recentDates,
        datasets: [{{
          label: 'Applications',
          data: recentDates.map(d => datesMap[d]),
          borderColor: '#38bdf8',
          backgroundColor: 'rgba(56, 189, 248, 0.1)',
          fill: true,
          tension: 0.3,
          borderWidth: 2,
          pointBackgroundColor: '#38bdf8'
        }}]
      }},
      options: {{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{ legend: {{ display: false }} }},
        scales: {{
          y: {{ beginAtZero: true, grid: {{ color: '#33415560' }} }},
          x: {{ grid: {{ display: false }} }}
        }}
      }}
    }});

    // Match Criteria Chart
    const critLabels = Object.keys(criteriaCounts);
    const critRates = critLabels.map(k => {{
      const c = criteriaCounts[k];
      return c.total > 0 ? Math.round((c.passed / c.total) * 100) : 0;
    }});

    new Chart(document.getElementById('matchChart'), {{
      type: 'bar',
      data: {{
        labels: critLabels.length > 0 ? critLabels : ['Keyskills', 'Experience', 'Location', 'Early Applicant'],
        datasets: [{{
          label: 'Match %',
          data: critLabels.length > 0 ? critRates : [100, 100, 100, 100],
          backgroundColor: critRates.map(v => v >= 80 ? '#34d399' : (v >= 50 ? '#fbbf24' : '#f87171')),
          borderRadius: 6
        }}]
      }},
      options: {{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{ legend: {{ display: false }} }},
        scales: {{
          y: {{ max: 100, beginAtZero: true, grid: {{ color: '#33415560' }} }},
          x: {{ grid: {{ display: false }} }}
        }}
      }}
    }});

    // Top Companies Chart
    const companyMap = {{}};
    APPLIED_DATA.forEach(j => {{
      const comp = (j['Company'] || 'Unknown').trim();
      if (comp) {{
        companyMap[comp] = (companyMap[comp] || 0) + 1;
      }}
    }});
    const topCompanies = Object.entries(companyMap)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 10);

    new Chart(document.getElementById('companiesChart'), {{
      type: 'bar',
      data: {{
        labels: topCompanies.map(c => c[0].length > 20 ? c[0].substring(0, 18) + '...' : c[0]),
        datasets: [{{
          label: 'Applications',
          data: topCompanies.map(c => c[1]),
          backgroundColor: '#818cf8',
          borderRadius: 6
        }}]
      }},
      options: {{
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{ legend: {{ display: false }} }},
        scales: {{
          x: {{ beginAtZero: true, grid: {{ color: '#33415560' }} }},
          y: {{ grid: {{ display: false }} }}
        }}
      }}
    }});

    // Locations Chart
    const locMap = {{}};
    APPLIED_DATA.forEach(j => {{
      let loc = (j['Location'] || 'Other').trim();
      if (loc.toLowerCase().includes('gurgaon') || loc.toLowerCase().includes('gurugram')) loc = 'Gurugram';
      else if (loc.toLowerCase().includes('noida')) loc = 'Noida';
      else if (loc.toLowerCase().includes('delhi')) loc = 'Delhi / NCR';
      else if (loc.toLowerCase().includes('bengaluru') || loc.toLowerCase().includes('bangalore')) loc = 'Bengaluru';
      else if (loc.toLowerCase().includes('hyderabad')) loc = 'Hyderabad';
      else if (loc.toLowerCase().includes('pune')) loc = 'Pune';
      else if (loc.toLowerCase().includes('mumbai')) loc = 'Mumbai';
      else loc = 'Other Hubs';
      locMap[loc] = (locMap[loc] || 0) + 1;
    }});

    const locLabels = Object.keys(locMap);
    new Chart(document.getElementById('locationsChart'), {{
      type: 'doughnut',
      data: {{
        labels: locLabels,
        datasets: [{{
          data: locLabels.map(l => locMap[l]),
          backgroundColor: ['#38bdf8', '#818cf8', '#34d399', '#f472b6', '#fbbf24', '#a78bfa', '#38bdf888', '#94a3b8']
        }}]
      }},
      options: {{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{
          legend: {{ position: 'right', labels: {{ boxWidth: 12, padding: 12 }} }}
        }}
      }}
    }});

    // 3. Tab Switching & Filtering Logic
    function switchTab(tab) {{
      currentTab = tab;
      currentPage = 1;
      
      const tabBtnApplied = document.getElementById('tabBtnApplied');
      const tabBtnExternal = document.getElementById('tabBtnExternal');
      const appliedView = document.getElementById('appliedTableView');
      const externalView = document.getElementById('externalTableView');
      const statusFilter = document.getElementById('statusFilter');
      const tierFilter = document.getElementById('tierFilter');

      if (tab === 'applied') {{
        tabBtnApplied.classList.add('active');
        tabBtnExternal.classList.remove('active');
        appliedView.style.display = 'block';
        externalView.style.display = 'none';
        statusFilter.style.display = 'inline-block';
        tierFilter.style.display = 'none';
      }} else {{
        tabBtnApplied.classList.remove('active');
        tabBtnExternal.classList.add('active');
        appliedView.style.display = 'none';
        externalView.style.display = 'block';
        statusFilter.style.display = 'none';
        tierFilter.style.display = 'inline-block';
      }}

      renderCurrentTable();
    }}

    function handleFilterChange() {{
      currentPage = 1;
      renderCurrentTable();
    }}

    function handlePageSizeChange(val) {{
      pageSize = val === 'all' ? Infinity : parseInt(val, 10);
      currentPage = 1;
      renderCurrentTable();
    }}

    function handleSort(tab, field) {{
      if (sortField[tab] === field) {{
        sortAsc[tab] = !sortAsc[tab];
      }} else {{
        sortField[tab] = field;
        // Default date sorting to descending, others to ascending
        sortAsc[tab] = field.toLowerCase().includes('date') ? false : true;
      }}
      updateSortIcons(tab);
      renderCurrentTable();
    }}

    function updateSortIcons(tab) {{
      const headers = tab === 'applied' 
        ? ['Date', 'Title', 'Company', 'Location', 'Status']
        : ['Date Discovered', 'Title', 'Company', 'Priority Tier', 'Location', 'Experience', 'Status'];
      
      headers.forEach(h => {{
        const iconEl = document.getElementById(`sort-${{tab}}-${{h}}`);
        if (iconEl) {{
          if (sortField[tab] === h) {{
            iconEl.textContent = sortAsc[tab] ? '▲' : '▼';
            iconEl.style.opacity = '1';
          }} else {{
            iconEl.textContent = '';
            iconEl.style.opacity = '0.4';
          }}
        }}
      }});
    }}

    function getFilteredAndSortedData() {{
      const search = (document.getElementById('searchInput').value || '').toLowerCase().trim();
      
      if (currentTab === 'applied') {{
        const statusFilterVal = (document.getElementById('statusFilter').value || '').toLowerCase();
        
        let filtered = APPLIED_DATA.filter(j => {{
          if (statusFilterVal) {{
            const st = (j['Status'] || '').toLowerCase();
            if (statusFilterVal === 'applied' && !st.includes('applied')) return false;
            if (statusFilterVal === 'external' && !st.includes('external')) return false;
          }}
          if (!search) return true;
          return (j['Title'] || '').toLowerCase().includes(search) ||
                 (j['Company'] || '').toLowerCase().includes(search) ||
                 (j['Location'] || '').toLowerCase().includes(search) ||
                 (j['Status'] || '').toLowerCase().includes(search) ||
                 (j['Date'] || '').toLowerCase().includes(search) ||
                 (j['Job ID'] || '').toLowerCase().includes(search);
        }});

        const f = sortField.applied;
        const asc = sortAsc.applied;
        filtered.sort((a, b) => {{
          const valA = (a[f] || '').trim();
          const valB = (b[f] || '').trim();
          return asc ? valA.localeCompare(valB) : valB.localeCompare(valA);
        }});

        return filtered;
      }} else {{
        const tierFilterVal = (document.getElementById('tierFilter').value || '').toLowerCase();
        
        let filtered = EXTERNAL_DATA.filter(j => {{
          if (tierFilterVal) {{
            const tier = (j['Priority Tier'] || '').toLowerCase();
            if (!tier.includes(tierFilterVal)) return false;
          }}
          if (!search) return true;
          return (j['Title'] || '').toLowerCase().includes(search) ||
                 (j['Company'] || '').toLowerCase().includes(search) ||
                 (j['Location'] || '').toLowerCase().includes(search) ||
                 (j['Priority Tier'] || '').toLowerCase().includes(search) ||
                 (j['Experience'] || '').toLowerCase().includes(search) ||
                 (j['Date Discovered'] || '').toLowerCase().includes(search) ||
                 (j['Job ID'] || '').toLowerCase().includes(search);
        }});

        const f = sortField.external;
        const asc = sortAsc.external;
        filtered.sort((a, b) => {{
          const valA = (a[f] || '').trim();
          const valB = (b[f] || '').trim();
          return asc ? valA.localeCompare(valB) : valB.localeCompare(valA);
        }});

        return filtered;
      }}
    }}

    function renderCurrentTable() {{
      const data = getFilteredAndSortedData();
      const totalCount = data.length;
      const totalPages = pageSize === Infinity ? 1 : Math.max(1, Math.ceil(totalCount / pageSize));
      
      if (currentPage > totalPages) currentPage = totalPages;
      if (currentPage < 1) currentPage = 1;

      const startIndex = pageSize === Infinity ? 0 : (currentPage - 1) * pageSize;
      const endIndex = pageSize === Infinity ? totalCount : Math.min(startIndex + pageSize, totalCount);
      const pageData = data.slice(startIndex, endIndex);

      if (currentTab === 'applied') {{
        renderAppliedTable(pageData);
      }} else {{
        renderExternalTable(pageData);
      }}

      renderPagination(totalCount, totalPages, startIndex, endIndex);
    }}

    function renderAppliedTable(rows) {{
      const tbody = document.getElementById('appliedTableBody');
      tbody.innerHTML = '';

      if (rows.length === 0) {{
        tbody.innerHTML = '<tr><td colspan="6" class="empty-state">No matching applied jobs found.</td></tr>';
        return;
      }}

      rows.forEach(j => {{
        const tr = document.createElement('tr');
        
        const dateTd = document.createElement('td');
        dateTd.textContent = j['Date'] || '';
        dateTd.style.whiteSpace = 'nowrap';
        
        const titleTd = document.createElement('td');
        titleTd.style.fontWeight = '600';
        titleTd.textContent = j['Title'] || 'Untitled Job';

        const compTd = document.createElement('td');
        compTd.textContent = j['Company'] || 'Unknown';

        const locTd = document.createElement('td');
        locTd.textContent = j['Location'] || '-';

        const stTd = document.createElement('td');
        const st = j['Status'] || 'Applied';
        const badge = document.createElement('span');
        badge.className = 'badge ' + (
          st.toLowerCase().includes('applied') ? 'badge-applied' :
          st.toLowerCase().includes('external') ? 'badge-external' : 'badge-skipped'
        );
        badge.textContent = st;
        stTd.appendChild(badge);

        const linkTd = document.createElement('td');
        if (j['Job URL']) {{
          const a = document.createElement('a');
          a.className = 'job-link';
          a.href = j['Job URL'];
          a.target = '_blank';
          a.rel = 'noreferrer noopener';
          a.textContent = 'View Job ↗';
          linkTd.appendChild(a);
        }} else {{
          linkTd.textContent = '-';
        }}

        tr.appendChild(dateTd);
        tr.appendChild(titleTd);
        tr.appendChild(compTd);
        tr.appendChild(locTd);
        tr.appendChild(stTd);
        tr.appendChild(linkTd);

        tbody.appendChild(tr);
      }});
    }}

    function renderExternalTable(rows) {{
      const tbody = document.getElementById('externalTableBody');
      tbody.innerHTML = '';

      if (rows.length === 0) {{
        tbody.innerHTML = '<tr><td colspan="8" class="empty-state">No matching external target company jobs found.</td></tr>';
        return;
      }}

      rows.forEach(j => {{
        const tr = document.createElement('tr');
        
        const dateTd = document.createElement('td');
        dateTd.textContent = j['Date Discovered'] || '';
        dateTd.style.whiteSpace = 'nowrap';
        
        const titleTd = document.createElement('td');
        titleTd.style.fontWeight = '600';
        titleTd.textContent = j['Title'] || 'Untitled Job';

        const compTd = document.createElement('td');
        compTd.textContent = j['Company'] || 'Unknown';

        const tierTd = document.createElement('td');
        const tier = j['Priority Tier'] || 'Tier 3 (Standard)';
        const tierBadge = document.createElement('span');
        if (tier.toLowerCase().includes('tier 1')) {{
          tierBadge.className = 'badge badge-tier-1';
          tierBadge.textContent = '⭐ ' + tier;
        }} else if (tier.toLowerCase().includes('tier 2')) {{
          tierBadge.className = 'badge badge-tier-2';
          tierBadge.textContent = '🔷 ' + tier;
        }} else {{
          tierBadge.className = 'badge badge-tier-3';
          tierBadge.textContent = tier;
        }}
        tierTd.appendChild(tierBadge);

        const locTd = document.createElement('td');
        locTd.textContent = j['Location'] || '-';

        const expTd = document.createElement('td');
        expTd.textContent = j['Experience'] || '-';

        const stTd = document.createElement('td');
        const st = j['Status'] || 'Pending';
        const stBadge = document.createElement('span');
        stBadge.className = 'badge ' + (st.toLowerCase().includes('applied') ? 'badge-applied' : 'badge-pending');
        stBadge.textContent = st;
        stTd.appendChild(stBadge);

        const actTd = document.createElement('td');
        actTd.style.whiteSpace = 'nowrap';
        const applyUrl = j['Direct Apply URL'] || '';
        const naukriUrl = j['Naukri URL'] || '';

        if (applyUrl && applyUrl.startsWith('http')) {{
          const a = document.createElement('a');
          a.className = 'btn-direct-apply';
          a.href = applyUrl;
          a.target = '_blank';
          a.rel = 'noreferrer noopener';
          a.textContent = 'Apply Direct ↗';
          actTd.appendChild(a);
        }} else if (naukriUrl && naukriUrl.startsWith('http')) {{
          const a = document.createElement('a');
          a.className = 'job-link';
          a.href = naukriUrl;
          a.target = '_blank';
          a.rel = 'noreferrer noopener';
          a.textContent = 'View Naukri ↗';
          actTd.appendChild(a);
        }} else {{
          actTd.textContent = '-';
        }}

        tr.appendChild(dateTd);
        tr.appendChild(titleTd);
        tr.appendChild(compTd);
        tr.appendChild(tierTd);
        tr.appendChild(locTd);
        tr.appendChild(expTd);
        tr.appendChild(stTd);
        tr.appendChild(actTd);

        tbody.appendChild(tr);
      }});
    }}

    function renderPagination(totalCount, totalPages, startIndex, endIndex) {{
      const infoEl = document.getElementById('paginationInfo');
      const navEl = document.getElementById('paginationNav');
      
      if (totalCount === 0) {{
        infoEl.textContent = 'Showing 0 to 0 of 0 entries';
        navEl.innerHTML = '';
        return;
      }}

      infoEl.textContent = `Showing ${{startIndex + 1}} to ${{endIndex}} of ${{totalCount.toLocaleString()}} entries`;

      if (pageSize === Infinity || totalPages <= 1) {{
        navEl.innerHTML = '';
        return;
      }}

      let navHtml = '';
      navHtml += `<button class="page-btn" onclick="goToPage(1)" ${{currentPage === 1 ? 'disabled' : ''}}>« First</button>`;
      navHtml += `<button class="page-btn" onclick="goToPage(${{currentPage - 1}})" ${{currentPage === 1 ? 'disabled' : ''}}>‹ Prev</button>`;

      // Generate page number window
      const startP = Math.max(1, currentPage - 2);
      const endP = Math.min(totalPages, currentPage + 2);

      for (let p = startP; p <= endP; p++) {{
        navHtml += `<button class="page-btn ${{p === currentPage ? 'active' : ''}}" onclick="goToPage(${{p}})">${{p}}</button>`;
      }}

      navHtml += `<button class="page-btn" onclick="goToPage(${{currentPage + 1}})" ${{currentPage === totalPages ? 'disabled' : ''}}>Next ›</button>`;
      navHtml += `<button class="page-btn" onclick="goToPage(${{totalPages}})" ${{currentPage === totalPages ? 'disabled' : ''}}>Last »</button>`;

      navEl.innerHTML = navHtml;
    }}

    function goToPage(page) {{
      currentPage = page;
      renderCurrentTable();
    }}

    // Search Listener
    document.getElementById('searchInput').addEventListener('input', () => {{
      currentPage = 1;
      renderCurrentTable();
    }});

    // Initial render
    updateSortIcons('applied');
    updateSortIcons('external');
    renderCurrentTable();
  </script>
</body>
</html>
"""

    try:
        with open(output_html_path, "w", encoding="utf-8") as f:
            f.write(html_template)
        logger.info(f"✓ Standalone insights dashboard generated at: {output_html_path}")
    except Exception as e:
        logger.error(f"Failed to generate insights HTML at {output_html_path}: {e}")

    return output_html_path


if __name__ == "__main__":
    generate_insights_html()

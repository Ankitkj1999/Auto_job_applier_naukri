import os
import csv
import json
import logging
from typing import Dict, Any, List

logger = logging.getLogger("NaukriBot")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APPLIED_JOBS_CSV = os.path.join(BASE_DIR, "applied_jobs.csv")
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
) -> str:
    """
    Builds a standalone, zero-dependency HTML dashboard embedding both
    applied_jobs.csv and application_insights.json data.
    """
    applied_jobs = load_applied_jobs(csv_path)
    insights = load_application_insights(json_path)

    # Encode safely as JSON for browser script consumption
    applied_jobs_json_str = json.dumps(applied_jobs, ensure_ascii=False)
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
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
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
      font-size: 0.85rem;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.05em;
      font-weight: 600;
    }}
    .stat-value {{
      font-size: 2rem;
      font-weight: 700;
      color: var(--text-main);
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
      padding: 20px;
      box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
    }}
    .table-header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 16px;
      flex-wrap: wrap;
      gap: 12px;
    }}
    .table-header h3 {{
      font-size: 1.2rem;
      font-weight: 600;
    }}
    .search-input {{
      background: var(--bg-color);
      border: 1px solid var(--card-border);
      color: var(--text-main);
      padding: 8px 14px;
      border-radius: 8px;
      font-size: 0.9rem;
      outline: none;
      min-width: 260px;
      transition: border-color 0.2s;
    }}
    .search-input:focus {{
      border-color: var(--primary);
    }}
    .table-wrapper {{
      overflow-x: auto;
      max-height: 520px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      text-align: left;
      font-size: 0.9rem;
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
    }}
    td {{
      padding: 12px 14px;
      border-bottom: 1px solid #33415560;
      color: var(--text-main);
    }}
    tr:hover {{
      background-color: #33415530;
    }}
    a.job-link {{
      color: var(--primary);
      text-decoration: none;
      font-weight: 500;
    }}
    a.job-link:hover {{
      text-decoration: underline;
    }}
    .badge {{
      display: inline-block;
      padding: 3px 8px;
      border-radius: 6px;
      font-size: 0.75rem;
      font-weight: 600;
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
    .footer {{
      margin-top: 32px;
      text-align: center;
      color: var(--text-muted);
      font-size: 0.85rem;
    }}
  </style>
</head>
<body>
  <div class="header">
    <div class="title-group">
      <h1><span>📊</span> Naukri Bot Analytics & Insights</h1>
      <p>Single-file automated job application and profile matching intelligence report</p>
    </div>
    <div id="last-updated" style="color: var(--text-muted); font-size: 0.9rem;"></div>
  </div>

  <div class="stats-grid">
    <div class="stat-card">
      <span class="stat-label">Total Applications</span>
      <span class="stat-value" id="stat-total-applied" style="color: var(--primary);">0</span>
    </div>
    <div class="stat-card">
      <span class="stat-label">Unique Companies</span>
      <span class="stat-value" id="stat-unique-companies" style="color: var(--accent);">0</span>
    </div>
    <div class="stat-card">
      <span class="stat-label">Profile Match Rate</span>
      <span class="stat-value" id="stat-match-rate" style="color: var(--success);">0%</span>
    </div>
    <div class="stat-card">
      <span class="stat-label">External Skipped</span>
      <span class="stat-value" id="stat-external-skipped" style="color: var(--warning);">0</span>
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
      <h3><span>🏢</span> Top 10 Target Companies</h3>
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
    <div class="table-header">
      <h3><span>📋</span> Applied Jobs History</h3>
      <input type="text" id="searchInput" class="search-input" placeholder="Search by job title, company, location...">
    </div>
    <div class="table-wrapper">
      <table id="jobsTable">
        <thead>
          <tr>
            <th>Date</th>
            <th>Job Title</th>
            <th>Company</th>
            <th>Location</th>
            <th>Status</th>
            <th>Link</th>
          </tr>
        </thead>
        <tbody id="tableBody"></tbody>
      </table>
    </div>
  </div>

  <div class="footer">
    Generated automatically by <strong>Naukri Auto Applier & Profile Booster</strong> &bull; Open in any browser
  </div>

  <script>
    const APPLIED_DATA = {applied_jobs_json_str};
    const INSIGHTS_DATA = {insights_json_str};

    document.getElementById('last-updated').textContent = 'Report refreshed: ' + new Date().toLocaleString();

    // 1. Calculate Summary Stats
    const totalJobs = APPLIED_DATA.length;
    const uniqueCompanies = new Set(APPLIED_DATA.map(j => (j['Company'] || '').trim().toLowerCase()).filter(Boolean)).size;
    
    let appliedCount = 0;
    let externalCount = 0;
    APPLIED_DATA.forEach(j => {{
      const st = (j['Status'] || '').toLowerCase();
      if (st.includes('applied')) appliedCount++;
      else if (st.includes('external')) externalCount++;
    }});

    document.getElementById('stat-total-applied').textContent = totalJobs.toLocaleString();
    document.getElementById('stat-unique-companies').textContent = uniqueCompanies.toLocaleString();
    document.getElementById('stat-external-skipped').textContent = externalCount.toLocaleString();

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

    // Render Table
    const tableBody = document.getElementById('tableBody');
    function renderTable(filterText = '') {{
      tableBody.innerHTML = '';
      const filter = filterText.toLowerCase().trim();
      const filtered = APPLIED_DATA.filter(j => {{
        if (!filter) return true;
        return (j['Title'] || '').toLowerCase().includes(filter) ||
               (j['Company'] || '').toLowerCase().includes(filter) ||
               (j['Location'] || '').toLowerCase().includes(filter) ||
               (j['Status'] || '').toLowerCase().includes(filter);
      }});

      filtered.slice(0, 100).forEach(j => {{
        const tr = document.createElement('tr');
        
        const dateTd = document.createElement('td');
        dateTd.textContent = j['Date'] || '';
        
        const titleTd = document.createElement('td');
        titleTd.style.fontWeight = '500';
        titleTd.textContent = j['Title'] || 'Untitled';

        const compTd = document.createElement('td');
        compTd.textContent = j['Company'] || 'Unknown';

        const locTd = document.createElement('td');
        locTd.textContent = j['Location'] || '';

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

        tableBody.appendChild(tr);
      }});
    }}

    renderTable();
    document.getElementById('searchInput').addEventListener('input', (e) => {{
      renderTable(e.target.value);
    }});
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

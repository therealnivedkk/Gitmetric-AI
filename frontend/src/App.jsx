import { useCallback, useEffect, useRef, useState } from 'react';
import axios from 'axios';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  BarElement,
  Title,
  Tooltip,
  Legend,
} from 'chart.js';
import { Bar } from 'react-chartjs-2';
import './App.css';

ChartJS.register(CategoryScale, LinearScale, BarElement, Title, Tooltip, Legend);

const API_BASE = 'http://localhost:8000';
// Matches FastAPI route @app.get("/api/analyses")
const HISTORY_ENDPOINT = `${API_BASE}/api/analyses`;

const EXAMPLE_REPOS = ['../repositories/tqdm', '../repositories/arrow', 'https://github.com/pallets/flask'];

const GAUGE_RADIUS = 54;
const GAUGE_CIRCUMFERENCE = 2 * Math.PI * GAUGE_RADIUS;

// Sidebar structure. `badge` keys are resolved against live data in the component.
const NAV_SECTIONS = [
  {
    title: 'Workspace',
    items: [
      { id: 'scanner',  label: 'Repository Scanner', needsData: false },
      { id: 'overview', label: 'Health Overview', needsData: true },
    ],
  },
  {
    title: 'Deep Analytics',
    items: [
      { id: 'ml', label: 'ML Explainability', needsData: true },
      { id: 'hotspots', label: 'Hotspot Matrix', needsData: true, badge: 'hotspots' },
      { id: 'security', label: 'Security Findings', needsData: true, badge: 'security' },
      { id: 'recs', label: 'Recommendations', needsData: true, badge: 'recs' },
    ],
  },
  {
    title: 'History & Export',
    items: [
      { id: 'history', label: 'Scan History', needsData: false, badge: 'history' },
      { id: 'export', label: 'Export Reports', needsData: true },
    ],
  },
];

const VIEW_META = {
  scanner: ['Repository Scanner', 'Ingest a local path or GitHub URL and run a scan'],
  overview: ['Health Overview', 'Repository Health Index and core pillars'],
  ml: ['ML Explainability', 'What the Random Forest model weighed, and how confident it is'],
  hotspots: ['Hotspot Matrix', 'Churn × complexity — where defects are most likely to cluster'],
  security: ['Security Findings', 'AST-based anti-patterns and leaked secrets'],
  recs: ['Recommendations', 'Prioritized remediation actions'],
  history: ['Scan History', 'Previously analyzed repositories'],
  export: ['Export Reports', 'Download this analysis as a shareable report'],
};

// Normalizes any health label (RHI label or ML label) to one of three bands.
function bandOf(label) {
  if (!label) return 'stable';
  const l = label.toLowerCase();
  if (l.includes('health')) return 'healthy';
  if (l.includes('stable')) return 'stable';
  return 'needs-attention';
}

const isGithubUrl = (s) => /^(https?:\/\/)?(www\.)?github\.com\/[^/\s]+\/[^/\s]+/i.test(s.trim()) || /^git@github\.com:/i.test(s.trim());

export default function App() {
  const [token, setToken] = useState(localStorage.getItem('token') || '');
  const [user, setUser] = useState(localStorage.getItem('username') || '');
  const [isRegister, setIsRegister] = useState(false);
  const [authForm, setAuthForm] = useState({ username: '', email: '', password: '' });

  const [repoPath, setRepoPath] = useState('');
  const [shallowClone, setShallowClone] = useState(true);
  const [branch, setBranch] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [data, setData] = useState(null);
  const [apiState, setApiState] = useState('unknown'); // unknown | connected | offline

  const [view, setView] = useState('scanner');
  const [collapsed, setCollapsed] = useState(false); // desktop icon-only mode
  const [drawerOpen, setDrawerOpen] = useState(false); // mobile off-canvas
  const [gaugeReady, setGaugeReady] = useState(false);

  const [history, setHistory] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState('');

  const abortRef = useRef(null);
  const viewRef = useRef(null);

  // Animate the gauge whenever a new result arrives or the overview is shown
  useEffect(() => {
    setGaugeReady(false);
    if (data && view === 'overview') {
      const t = setTimeout(() => setGaugeReady(true), 80);
      return () => clearTimeout(t);
    }
  }, [data, view]);

  // Scroll the content area back to the top when switching views
  useEffect(() => {
    if (viewRef.current) viewRef.current.scrollTop = 0;
  }, [view]);

  const authHeaders = useCallback(() => ({ Authorization: `Bearer ${token}` }), [token]);

  const fetchHistory = useCallback(async () => {
    if (!token) return;
    setHistoryLoading(true);
    setHistoryError('');
    try {
      const res = await axios.get(HISTORY_ENDPOINT, { headers: authHeaders() });
      const rows = Array.isArray(res.data) ? res.data : res.data?.items || res.data?.history || [];
      setHistory(rows);
      setApiState('connected');
    } catch (err) {
      if (err.request && !err.response) setApiState('offline');
      setHistoryError(
        err.response?.status === 404
          ? 'History endpoint not found on the API yet.'
          : err.response?.data?.detail || 'Could not load scan history.'
      );
    } finally {
      setHistoryLoading(false);
    }
  }, [token, authHeaders]);

  useEffect(() => {
    fetchHistory();
  }, [fetchHistory]);

  const handleAuth = async (e) => {
    e.preventDefault();
    setError('');
    try {
      if (isRegister) {
        await axios.post(`${API_BASE}/auth/register`, authForm);
        setIsRegister(false);
        setError('Registration successful — please sign in.');
      } else {
        const res = await axios.post(`${API_BASE}/auth/login`, {
          username: authForm.username,
          password: authForm.password,
        });
        const jwt = res.data.access_token;
        setToken(jwt);
        setUser(authForm.username);
        localStorage.setItem('token', jwt);
        localStorage.setItem('username', authForm.username);
        setView('scanner');
      }
    } catch (err) {
      if (err.request && !err.response) setApiState('offline');
      setError(err.response?.data?.detail || 'Authentication failed');
    }
  };

  const handleLogout = () => {
    abortRef.current?.abort();
    setToken('');
    setUser('');
    setData(null);
    setHistory([]);
    setView('scanner');
    setApiState('unknown');
    localStorage.removeItem('token');
    localStorage.removeItem('username');
  };

  const runAnalysis = async () => {
    const target = repoPath.trim();
    if (!target || loading) return;

    const controller = new AbortController();
    abortRef.current = controller;

    setLoading(true);
    setError('');
    setNotice('');

    const fromGithub = isGithubUrl(target);
    // `repo_path` carries either a local path or a GitHub URL. The extra fields are hints
    // for the backend's clone step and are ignored by APIs that don't declare them.
    const payload = { repo_path: target };
    if (fromGithub) {
      payload.source = 'github';
      payload.shallow = shallowClone;
      if (branch.trim()) payload.branch = branch.trim();
    }

    try {
      const res = await axios.post(`${API_BASE}/api/analyze`, payload, {
        headers: authHeaders(),
        signal: controller.signal,
      });
      setData(res.data);
      setApiState('connected');
      setView('overview');
      fetchHistory();
    } catch (err) {
      if (axios.isCancel(err) || err.code === 'ERR_CANCELED') {
        setNotice('Scan cancelled.');
      } else {
        if (err.request && !err.response) setApiState('offline');
        setError(
          err.response?.data?.detail ||
            (fromGithub
              ? 'Analysis failed. Check the GitHub URL, branch, and that the repo is public.'
              : 'Analysis failed. Verify the repository path and try again.')
        );
      }
    } finally {
      setLoading(false);
      abortRef.current = null;
    }
  };

  const cancelAnalysis = () => abortRef.current?.abort();

  const loadPastAnalysis = async (analysisId) => {
    if (!analysisId) return;
    setLoading(true);
    setError('');
    try {
      const res = await axios.get(`${API_BASE}/api/analyses/${analysisId}`, {
        headers: authHeaders(),
      });
      setData(res.data);
      setRepoPath(res.data.repo_path || res.data.repo_name || '');
      setView('overview');
      setDrawerOpen(false);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to load past analysis.');
    } finally {
      setLoading(false);
    }
  };

  const openFromHistory = (row) => {
    if (row.id) {
      loadPastAnalysis(row.id);
    } else {
      const path = row.repo_path || row.repo_url || row.path || row.repo_name || '';
      setRepoPath(path);
      setView('scanner');
      setDrawerOpen(false);
    }
  };

  const goTo = (id) => {
    setView(id);
    setDrawerOpen(false);
  };

  const downloadPdfReport = () => {
    if (!data) return;
    const printWindow = window.open('', '_blank');
    const html = `
      <!DOCTYPE html>
      <html>
      <head>
        <title>GitMetric AI Audit - ${data.repo_name}</title>
        <style>
          body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; color: #14161b; margin: 30px; font-size: 13px; line-height: 1.5; }
          h1, h2, h3, h4 { color: #b3760f; margin-top: 0; }
          .header { border-bottom: 2px solid #dee2e6; padding-bottom: 12px; margin-bottom: 20px; display: flex; justify-content: space-between; align-items: flex-end; }
          .badge { display: inline-block; padding: 4px 8px; border-radius: 4px; font-weight: 600; font-size: 12px; }
          .badge-healthy { background: #d1f5e4; color: #0f7a4f; }
          .badge-stable { background: #dcecff; color: #1c5fa8; }
          .badge-needs { background: #ffe1e5; color: #b3283b; }
          .score-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 20px 0; }
          .score-box { border: 1px solid #ced4da; border-radius: 6px; padding: 10px; text-align: center; }
          .score-val { font-size: 22px; font-weight: bold; margin: 4px 0; }
          table { width: 100%; border-collapse: collapse; margin: 15px 0; font-size: 12px; }
          th, td { border: 1px solid #dee2e6; padding: 6px 10px; text-align: left; }
          th { background-color: #f8f9fa; }
          .rec-item { border-left: 4px solid #b3760f; background: #fdfdfd; padding: 8px 12px; margin-bottom: 10px; border-radius: 0 4px 4px 0; }
          .rec-item.CRITICAL { border-left-color: #dc3545; }
          .rec-item.HIGH { border-left-color: #ea580c; }
        </style>
      </head>
      <body>
        <div class="header">
          <div>
            <h2 style="margin-bottom: 4px;">GitMetric AI — Repository Audit Report</h2>
            <div><strong>Repository:</strong> <code>${data.repo_name}</code> | <strong>Scanned:</strong> ${new Date().toLocaleDateString()}</div>
          </div>
          <div style="text-align: right;">
            <div style="font-size: 28px; font-weight: bold; color: #b3760f;">${data.scores.overall_rhi} / 100</div>
            <span class="badge ${data.scores.label === 'Healthy' ? 'badge-healthy' : data.scores.label === 'Stable' ? 'badge-stable' : 'badge-needs'}">
              ${data.scores.label}
            </span>
          </div>
        </div>

        <h3>Executive Summary</h3>
        <p>${data.recommendations?.executive_summary}</p>
        <p><strong>ML Classification:</strong> <code>${data.ml_prediction?.ml_label}</code></p>

        <h3>Core Sub-Scores</h3>
        <div class="score-grid">
          <div class="score-box">
            <div>Code Quality</div>
            <div class="score-val">${data.scores.code_quality_score}</div>
            <small>McCabe Bands</small>
          </div>
          <div class="score-box">
            <div>Maintainability</div>
            <div class="score-val">${data.scores.maintainability_score}</div>
            <small>Radon MI</small>
          </div>
          <div class="score-box">
            <div>Development Activity</div>
            <div class="score-val">${data.scores.development_score}</div>
            <small>${data.aggregates.contributors} Authors</small>
          </div>
          <div class="score-box">
            <div>Change Risk</div>
            <div class="score-val">${data.scores.change_risk_score}</div>
            <small>${data.aggregates.total_churn.toLocaleString()} Churn</small>
          </div>
        </div>

        <h3>Top Defect Hotspots</h3>
        <table>
          <thead>
            <tr><th>File Path</th><th>Churn</th><th>Max CC</th><th>Hotspot Score</th></tr>
          </thead>
          <tbody>
            ${data.issues.hotspots.slice(0, 5).map(h => `
              <tr>
                <td><code>${h.filepath}</code></td>
                <td>${h.churn}</td>
                <td>${h.max_cc}</td>
                <td><strong>${h.hotspot_score}</strong></td>
              </tr>
            `).join('')}
          </tbody>
        </table>

        <h3>Quick Wins</h3>
        <ul>
          ${data.recommendations?.quick_wins?.map(w => `<li>${w}</li>`).join('')}
        </ul>

        <h3>Prioritized Recommendations</h3>
        ${data.recommendations?.recommendations?.map(r => `
          <div class="rec-item ${r.priority}">
            <strong>[${r.priority}] ${r.title}</strong>
            <div><strong>Action:</strong> ${r.action}</div>
            <div style="color: #6c757d; font-size: 11px;"><strong>Rationale:</strong> ${r.rationale}</div>
          </div>
        `).join('')}
      </body>
      </html>
    `;
    printWindow.document.write(html);
    printWindow.document.close();
    printWindow.focus();
    setTimeout(() => {
      printWindow.print();
    }, 400);
  };

  const downloadMarkdownReport = () => {
    if (!data) return;
    const content = `# GitMetric AI Report: ${data.repo_name}
**Overall RHI:** ${data.scores.overall_rhi} / 100 (${data.scores.label})
**ML Model Verdict:** ${data.ml_prediction?.ml_label}

## Executive Summary
${data.recommendations?.executive_summary}

## Core Sub-Scores
- **Code Quality:** ${data.scores.code_quality_score}/100
- **Maintainability:** ${data.scores.maintainability_score}/100
- **Development Activity:** ${data.scores.development_score}/100
- **Change Risk:** ${data.scores.change_risk_score}/100

## Quick Wins
${data.recommendations?.quick_wins?.map((w, i) => `${i + 1}. ${w}`).join('\n')}

## Prioritized Recommendations
${data.recommendations?.recommendations?.map(r => `### [${r.priority}] ${r.title}\n- **Action:** ${r.action}\n- **Rationale:** ${r.rationale}`).join('\n\n')}
`;
    const blob = new Blob([content], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${data.repo_name}_gitmetric_report.md`;
    a.click();
  };
  // Prepare ML Explainability Feature Importances for Chart.js
  const topFeatures = Object.entries(data?.ml_prediction?.feature_contributions || {}).slice(0, 8);

  const featureChartData = {
    labels: topFeatures.map(([k]) => k),
    datasets: [
      {
        label: 'Feature Importance Weight',
        data: topFeatures.map(([, v]) => v),
        backgroundColor: 'rgba(255, 176, 32, 0.75)',
        borderColor: 'rgba(255, 176, 32, 1)',
        borderWidth: 1,
        borderRadius: 3,
      },
    ],
  };

  const featureChartOptions = {
    indexAxis: 'y',
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: false },
      tooltip: {
        backgroundColor: '#171b24',
        borderColor: '#232836',
        borderWidth: 1,
        titleColor: '#e9ecf2',
        bodyColor: '#8991a3',
        titleFont: { family: "'JetBrains Mono', monospace", size: 11 },
        bodyFont: { family: "'JetBrains Mono', monospace", size: 11 },
        callbacks: { label: (ctx) => `weight: ${(ctx.raw * 100).toFixed(2)}%` },
      },
    },
    scales: {
      x: {
        beginAtZero: true,
        max: 0.2,
        grid: { color: '#1c2129' },
        ticks: { color: '#565e70', font: { family: "'JetBrains Mono', monospace", size: 10 } },
      },
      y: {
        grid: { display: false },
        ticks: { color: '#8991a3', font: { family: "'JetBrains Mono', monospace", size: 10 } },
      },
    },
  };

  // -----------------------------------------------------------------
  // Auth screen (full-screen, no sidebar)
  // -----------------------------------------------------------------
  if (!token) {
    return (
      <div className="auth-screen">
        <div className="auth-frame">
          <div className="auth-logo">
            <div className="brand">
              <span className="brand-dot" />
              <span className="brand-mark">Git<span className="accent">Metric AI</span></span>
            </div>
            <p>Intelligent repository health &amp; risk assessment platform</p>
          </div>
          <div className="auth-card">
            <h3>{isRegister ? 'Create an account' : 'Sign in'}</h3>
            <p className="hint">
              {isRegister ? 'Register to start scanning repositories.' : 'Enter your credentials to continue.'}
            </p>
            {error && <div className="error-banner">{error}</div>}
            <form onSubmit={handleAuth}>
              <div className="field">
                <label>Username</label>
                <input
                  type="text"
                  required
                  value={authForm.username}
                  onChange={(e) => setAuthForm({ ...authForm, username: e.target.value })}
                />
              </div>
              {isRegister && (
                <div className="field">
                  <label>Email</label>
                  <input
                    type="email"
                    required
                    value={authForm.email}
                    onChange={(e) => setAuthForm({ ...authForm, email: e.target.value })}
                  />
                </div>
              )}
              <div className="field">
                <label>Password</label>
                <input
                  type="password"
                  required
                  value={authForm.password}
                  onChange={(e) => setAuthForm({ ...authForm, password: e.target.value })}
                />
              </div>
              <button className="btn-primary" type="submit">
                {isRegister ? 'Register' : 'Sign in'}
              </button>
            </form>
            <div className="auth-switch">
              {isRegister ? 'Already have an account?' : "Don't have an account?"}{' '}
              <button onClick={() => { setIsRegister(!isRegister); setError(''); }}>
                {isRegister ? 'Sign in' : 'Register'}
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // -----------------------------------------------------------------
  // Derived values
  // -----------------------------------------------------------------
  const rhiBand = data ? bandOf(data.scores.label) : 'stable';
  const gaugeOffset = gaugeReady
    ? GAUGE_CIRCUMFERENCE - ((data?.scores?.overall_rhi || 0) / 100) * GAUGE_CIRCUMFERENCE
    : GAUGE_CIRCUMFERENCE;

  const hotspots = data?.issues?.hotspots || [];
  const securityIssues = data?.issues?.security_issues || [];
  const recList = data?.recommendations?.recommendations || [];

  const badgeValues = {
    hotspots: data ? hotspots.length : null,
    security: data ? securityIssues.length : null,
    recs: data ? data.recommendations?.total_recommendations ?? recList.length : null,
    history: history.length || null,
  };

  const status = loading
    ? { cls: 'scanning', text: 'Scanning…' }
    : apiState === 'offline'
      ? { cls: 'offline', text: 'API offline' }
      : apiState === 'connected'
        ? { cls: 'connected', text: 'API connected' }
        : { cls: 'idle', text: 'Idle' };

  const [viewTitle, viewSubtitle] = VIEW_META[view];
  const sourceKind = repoPath.trim() ? (isGithubUrl(repoPath) ? 'github' : 'local') : null;

  const severityOf = (sec) => {
    const s = (sec.severity || '').toLowerCase();
    if (s.startsWith('high') || s.startsWith('crit')) return 'high';
    if (s.startsWith('low')) return 'low';
    return 'medium';
  };

  const EmptyData = () => (
    <div className="empty-state">
      <span className="caret-blink">▍</span>
      <p>No analysis loaded yet. Scan a repository to see this view.</p>
      <button className="btn-run empty-cta" onClick={() => goTo('scanner')}>Go to Repository Scanner</button>
    </div>
  );

  // -----------------------------------------------------------------
  // Views
  // -----------------------------------------------------------------
  const renderScanner = () => (
    <>
      <div className={`scan-panel ${loading ? 'is-scanning' : ''}`}>
        <span className="scan-label">target repository</span>
        <div className="scan-row">
          <div className="scan-prompt">
            <span className="caret">$</span>
            <input
              type="text"
              placeholder="../repositories/repo_name  or  https://github.com/owner/repo"
              value={repoPath}
              disabled={loading}
              onChange={(e) => setRepoPath(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && runAnalysis()}
            />
            {sourceKind && <span className={`source-tag ${sourceKind}`}>{sourceKind === 'github' ? 'GitHub URL' : 'Local path'}</span>}
          </div>
          {loading ? (
            <button className="btn-cancel" onClick={cancelAnalysis}>Cancel scan</button>
          ) : (
            <button className="btn-run" onClick={runAnalysis} disabled={!repoPath.trim()}>Run analysis</button>
          )}
        </div>

        {sourceKind === 'github' && (
          <div className="clone-options">
            <label className="check">
              <input type="checkbox" checked={shallowClone} disabled={loading} onChange={(e) => setShallowClone(e.target.checked)} />
              Shallow clone (faster, recent history only)
            </label>
            <label className="branch-field">
              Branch
              <input type="text" placeholder="default branch" value={branch} disabled={loading} onChange={(e) => setBranch(e.target.value)} />
            </label>
          </div>
        )}

        <div className="quick-paths">
          <span>Try:</span>
          {EXAMPLE_REPOS.map((path) => (
            <button key={path} disabled={loading} onClick={() => setRepoPath(path)}>{path.replace('https://github.com/', 'gh:')}</button>
          ))}
        </div>
        {error && <div className="error-banner">{error}</div>}
        {notice && <div className="notice-banner">{notice}</div>}
      </div>

      {data && !loading && (
        <div className="panel last-scan">
          <div>
            <h5>Last scan: <span className="mono">{data.repo_name}</span></h5>
            <p className="panel-desc" style={{ marginBottom: 0 }}>RHI {data.scores.overall_rhi}/100 · {data.scores.label}</p>
          </div>
          <button className="btn-ghost" onClick={() => goTo('overview')}>Open health overview</button>
        </div>
      )}

      {!data && !loading && (
        <div className="empty-state">
          <span className="caret-blink">▍</span>
          <p>No scan yet — enter a repository path or GitHub URL and run an analysis.</p>
        </div>
      )}
    </>
  );

  const renderOverview = () => (
    <>
      <div className="verdict">
        <div>
          <span className="verdict-eyebrow">repository audit</span>
          <h2>{data.repo_name}</h2>
          <div className="verdict-pills">
            <span className={`pill ${rhiBand}`}>RHI: {data.scores.label}</span>
            <span className={`pill ${bandOf(data.ml_prediction?.ml_label)}`}>ML: {data.ml_prediction?.ml_label}</span>
          </div>
          <p className="verdict-summary">{data.recommendations?.executive_summary}</p>
        </div>
        <div className="gauge-block">
          <div className="gauge">
            <svg viewBox="0 0 128 128">
              <circle className="gauge-track" cx="64" cy="64" r={GAUGE_RADIUS} />
              <circle
                className={`gauge-fill ${rhiBand}`}
                cx="64"
                cy="64"
                r={GAUGE_RADIUS}
                strokeDasharray={GAUGE_CIRCUMFERENCE}
                strokeDashoffset={gaugeOffset}
              />
            </svg>
            <div className="gauge-value">
              <span className="num">{data.scores.overall_rhi}</span>
              <span className="denom">/ 100</span>
            </div>
          </div>
          <span className="gauge-caption">Repository Health Index</span>
        </div>
      </div>

      <div className="score-grid">
        {[
          ['Code quality', data.scores.code_quality_score, 'McCabe bands'],
          ['Maintainability', data.scores.maintainability_score, 'Radon MI'],
          ['Development activity', data.scores.development_score, `${data.aggregates.contributors} contributors`],
          ['Change risk', data.scores.change_risk_score, `${data.aggregates.total_churn?.toLocaleString()} churn lines`],
        ].map(([label, value, meta]) => (
          <div className="score-card" key={label}>
            <div className="label">{label}</div>
            <div className="value">{value}<span>/100</span></div>
            <div className="score-track"><div className="fill" style={{ width: `${value}%` }} /></div>
            <div className="meta">{meta}</div>
          </div>
        ))}
      </div>

      <div className="grid-2">
        <div className="panel">
          <h5>Repository metrics</h5>
          <p className="panel-desc">Snapshot pulled from the latest scan</p>
          <table className="kv-table">
            <tbody>
              <tr><td>Total LOC</td><td>{data.aggregates.total_loc?.toLocaleString()}</td></tr>
              <tr><td>Python files</td><td>{data.aggregates.file_count}</td></tr>
              <tr><td>Avg cyclomatic complexity</td><td>{data.aggregates.avg_cc}</td></tr>
              <tr><td>Documentation coverage</td><td>{data.aggregates.documentation_coverage}%</td></tr>
              <tr><td>Total commits</td><td>{data.aggregates.commit_count} ({data.aggregates.commit_freq}/wk)</td></tr>
              <tr><td>Top-3 churn concentration</td><td>{(data.aggregates.churn_concentration * 100).toFixed(1)}%</td></tr>
            </tbody>
          </table>
        </div>
        <div className="panel">
          <h5>Quick wins</h5>
          <p className="panel-desc">Fastest changes to move the needle</p>
          <ul className="quickwin-list">
            {data.recommendations?.quick_wins?.map((win, i) => (
              <li key={i}>
                <span className="quickwin-num">{i + 1}</span>
                <span>{win}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </>
  );

  const renderML = () => (
    <div className="grid-2">
      <div className="panel">
        <h5>Feature importances</h5>
        <p className="panel-desc">Trained Random Forest relative feature weights</p>
        <div className="chart-box">
          <Bar data={featureChartData} options={featureChartOptions} />
        </div>
      </div>
      <div className="panel">
        <h5>Prediction probabilities</h5>
        <p className="panel-desc">Confidence across the three health classes</p>
        {Object.entries(data.ml_prediction?.confidence || {}).map(([label, prob]) => (
          <div key={label} className="prob-row">
            <div className="prob-row-head">
              <span>{label}</span>
              <span className="val">{(prob * 100).toFixed(1)}%</span>
            </div>
            <div className="prob-track">
              <div className={`prob-fill ${bandOf(label)}`} style={{ width: `${prob * 100}%` }} />
            </div>
          </div>
        ))}
        <div className="model-note">
          <strong>Model:</strong> RandomForestClassifier — SMOTE-balanced, 200 estimators
        </div>
      </div>
    </div>
  );

  const renderHotspots = () => (
    <div className="panel">
      <h5>Defect hotspots</h5>
      <p className="panel-desc">High churn X high complexity</p>
      {hotspots.length === 0 ? (
        <p className="muted-note">No hotspots detected in this repository.</p>
      ) : (
        <div className="table-scroll">
          <table className="hotspot-table">
            <thead>
              <tr>
                <th>#</th>
                <th>File path</th>
                <th>Churn</th>
                <th>Avg CC</th>
                <th>Max CC</th>
                <th>Hotspot score</th>
              </tr>
            </thead>
            <tbody>
              {hotspots.map((h, i) => (
                <tr key={i}>
                  <td className="rank">{i + 1}</td>
                  <td className="filepath">{h.filepath}</td>
                  <td>{h.churn}</td>
                  <td>{h.avg_cc}</td>
                  <td><span className={`chip ${h.max_cc > 20 ? 'cc-high' : 'cc-mid'}`}>{h.max_cc}</span></td>
                  <td className="score">{h.hotspot_score}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );

  const renderSecurity = () => (
    <div className="panel">
      <h5>Detected security anti-patterns</h5>
      <p className="panel-desc">{securityIssues.length} finding{securityIssues.length === 1 ? '' : 's'}</p>
      {securityIssues.length === 0 ? (
        <p className="muted-note">No security anti-patterns or secret leaks were detected.</p>
      ) : (
        <div className="security-list">
          {securityIssues.map((sec, i) => {
            const sev = severityOf(sec);
            return (
              <div key={i} className={`security-item sev-${sev}`}>
                <div className="sec-head">
                  <div className="sec-title">
                    {sec.title} <span className="rule">({sec.rule_id})</span>
                  </div>
                  <span className={`sev-badge sev-${sev}`}>{sev}</span>
                </div>
                <div className="sec-loc">{sec.filepath}:{sec.lineno}</div>
                <p>{sec.description}</p>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );

  const renderRecs = () => (
    <div className="panel">
      <h5>Prioritized action items</h5>
      <p className="panel-desc">Ordered by impact and urgency</p>
      <div className="rec-grid">
        {recList.map((r, i) => (
          <div key={i} className={`rec-card prio-${r.priority?.toLowerCase()}`}>
            <div className="rec-head">
              <h6>{r.title}</h6>
              <span className={`prio-tag prio-${r.priority?.toLowerCase()}`}>{r.priority}</span>
            </div>
            <p><strong>Action:</strong> {r.action}</p>
            <p><strong>Rationale:</strong> {r.rationale}</p>
          </div>
        ))}
      </div>
    </div>
  );

  const renderHistory = () => (
    <div className="panel">
      <div className="panel-title-row">
        <div>
          <h5>Previous scans</h5>
          <p className="panel-desc">Stored in your account's database</p>
        </div>
        <button className="btn-ghost" onClick={fetchHistory} disabled={historyLoading}>
          {historyLoading ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>
      {historyError && <div className="error-banner" style={{ marginTop: 0 }}>{historyError}</div>}
      {!historyError && !historyLoading && history.length === 0 && (
        <p className="muted-note">No scans saved yet. Run your first analysis from the Repository Scanner.</p>
      )}
      <div className="history-list">
        {history.map((row, i) => {
          const score = row.overall_rhi ?? row.rhi ?? row.score;
          const label = row.label ?? row.rhi_label;
          const when = row.created_at || row.timestamp || row.scanned_at;
          return (
            <div key={row.id ?? i} className="history-row">
              <div className="history-main">
                <span className="mono history-name">{row.repo_name || row.repo_path || 'Unnamed repository'}</span>
                <span className="history-sub">{when ? new Date(when).toLocaleString() : '—'}</span>
              </div>
              {score != null && <span className="mono history-score">{score}</span>}
              {label && <span className={`pill ${bandOf(label)}`}>{label}</span>}
              <div style={{ display: 'flex', gap: '8px' }}>
                <button className="btn-ghost" onClick={() => openFromHistory(row)}>View Report</button>
                <button className="btn-ghost" onClick={() => {
                  setRepoPath(row.repo_path || row.repo_name || '');
                  setView('scanner');
                }}>Re-scan</button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );

  const renderExport = () => (
    <div className="grid-2">
      <div className="panel export-card">
        <h5>PDF report</h5>
        <p className="panel-desc">Opens a print-ready audit for <span className="mono">{data.repo_name}</span>. Choose “Save as PDF” in the print dialog.</p>
        <button className="btn-run" onClick={downloadPdfReport}>Export PDF</button>
      </div>
      <div className="panel export-card">
        <h5>Markdown report</h5>
        <p className="panel-desc">A portable .md summary you can commit alongside the repository or paste into an issue.</p>
        <button className="btn-run" onClick={downloadMarkdownReport}>Download .md</button>
      </div>
    </div>
  );

  const renderView = () => {
    if (view === 'scanner') return renderScanner();
    if (view === 'history') return renderHistory();
    if (!data) return <EmptyData />;
    switch (view) {
      case 'overview': return renderOverview();
      case 'ml': return renderML();
      case 'hotspots': return renderHotspots();
      case 'security': return renderSecurity();
      case 'recs': return renderRecs();
      case 'export': return renderExport();
      default: return null;
    }
  };

  // -----------------------------------------------------------------
  // Dashboard shell: sidebar + status bar + scrollable view
  // -----------------------------------------------------------------
  return (
    <div className={`dash ${collapsed ? 'is-collapsed' : ''} ${drawerOpen ? 'drawer-open' : ''}`}>
      {drawerOpen && <div className="scrim" onClick={() => setDrawerOpen(false)} />}

      <aside className="sidebar" aria-label="Primary navigation">
        <div className="sb-header">
          <div className="sb-brand">
            <span className="sb-logo">◆</span>
            <div className="sb-brand-text">
              <span className="sb-title">GitMetric AI</span>
              <span className="sb-version">v1.0</span>
            </div>
          </div>
          <button
            className="sb-collapse"
            onClick={() => setCollapsed(!collapsed)}
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            {collapsed ? '»' : '«'}
          </button>
        </div>

        <div className={`status-pill ${status.cls}`} title={status.text}>
          <span className="status-dot" />
          <span className="status-text">{status.text}</span>
        </div>

        <nav className="sb-nav">
          {NAV_SECTIONS.map((section) => (
            <div className="sb-section" key={section.title}>
              <div className="sb-section-title">{section.title}</div>
              {section.items.map((item) => {
                const badge = item.badge ? badgeValues[item.badge] : null;
                const locked = item.needsData && !data;
                return (
                  <button
                    key={item.id}
                    className={`sb-item ${view === item.id ? 'active' : ''} ${locked ? 'locked' : ''}`}
                    onClick={() => goTo(item.id)}
                    aria-current={view === item.id ? 'page' : undefined}
                    title={item.label}
                  >
                    <span className="sb-icon">{item.icon}</span>
                    <span className="sb-label">{item.label}</span>
                    {badge != null && (
                      <span className={`sb-badge ${item.badge === 'security' && badge > 0 ? 'danger' : ''}`}>{badge}</span>
                    )}
                  </button>
                );
              })}
            </div>
          ))}
        </nav>

        <div className="sb-footer">
          <div className="sb-user">
            <span className="sb-avatar">{user.charAt(0).toUpperCase() || '?'}</span>
            <span className="sb-username">{user}</span>
          </div>
          <button className="sb-signout" onClick={handleLogout} title="Sign out">
            <span className="sb-icon">⏻</span>
            <span className="sb-label">Sign Out</span>
          </button>
        </div>
      </aside>

      <div className="main-col">
        <header className="statusbar">
          <button className="hamburger" onClick={() => setDrawerOpen(true)} aria-label="Open navigation">☰</button>
          <div className="statusbar-title">
            <h1>{viewTitle}</h1>
            <p>{viewSubtitle}</p>
          </div>
          <div className="statusbar-right">
            {data && <span className="repo-chip mono" title="Loaded repository">{data.repo_name}</span>}
            <span className={`status-pill compact ${status.cls}`}>
              <span className="status-dot" />
              {status.text}
            </span>
          </div>
        </header>

        <main className="view" ref={viewRef}>
          <div className="view-inner">{renderView()}</div>
        </main>
      </div>
    </div>
  );
}
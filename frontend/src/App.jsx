import { useState } from 'react';
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

ChartJS.register(CategoryScale, LinearScale, BarElement, Title, Tooltip, Legend);

const API_BASE = 'http://localhost:8000';

export default function App() {
  const [token, setToken] = useState(localStorage.getItem('token') || '');
  const [user, setUser] = useState(localStorage.getItem('username') || '');
  const [isRegister, setIsRegister] = useState(false);

  // Form states
  const [authForm, setAuthForm] = useState({ username: '', email: '', password: '' });
  const [repoPath, setRepoPath] = useState('.....enter the path');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [data, setData] = useState(null);
  const [activeTab, setActiveTab] = useState('overview');

  const handleAuth = async (e) => {
    e.preventDefault();
    setError('');
    try {
      if (isRegister) {
        await axios.post(`${API_BASE}/auth/register`, authForm);
        setIsRegister(false);
        setError('Registration successful! Please login.');
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
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'Authentication failed');
    }
  };

  const handleLogout = () => {
    setToken('');
    setUser('');
    setData(null);
    localStorage.removeItem('token');
    localStorage.removeItem('username');
  };

  const runAnalysis = async () => {
    if (!repoPath) return;
    setLoading(true);
    setError('');
    try {
      const res = await axios.post(
        `${API_BASE}/api/analyze`,
        { repo_path: repoPath },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      setData(res.data);
      setActiveTab('overview');
    } catch (err) {
      setError(err.response?.data?.detail || 'Analysis failed. Please verify the repository path.');
    } finally {
      setLoading(false);
    }
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
          body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; color: #212529; margin: 30px; font-size: 13px; line-height: 1.5; }
          h1, h2, h3, h4 { color: #0d6efd; margin-top: 0; }
          .header { border-bottom: 2px solid #dee2e6; padding-bottom: 12px; margin-bottom: 20px; display: flex; justify-content: space-between; align-items: flex-end; }
          .badge { display: inline-block; padding: 4px 8px; border-radius: 4px; font-weight: 600; font-size: 12px; }
          .badge-healthy { background: #d1e7dd; color: #0f5132; }
          .badge-stable { background: #cff4fc; color: #055160; }
          .badge-needs { background: #fff3cd; color: #664d03; }
          .score-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 20px 0; }
          .score-box { border: 1px solid #ced4da; border-radius: 6px; padding: 10px; text-align: center; }
          .score-val { font-size: 22px; font-weight: bold; margin: 4px 0; }
          table { width: 100%; border-collapse: collapse; margin: 15px 0; font-size: 12px; }
          th, td { border: 1px solid #dee2e6; padding: 6px 10px; text-align: left; }
          th { background-color: #f8f9fa; }
          .rec-item { border-left: 4px solid #0d6efd; background: #fdfdfd; padding: 8px 12px; margin-bottom: 10px; border-radius: 0 4px 4px 0; }
          .rec-item.CRITICAL { border-left-color: #dc3545; }
          .rec-item.HIGH { border-left-color: #ffc107; }
        </style>
      </head>
      <body>
        <div class="header">
          <div>
            <h2 style="margin-bottom: 4px;">GitMetric AI — Repository Audit Report</h2>
            <div><strong>Repository:</strong> <code>${data.repo_name}</code> | <strong>Scanned:</strong> ${new Date().toLocaleDateString()}</div>
          </div>
          <div style="text-align: right;">
            <div style="font-size: 28px; font-weight: bold; color: #0d6efd;">${data.scores.overall_rhi} / 100</div>
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

  const getBadgeClass = (label) => {
    if (label === 'Healthy') return 'bg-success';
    if (label === 'Stable') return 'bg-primary';
    return 'bg-warning text-dark';
  };

  // Prepare ML Explainability Feature Importances for Chart.js
  const topFeatures = Object.entries(data?.ml_prediction?.feature_contributions || {})
    .slice(0, 8);

  const featureChartData = {
    labels: topFeatures.map(([k]) => k),
    datasets: [
      {
        label: 'Feature Importance Weight',
        data: topFeatures.map(([, v]) => v),
        backgroundColor: 'rgba(13, 110, 253, 0.75)',
        borderColor: 'rgba(13, 110, 253, 1)',
        borderWidth: 1,
      },
    ],
  };

  const featureChartOptions = {
    indexAxis: 'y',
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: false },
      tooltip: { callbacks: { label: (ctx) => `Weight: ${(ctx.raw * 100).toFixed(2)}%` } },
    },
    scales: {
      x: { beginAtZero: true, max: 0.20 },
    },
  };

  // Authentication Screen
  if (!token) {
    return (
      <div className="container mt-5" style={{ maxWidth: 450 }}>
        <div className="card shadow-sm p-4 border-0">
          <div className="text-center mb-3">
            <h2 className="text-primary fw-bold">GitMetric AI</h2>
            <p className="text-muted small">Autonomous Repository Health & Risk Assessment</p>
          </div>
          {error && <div className="alert alert-danger py-2 small">{error}</div>}
          <form onSubmit={handleAuth}>
            <div className="mb-3">
              <label className="form-label small fw-bold">Username</label>
              <input
                type="text"
                className="form-control"
                required
                value={authForm.username}
                onChange={(e) => setAuthForm({ ...authForm, username: e.target.value })}
              />
            </div>
            {isRegister && (
              <div className="mb-3">
                <label className="form-label small fw-bold">Email</label>
                <input
                  type="email"
                  className="form-control"
                  required
                  value={authForm.email}
                  onChange={(e) => setAuthForm({ ...authForm, email: e.target.value })}
                />
              </div>
            )}
            <div className="mb-3">
              <label className="form-label small fw-bold">Password</label>
              <input
                type="password"
                className="form-control"
                required
                value={authForm.password}
                onChange={(e) => setAuthForm({ ...authForm, password: e.target.value })}
              />
            </div>
            <button className="btn btn-primary w-100 mb-2" type="submit">
              {isRegister ? 'Register' : 'Login'}
            </button>
            <button
              type="button"
              className="btn btn-link w-100 text-decoration-none small"
              onClick={() => { setIsRegister(!isRegister); setError(''); }}
            >
              {isRegister ? 'Already have an account? Sign in' : "Don't have an account? Register"}
            </button>
          </form>
        </div>
      </div>
    );
  }

  return (
    <div className="container py-4">
      {/* Top Navbar */}
      <div className="d-flex justify-content-between align-items-center mb-4 pb-2 border-bottom">
        <div>
          <h3 className="text-primary fw-bold mb-0">GitMetric AI</h3>
          <small className="text-muted">Repository Health & Risk Assessment Platform</small>
        </div>
        <div className="d-flex align-items-center gap-3">
          <span className="badge bg-light text-dark border px-3 py-2">👤 {user}</span>
          <button className="btn btn-outline-danger btn-sm" onClick={handleLogout}>Logout</button>
        </div>
      </div>

      {/* Analysis Input Bar */}
      <div className="card shadow-sm p-3 mb-4 border-0">
        <label className="form-label small text-muted fw-bold">Enter Target Repository Path</label>
        <div className="row g-2 align-items-center">
          <div className="col">
            <input
              type="text"
              className="form-control"
              placeholder="e.g. ../repositories/tqdm or ../repositories/arrow"
              value={repoPath}
              onChange={(e) => setRepoPath(e.target.value)}
            />
          </div>
          <div className="col-auto">
            <button className="btn btn-primary px-4 fw-bold" onClick={runAnalysis} disabled={loading}>
              {loading ? 'Analyzing...' : 'Run Analysis'}
            </button>
          </div>
        </div>
        {error && <div className="alert alert-danger mt-3 mb-0 py-2 small">{error}</div>}
      </div>

      {/* Results View */}
      {data && (
        <>
          {/* Hero Verdict Banner */}
          <div className="card shadow-sm p-4 mb-4 border-0 bg-white">
            <div className="row align-items-center">
              <div className="col-md-7">
                <span className="text-uppercase text-muted small fw-bold">Repository Audit</span>
                <h2 className="fw-bold mb-2 text-dark">{data.repo_name}</h2>
                <div className="d-flex gap-3 mb-3">
                  <div>RHI Label: <span className={`badge ${getBadgeClass(data.scores.label)} ms-1`}>{data.scores.label}</span></div>
                  <div>ML Prediction: <span className={`badge ${getBadgeClass(data.ml_prediction?.ml_label)} ms-1`}>{data.ml_prediction?.ml_label}</span></div>
                </div>
                <p className="text-secondary small mb-0">{data.recommendations?.executive_summary}</p>
              </div>
              <div className="col-md-5 text-md-end text-center mt-3 mt-md-0">
                <div className="display-4 fw-bold text-primary">{data.scores.overall_rhi}</div>
                <div className="text-muted small">Repository Health Index (RHI / 100)</div>
                <div className="mt-3 d-flex justify-content-md-end justify-content-center gap-2">
                  <button className="btn btn-outline-secondary btn-sm" onClick={downloadMarkdownReport}>
                    Markdown (.md)
                  </button>
                  <button className="btn btn-outline-primary btn-sm" onClick={downloadPdfReport}>
                    Export PDF
                  </button>
                </div>
              </div>
            </div>
          </div>

          {/* Navigation Tabs */}
          <ul className="nav nav-pills mb-4">
            <li className="nav-item">
              <button
                className={`nav-link ${activeTab === 'overview' ? 'active fw-bold' : ''}`}
                onClick={() => setActiveTab('overview')}
              >
                Overview & Sub-Scores
              </button>
            </li>
            <li className="nav-item">
              <button
                className={`nav-link ${activeTab === 'explainability' ? 'active fw-bold' : ''}`}
                onClick={() => setActiveTab('explainability')}
              >
                ML Explainability (Feature Weights)
              </button>
            </li>
            <li className="nav-item">
              <button
                className={`nav-link ${activeTab === 'hotspots' ? 'active fw-bold' : ''}`}
                onClick={() => setActiveTab('hotspots')}
              >
                Hotspots & Issues ({data.issues?.summary?.critical + data.issues?.summary?.high} High/Crit)
              </button>
            </li>
            <li className="nav-item">
              <button
                className={`nav-link ${activeTab === 'recommendations' ? 'active fw-bold' : ''}`}
                onClick={() => setActiveTab('recommendations')}
              >
                Actionable Recommendations ({data.recommendations?.total_recommendations})
              </button>
            </li>
          </ul>

          {/* TAB 1: Overview */}
          {activeTab === 'overview' && (
            <>
              {/* 4 Core Sub-Scores */}
              <div className="row g-3 mb-4">
                <div className="col-md-3">
                  <div className="card shadow-sm text-center p-3 border-0 bg-white">
                    <small className="text-muted">Code Quality Score</small>
                    <h2 className="fw-bold my-1 text-dark">{data.scores.code_quality_score}</h2>
                    <small className="text-success">McCabe Bands (0-100)</small>
                  </div>
                </div>
                <div className="col-md-3">
                  <div className="card shadow-sm text-center p-3 border-0 bg-white">
                    <small className="text-muted">Maintainability Score</small>
                    <h2 className="fw-bold my-1 text-dark">{data.scores.maintainability_score}</h2>
                    <small className="text-info">Radon MI Index</small>
                  </div>
                </div>
                <div className="col-md-3">
                  <div className="card shadow-sm text-center p-3 border-0 bg-white">
                    <small className="text-muted">Development Activity</small>
                    <h2 className="fw-bold my-1 text-dark">{data.scores.development_score}</h2>
                    <small className="text-primary">{data.aggregates.contributors} Contributors</small>
                  </div>
                </div>
                <div className="col-md-3">
                  <div className="card shadow-sm text-center p-3 border-0 bg-white">
                    <small className="text-muted">Change Risk Score</small>
                    <h2 className="fw-bold my-1 text-dark">{data.scores.change_risk_score}</h2>
                    <small className="text-secondary">{data.aggregates.total_churn?.toLocaleString()} Churn lines</small>
                  </div>
                </div>
              </div>

              {/* Metrics & Quick Wins */}
              <div className="row g-4 mb-4">
                <div className="col-md-6">
                  <div className="card shadow-sm p-3 h-100 border-0 bg-white">
                    <h5 className="fw-bold mb-3">Repository Metrics Snapshot</h5>
                    <table className="table table-sm table-borderless small mb-0">
                      <tbody>
                        <tr><td><strong>Total LOC:</strong></td><td>{data.aggregates.total_loc?.toLocaleString()} lines</td></tr>
                        <tr><td><strong>Python Files:</strong></td><td>{data.aggregates.file_count} files</td></tr>
                        <tr><td><strong>Avg Cyclomatic Complexity:</strong></td><td>{data.aggregates.avg_cc}</td></tr>
                        <tr><td><strong>Documentation Coverage:</strong></td><td>{data.aggregates.documentation_coverage}%</td></tr>
                        <tr><td><strong>Total Commits:</strong></td><td>{data.aggregates.commit_count} ({data.aggregates.commit_freq} / week)</td></tr>
                        <tr><td><strong>Top 3 Churn Concentration:</strong></td><td>{(data.aggregates.churn_concentration * 100).toFixed(1)}%</td></tr>
                      </tbody>
                    </table>
                  </div>
                </div>
                <div className="col-md-6">
                  <div className="card shadow-sm p-3 h-100 border-0 bg-white">
                    <h5 className="fw-bold mb-3">⚡ Quick Wins</h5>
                    <ul className="list-group list-group-flush small">
                      {data.recommendations?.quick_wins?.map((win, i) => (
                        <li key={i} className="list-group-item px-0">
                          <span className="badge bg-primary me-2">{i + 1}</span> {win}
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              </div>
            </>
          )}

          {/* TAB 2: ML Explainability */}
          {activeTab === 'explainability' && (
            <div className="row g-4 mb-4">
              <div className="col-md-7">
                <div className="card shadow-sm p-3 border-0 bg-white h-100">
                  <h5 className="fw-bold mb-2">Corpus Feature Importances</h5>
                  <small className="text-muted mb-3 d-block">
                    Trained Random Forest relative feature weights (Module 7)
                  </small>
                  <div style={{ height: 320 }}>
                    <Bar data={featureChartData} options={featureChartOptions} />
                  </div>
                </div>
              </div>
              <div className="col-md-5">
                <div className="card shadow-sm p-3 border-0 bg-white h-100">
                  <h5 className="fw-bold mb-2">ML Prediction Probabilities</h5>
                  <small className="text-muted mb-3 d-block">Confidence distribution across the 3 health classes</small>
                  {Object.entries(data.ml_prediction?.confidence || {}).map(([label, prob]) => (
                    <div key={label} className="mb-3">
                      <div className="d-flex justify-content-between small fw-bold mb-1">
                        <span>{label}</span>
                        <span>{(prob * 100).toFixed(1)}%</span>
                      </div>
                      <div className="progress" style={{ height: 10 }}>
                        <div
                          className={`progress-bar ${label === 'Healthy' ? 'bg-success' : label === 'Stable' ? 'bg-primary' : 'bg-warning'}`}
                          style={{ width: `${prob * 100}%` }}
                        />
                      </div>
                    </div>
                  ))}
                  <div className="alert alert-light border small mt-4 mb-0">
                    <strong>Model Type:</strong> RandomForestClassifier (SMOTE-Balanced, 200 Estimators)
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* TAB 3: Hotspots & Issues */}
          {activeTab === 'hotspots' && (
            <>
              <div className="card shadow-sm p-3 mb-4 border-0 bg-white">
                <h5 className="fw-bold mb-3">Defect Hotspots (High Churn × High Complexity)</h5>
                <div className="table-responsive">
                  <table className="table table-hover align-middle small mb-0">
                    <thead className="table-light">
                      <tr>
                        <th>Rank</th>
                        <th>File Path</th>
                        <th>Churn (Lines)</th>
                        <th>Avg CC</th>
                        <th>Max CC</th>
                        <th>Hotspot Score</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.issues.hotspots.map((h, i) => (
                        <tr key={i}>
                          <td><span className="badge bg-secondary">{i + 1}</span></td>
                          <td><code>{h.filepath}</code></td>
                          <td>{h.churn}</td>
                          <td>{h.avg_cc}</td>
                          <td><span className={`badge ${h.max_cc > 20 ? 'bg-danger' : 'bg-warning text-dark'}`}>{h.max_cc}</span></td>
                          <td><strong>{h.hotspot_score}</strong></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Security Alerts */}
              {data.issues.security_issues?.length > 0 && (
                <div className="card shadow-sm p-3 mb-4 border-0 bg-white">
                  <h5 className="fw-bold text-danger mb-3">⚠️ Detected Security Anti-Patterns</h5>
                  <div className="list-group">
                    {data.issues.security_issues.map((sec, i) => (
                      <div key={i} className="list-group-item list-group-item-danger mb-2 rounded">
                        <div className="fw-bold">{sec.title} ({sec.rule_id})</div>
                        <small>File: <code>{sec.filepath}:{sec.lineno}</code></small>
                        <p className="small mb-0 mt-1">{sec.description}</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}

          {/* TAB 4: Recommendations */}
          {activeTab === 'recommendations' && (
            <div className="card shadow-sm p-4 border-0 bg-white mb-4">
              <h5 className="fw-bold mb-3">Prioritized Action Items</h5>
              <div className="row g-3">
                {data.recommendations?.recommendations?.map((r, i) => (
                  <div className="col-12" key={i}>
                    <div className="p-3 border rounded">
                      <div className="d-flex justify-content-between mb-2">
                        <h6 className="fw-bold mb-0 text-dark">{r.title}</h6>
                        <span className={`badge ${r.priority === 'CRITICAL' ? 'bg-danger' : r.priority === 'HIGH' ? 'bg-warning text-dark' : 'bg-secondary'}`}>
                          {r.priority}
                        </span>
                      </div>
                      <p className="small mb-1 text-dark"><strong>Action:</strong> {r.action}</p>
                      <p className="small mb-0 text-muted"><strong>Rationale:</strong> {r.rationale}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
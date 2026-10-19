// Astryx Navbar Component
import { html } from '/static/js/html.js';

export function Navbar({ activeWorkerCount, isClusterBusy }) {
  return html`
    <header className="astryx-header">
      <div className="brand-wrapper">
        <div className="brand-icon">🛰</div>
        <div className="brand-name">
          GeoLLM
          <span className="pill-badge dark-meta">Astryx Sandbox</span>
        </div>
      </div>

      <div className="header-telemetry">
        <div className="telemetry-node">
          <span className="status-indicator ${isClusterBusy ? 'busy' : ''}"></span>
          <span>${isClusterBusy ? `${activeWorkerCount} of 3 Workers Running` : 'Cluster Ready: 0/3 Workers Active'}</span>
        </div>
        <div className="telemetry-node">
          <span style=${{ color: '#475569' }}>|</span>
        </div>
        <div className="telemetry-node">
          <span>Sandbox Core:</span>
          <strong style=${{ color: '#f8fafc', fontFamily: 'var(--font-mono)' }}>Docker + Pi RPC</strong>
        </div>
      </div>
    </header>
  `;
}

// Astryx Navbar Component (Deep Technical Dark)
import { html } from '/static/js/html.js';
import { IconSatellite } from '/static/js/icons.js';

export function Navbar({ activeWorkerCount, isClusterBusy }) {
  return html`
    <header className="astryx-header">
      <div className="brand-wrapper">
        <div className="brand-icon" aria-hidden="true">
          <${IconSatellite} size=${17} />
        </div>
        <div className="brand-title-group">
          <span className="brand-name">GeoLLM</span>
          <span className="brand-subtitle">Autonomous Geospatial Workbench</span>
        </div>
        <span className="pill-badge brand-badge">3 Sandboxes</span>
      </div>

      <div className="header-telemetry">
        <div className="telemetry-node">
          <span
            className="status-indicator ${isClusterBusy ? 'busy' : ''}"
            aria-label=${isClusterBusy ? 'Cluster busy' : 'Cluster idle'}
          ></span>
          <span className="telemetry-label">
            ${isClusterBusy
              ? `${activeWorkerCount} of 3 Sandboxes Active`
              : 'Cluster Ready · 0/3 Active'}
          </span>
        </div>
        <div className="telemetry-separator">/</div>
        <div className="telemetry-node">
          <span className="telemetry-dim">Execution Engine:</span>
          <span className="telemetry-val">Isolated Docker Containers</span>
        </div>
      </div>
    </header>
  `;
}

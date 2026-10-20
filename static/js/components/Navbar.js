// GeoLLM Navbar Component (Styled from design/reference.html)
import { html } from '/static/js/html.js';

export function Navbar({ activeWorkerCount = 0, isClusterBusy = false }) {
  return html`
    <header className="top">
      <div className="brand">
        <div className="logo" aria-hidden="true">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2">
            <path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z" />
            <path d="M12 12l8-4.5M12 12v9M12 12L4 7.5" />
          </svg>
        </div>
        <span>GeoLLM</span>
        <span className="tag">Workspace</span>
      </div>

      <div className="sp"></div>

      <div className="stat">
        <span className="dot ${isClusterBusy ? 'busy' : ''}"></span>
        <span>${isClusterBusy ? `${activeWorkerCount} of 3 workers active` : 'Cluster ready · 0 of 3 workers active'}</span>
      </div>

      <button className="btn s" type="button" onClick=${() => window.location.reload()}>
        Refresh
      </button>
    </header>
  `;
}

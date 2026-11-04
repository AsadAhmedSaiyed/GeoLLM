import { html, React } from '../html.js';

/**
 * ValidationViewer renders the live agentic vision validation events.
 * It handles the grid overlay, tile highlights, thumbnails, and final summary.
 */
export const ValidationViewer = ({ activity }) => {
  const { type } = activity;

  if (type === 'vision_input_gate') {
    const isDone = activity.state === 'done';
    const isBad = activity.verdict === 'insufficient_data';

    return html`
      <div className="tool-card ${isBad ? 'bad' : isDone ? 'ok' : 'run'}" style=${{ padding: '8px' }}>
        <div style=${{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12px', fontWeight: 'bold', marginBottom: '4px' }}>
          <span>🛡️ Input Quality Gate</span>
          <span style=${{ marginLeft: 'auto', fontSize: '10px' }}>${activity.verdict || 'Checking...'}</span>
        </div>
        ${activity.files && activity.files.map(f => html`
          <div key=${f.name} style=${{ fontSize: '11px', color: '#4B5B54', borderTop: '1px solid #e5e7eb', paddingTop: '4px', marginTop: '4px' }}>
            <div style=${{ display: 'flex', justifyContent: 'space-between' }}>
              <span className="mono" style=${{ fontWeight: 600 }}>${f.name.split('/').pop()}</span>
              <span style=${{ color: f.is_usable ? '#059669' : '#DC2626' }}>${f.is_usable ? 'PASS' : 'FAIL'}</span>
            </div>
            <div style=${{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', marginTop: '2px' }}>
              <span>Nodata: ${f.nodata_pct}%</span>
              <span>Cloud: ${f.cloud_pct}%</span>
            </div>
          </div>
        `)}
        ${activity.reason && html`<div style=${{ fontSize: '10px', color: '#991B1B', marginTop: '4px', fontStyle: 'italic' }}>${activity.reason}</div>`}
      </div>
    `;
  }

  if (type === 'vision_grid') {
    return html`
      <div className="tool-card ok" style=${{ padding: '6px 8px' }}>
        <div className="mono" style=${{ fontSize: '11px', fontWeight: 600 }}>
          🗺️ Grid Defined: ${activity.rows}x${activity.cols} (${activity.tiles ? activity.tiles.length : 0} tiles)
        </div>
        <div style=${{ fontSize: '10px', color: '#6B7280' }}>
          Step ${activity.steps_used} / ${activity.budget}
        </div>
      </div>
    `;
  }

  if (type === 'vision_inspecting_tile') {
    return html`
      <div className="tool-card run" style=${{ padding: '6px 8px', borderLeft: '3px solid #3B82F6' }}>
        <div style=${{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span className="mono" style=${{ fontSize: '11px', fontWeight: 600 }}>🔍 Inspecting: ${activity.tile_id}</span>
          <span style=${{ fontSize: '10px', color: '#6B7280', marginLeft: 'auto' }}>Zoom x${activity.zoom_level || 1}</span>
        </div>
        ${activity.thumb_url && html`
          <img
            src=${activity.thumb_url}
            style=${{ width: '100%', height: 'auto', marginTop: '6px', borderRadius: '4px', border: '1px solid #ddd' }}
            alt="Tile inspection"
          />
        `}
      </div>
    `;
  }

  if (type === 'vision_tile_verdict') {
    const color = activity.color || '#6B7280';
    return html`
      <div className="tool-card" style=${{ padding: '6px 8px', borderLeft: `4px solid ${color}` }}>
        <div style=${{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '11px' }}>
          <span className="mono" style=${{ fontWeight: 600 }}>⚖️ Verdict: ${activity.tile_id}</span>
          <span className="mono" style=${{ marginLeft: 'auto', fontWeight: 700, color: color }}>${activity.verdict.toUpperCase()}</span>
        </div>
        <div style=${{ fontSize: '10.5px', color: '#4B5B54', marginTop: '4px' }}>
          ${activity.rationale}
        </div>
        ${activity.thumb_url && html`
          <div style=${{ marginTop: '6px', fontSize: '10px', color: '#6B7280' }}>
             Confidence: ${Math.round(activity.confidence * 100)}%
          </div>
        `}
      </div>
    `;
  }

  if (type === 'vision_progress') {
    const pct = Math.round((activity.steps_used / activity.budget) * 100);
    return html`
      <div style=${{ padding: '4px 8px', fontSize: '10px', color: '#6B7280', display: 'flex', alignItems: 'center', gap: '8px' }}>
        <div style=${{ flex: 1, height: '4px', background: '#e5e7eb', borderRadius: '2px', overflow: 'hidden' }}>
          <div style=${{ width: `${pct}%`, height: '100%', background: '#10b981' }}></div>
        </div>
        <span className="mono">Step ${activity.steps_used}/${activity.budget}</span>
      </div>
    `;
  }

  if (type === 'vision_stopped') {
    const isBad = activity.reason !== 'valid';
    return html`
      <div className="tool-card ${isBad ? 'bad' : 'ok'}" style=${{ padding: '10px', border: isBad ? '1px solid #FCA5A5' : '1px solid #6EE7B7' }}>
        <div style=${{ fontWeight: 'bold', fontSize: '13px', color: isBad ? '#991B1B' : '#065F46' }}>
          🛑 Vision Loop Stopped
        </div>
        <div style=${{ fontSize: '11px', marginTop: '4px' }}>
          Reason: <span className="mono" style=${{ fontWeight: 600 }}>${activity.reason}</span>
        </div>
        ${activity.detail && html`<div style=${{ fontSize: '10.5px', color: '#4B5B54', marginTop: '4px', fontStyle: 'italic' }}>${activity.detail}</div>`}
      </div>
    `;
  }

  if (type === 'vision_summary') {
    const color = activity.final_verdict === 'valid' ? '#059669' : activity.final_verdict === 'not_valid' ? '#DC2626' : '#D97706';
    return html`
      <div className="task-findings-card" style=${{ marginTop: '10px', borderLeft: `4px solid ${color}` }}>
        <div style=${{ fontWeight: 'bold', fontSize: '14px', marginBottom: '8px' }}>
          📊 Final Vision Summary
        </div>
        <div style=${{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px', marginBottom: '10px' }}>
          <div className="tool-card" style=${{ padding: '8px', textAlign: 'center' }}>
            <div style=${{ fontSize: '10px', color: '#6B7280' }}>Verdict</div>
            <div style=${{ fontSize: '14px', fontWeight: 800, color: color }}>${activity.final_verdict.toUpperCase()}</div>
          </div>
          <div className="tool-card" style=${{ padding: '8px', textAlign: 'center' }}>
            <div style=${{ fontSize: '10px', color: '#6B7280' }}>Area Verified</div>
            <div style=${{ fontSize: '14px', fontWeight: 800 }}>${activity.verified_area_pct}%</div>
          </div>
        </div>
        <div className="mono" style=${{ fontSize: '11px', marginBottom: '8px' }}>
          ${activity.summary}
        </div>
        ${activity.flagged_regions && activity.flagged_regions.length > 0 && html`
          <div style=${{ borderTop: '1px solid #e5e7eb', paddingTop: '8px' }}>
            <div style=${{ fontSize: '11px', fontWeight: 'bold', marginBottom: '4px' }}>🚩 Flagged Issues:</div>
            ${activity.flagged_regions.map(f => html`
              <div key=${f.tile_id} style=${{ fontSize: '10.5px', marginBottom: '4px', padding: '4px', background: '#FEF2F2', borderRadius: '4px' }}>
                <span style=${{ fontWeight: 600 }}>${f.tile_id}:</span> ${f.rationale}
              </div>
            `)}
          </div>
        `}
      </div>
    `;
  }

  if (type === 'vision_consensus_done') {
    return html`
      <div className="tool-card ok" style=${{ padding: '6px 8px', background: '#F0F9FF' }}>
        <div className="mono" style=${{ fontSize: '11px', fontWeight: 600 }}>
          🤝 Consensus Re-verification Complete
        </div>
        <div style=${{ fontSize: '10px', color: '#6B7280' }}>
          ${activity.re_verified} tile(s) reviewed for agreement.
        </div>
      </div>
    `;
  }

  return null;
};

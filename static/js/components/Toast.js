// Astryx In-App Non-Blocking Toast Notification System
import { html } from '/static/js/html.js';
import { IconCheck, IconAlertTriangle, IconX } from '/static/js/icons.js';

export function ToastContainer({ toasts = [], onDismiss }) {
  if (!toasts || toasts.length === 0) return null;

  return html`
    <div className="toast-container" role="region" aria-label="Notifications" aria-live="polite">
      ${toasts.map(toast => {
        const isError = toast.type === 'error';
        const isWarning = toast.type === 'warning';
        const isSuccess = toast.type === 'success';

        return html`
          <div
            key=${toast.id}
            className="toast toast-${toast.type || 'info'}"
            role="alert"
          >
            <div className="toast-icon">
              ${isSuccess ? html`<${IconCheck} size=${16} />` : null}
              ${isWarning || isError ? html`<${IconAlertTriangle} size=${16} />` : null}
              ${!isSuccess && !isWarning && !isError ? html`<span className="toast-bullet">●</span>` : null}
            </div>

            <div className="toast-content">
              ${toast.title ? html`<div className="toast-title">${toast.title}</div>` : null}
              <div className="toast-message">${toast.message}</div>
            </div>

            <button
              className="toast-close-btn"
              onClick=${() => onDismiss(toast.id)}
              aria-label="Dismiss notification"
              type="button"
            >
              <${IconX} size=${13} />
            </button>
          </div>
        `;
      })}
    </div>
  `;
}

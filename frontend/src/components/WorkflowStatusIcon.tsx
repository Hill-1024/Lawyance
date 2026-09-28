import React from "react";

/** Original Lawver workflow animation, shared by legacy and the workbench. */
export const WorkflowStatusIcon: React.FC<{ status: 'running' | 'done' }> = ({ status }) => (
  <svg
    className={`lawver-status-glyph ${status === 'running' ? 'is-running' : 'is-done'}`}
    viewBox="0 0 16 16"
    aria-hidden="true"
  >
    {status === 'running' ? (
      <>
        <circle className="status-track" cx="8" cy="8" r="7" />
        <circle className="status-sweep" cx="8" cy="8" r="7" pathLength="50" strokeDashoffset="0" />
      </>
    ) : (
      <>
        <circle className="status-ring" cx="8" cy="8" r="7" pathLength="50" />
        <path className="status-check" d="M5 8.4 L7.2 10.6 L11 6.4" />
      </>
    )}
  </svg>
);


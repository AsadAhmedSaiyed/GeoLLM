import React from "https://esm.sh/react@18.2.0";
function TaskTabs({
  workspaces = [],
  activeWorkspaceId,
  onSelectWorkspace,
  onCreateWorkspace,
  tasks = {},
  isConsoleOpen,
  onToggleConsole,
  supervisorOpen,
  onToggleSupervisor,
  onOpenStacSearch
}) {
  const getStatusBadge = (t) => {
    if (!t) return { label: "Idle", color: "#64748B", bg: "rgba(100, 116, 139, 0.15)" };
    if (t.status === "running") {
      return {
        label: t.step ? "Running" : "Active",
        color: "#F59E0B",
        bg: "rgba(245, 158, 11, 0.15)",
        pulse: true
      };
    }
    if (t.status === "pending_approval") {
      return { label: "Review Plan", color: "#38BDF8", bg: "rgba(56, 189, 248, 0.15)", pulse: true };
    }
    if (t.status === "pending_stac_approval") {
      return { label: "STAC Review", color: "#38BDF8", bg: "rgba(56, 189, 248, 0.15)", pulse: true };
    }
    if (t.status === "done") {
      return { label: "Done", color: "#10B981", bg: "rgba(16, 185, 129, 0.15)" };
    }
    if (t.status === "failed") {
      return { label: "Failed", color: "#EF4444", bg: "rgba(239, 68, 68, 0.15)" };
    }
    return { label: "Idle", color: "#64748B", bg: "rgba(100, 116, 139, 0.15)" };
  };
  return /* @__PURE__ */ React.createElement(
    "header",
    {
      className: "task-tabs-header",
      style: {
        background: "#090D14",
        borderBottom: "1px solid #1E293B",
        padding: "0 16px",
        height: "48px",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        zIndex: 30
      }
    },
    /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", width: "100%", gap: "14px" } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: "8px" } }, /* @__PURE__ */ React.createElement("div", { style: { width: "8px", height: "8px", borderRadius: "50%", backgroundColor: "#14B8A6", boxShadow: "0 0 0 2px rgba(20, 184, 166, 0.35)" } }), /* @__PURE__ */ React.createElement("span", { style: { fontWeight: 700, fontSize: "15px", color: "#F1F5F9", letterSpacing: "-0.02em" } }, "GeoLLM"), /* @__PURE__ */ React.createElement("span", { style: { fontSize: "10px", textTransform: "uppercase", letterSpacing: "0.05em", color: "#14B8A6", background: "rgba(20, 184, 166, 0.1)", border: "1px solid rgba(20, 184, 166, 0.25)", padding: "1px 6px", borderRadius: "4px" } }, "Autonomous")), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: "6px" } }, /* @__PURE__ */ React.createElement(
      "span",
      {
        className: "mono",
        style: {
          fontSize: "11px",
          color: workspaces.length === 3 ? "#F59E0B" : "#14B8A6",
          background: "#111827",
          border: "1px solid #1E293B",
          padding: "2px 8px",
          borderRadius: "12px"
        }
      },
      "Containers: ",
      workspaces.length,
      " / 3 Allocated"
    )), /* @__PURE__ */ React.createElement("nav", { style: { display: "flex", alignItems: "center", gap: "6px", marginLeft: "8px", overflowX: "auto", flex: 1 } }, workspaces.map((ws) => {
      const task = tasks[ws.containerId];
      const badge = getStatusBadge(task);
      const isSelected = activeWorkspaceId === ws.id;
      const containerNum = ws.containerId ? ws.containerId.replace("task_", "") : "1";
      return /* @__PURE__ */ React.createElement(
        "button",
        {
          key: ws.id,
          type: "button",
          onClick: () => onSelectWorkspace(ws.id),
          style: {
            background: isSelected ? "#1E293B" : "transparent",
            border: isSelected ? "1px solid #14B8A6" : "1px solid #1E293B",
            borderRadius: "6px",
            padding: "4px 10px",
            display: "flex",
            alignItems: "center",
            gap: "6px",
            cursor: "pointer",
            color: isSelected ? "#F1F5F9" : "#94A3B8"
          },
          title: `Workspace: ${ws.name} (Container #${containerNum})`
        },
        /* @__PURE__ */ React.createElement("span", { className: "mono", style: { fontSize: "10px", color: "#14B8A6", fontWeight: 600 } }, "#", containerNum),
        /* @__PURE__ */ React.createElement("span", { style: { fontSize: "12px", fontWeight: 500, maxWidth: "140px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, ws.name),
        /* @__PURE__ */ React.createElement(
          "span",
          {
            className: "mono",
            style: {
              color: badge.color,
              backgroundColor: badge.bg,
              fontSize: "9.5px",
              padding: "1px 5px",
              borderRadius: "4px",
              fontWeight: 600
            }
          },
          badge.label
        )
      );
    })), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: "8px" } }, /* @__PURE__ */ React.createElement(
      "button",
      {
        type: "button",
        onClick: onToggleConsole,
        style: {
          background: isConsoleOpen ? "rgba(20, 184, 166, 0.2)" : "#111827",
          border: isConsoleOpen ? "1px solid #14B8A6" : "1px solid #1E293B",
          color: isConsoleOpen ? "#14B8A6" : "#E2E8F0",
          padding: "5px 12px",
          borderRadius: "6px",
          fontSize: "11.5px",
          fontWeight: 600,
          cursor: "pointer",
          display: "flex",
          alignItems: "center",
          gap: "6px"
        },
        title: "Toggle Movable Workspace & Agent Chat Panel"
      },
      /* @__PURE__ */ React.createElement("span", null, "\u{1F4AC}"),
      /* @__PURE__ */ React.createElement("span", null, "Workspace Console")
    ), /* @__PURE__ */ React.createElement(
      "button",
      {
        type: "button",
        style: {
          background: "#111827",
          border: "1px solid #1E293B",
          color: "#38BDF8",
          padding: "5px 10px",
          borderRadius: "6px",
          fontSize: "11.5px",
          fontWeight: 500,
          cursor: "pointer",
          display: "flex",
          alignItems: "center",
          gap: "4px"
        },
        onClick: onOpenStacSearch,
        title: "Search & Retrieve Satellite Imagery via Microsoft Planetary Computer"
      },
      /* @__PURE__ */ React.createElement("span", null, "\u{1F6F0}\uFE0F"),
      /* @__PURE__ */ React.createElement("span", null, "Planetary Computer")
    ), /* @__PURE__ */ React.createElement(
      "button",
      {
        type: "button",
        style: {
          background: supervisorOpen ? "rgba(20, 184, 166, 0.15)" : "#111827",
          border: supervisorOpen ? "1px solid #14B8A6" : "1px solid #1E293B",
          color: supervisorOpen ? "#14B8A6" : "#E2E8F0",
          padding: "5px 10px",
          borderRadius: "6px",
          fontSize: "11.5px",
          fontWeight: 500,
          cursor: "pointer",
          display: "flex",
          alignItems: "center",
          gap: "6px"
        },
        onClick: onToggleSupervisor,
        title: "Toggle Autonomous Supervisor Drawer"
      },
      /* @__PURE__ */ React.createElement("span", { style: { width: "6px", height: "6px", borderRadius: "50%", backgroundColor: "#14B8A6" } }),
      /* @__PURE__ */ React.createElement("span", null, "Supervisor Agent")
    )))
  );
}
export {
  TaskTabs
};

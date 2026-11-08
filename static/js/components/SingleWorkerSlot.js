import React, { useState, useRef, useEffect } from "https://esm.sh/react@18.2.0";
import { MarkdownView } from "./MarkdownView.js?v=20261107_v4";
import { TimeSeriesPanel } from "./TimeSeriesPanel.js?v=20261107_v4";
import { Terrain3DViewer } from "./Terrain3DViewer.js?v=20261107_v4";
import { ValidationViewer } from "./ValidationViewer.js?v=20261107_v4";
const getBasename = (p) => (p || "").replace(/\\/g, "/").split("/").pop();
function SingleWorkerSlot({
  taskId,
  task = {},
  onApprovePlan,
  onRevisePlan,
  onCancelTask,
  onPreviewFile,
  onSwitchToGlobe,
  onNotify
}) {
  const [revisionFeedback, setRevisionFeedback] = useState("");
  const [showLogs, setShowLogs] = useState(true);
  const [timelineFrame, setTimelineFrame] = useState(null);
  const [showTerrain3D, setShowTerrain3D] = useState(false);
  const activityRef = useRef(null);
  const isUserScrolledUp = useRef(false);
  const handleScroll = (e) => {
    const el = e.currentTarget;
    if (!el) return;
    const distanceToBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    isUserScrolledUp.current = distanceToBottom > 60;
  };
  useEffect(() => {
    if (activityRef.current && showLogs && !isUserScrolledUp.current) {
      activityRef.current.scrollTop = activityRef.current.scrollHeight;
    }
  }, [task.activities, showLogs]);
  const taskNum = taskId ? taskId.replace("task_", "") : "1";
  const formatSeconds = (t) => {
    if (!t || t.status === "idle") return "Not started";
    if (!t.elapsed) return "00:00";
    const total = Math.floor(t.elapsed);
    const m = Math.floor(total / 60);
    const s = total % 60;
    return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
  };
  const statusLabel = task.status === "running" ? task.step || "Running\u2026" : task.status === "pending_stac_approval" ? "STAC Satellite Preview Pending Review" : task.status === "pending_approval" ? "Plan Pending Approval" : task.status === "done" ? "Completed" : task.status === "failed" ? task.error || "Failed" : "Idle";
  const inputGateActivity = (task.activities || []).slice().reverse().find((a) => a.type === "vision_input_gate");
  const artifacts = task.artifacts || [];
  const gifArt = artifacts.find((a) => {
    const name = typeof a === "string" ? a : a.name || "";
    return name.toLowerCase().endsWith(".gif");
  });
  const hasTimeline = artifacts.some((a) => {
    const name = typeof a === "string" ? a : a.name || "";
    return name.toLowerCase().includes("timeline.json");
  }) || !!gifArt;
  const terrain3dArt = artifacts.find((a) => {
    const name = typeof a === "string" ? a : a.name || "";
    return name.toLowerCase().includes("terrain_3d.json");
  });
  const isLidar = artifacts.some((a) => {
    const name = typeof a === "string" ? a : a.name || "";
    return ["lidar", "chm", "las", "laz", "canopy_height"].some((k) => name.toLowerCase().includes(k));
  }) || (task.files || []).some((f) => ["lidar", "chm", "las", "laz", "autzen"].some((k) => (f || "").toLowerCase().includes(k))) || (task.prompt || task.question || "").toLowerCase().includes("lidar") || (task.prompt || task.question || "").toLowerCase().includes("canopy height") || (task.prompt || task.question || "").toLowerCase().includes("point cloud");
  const isElevation = artifacts.some((a) => {
    const name = typeof a === "string" ? a : a.name || "";
    return ["dem", "elevation", "dsm", "dtm", "cop-dem", "srtm", "nasadem", "topography", "terrain"].some((k) => name.toLowerCase().includes(k));
  }) || (task.files || []).some((f) => ["dem", "elevation", "dsm", "dtm", "cop-dem", "srtm", "nasadem"].some((k) => (f || "").toLowerCase().includes(k))) || (task.prompt || task.question || "").toLowerCase().includes("elevation") || (task.prompt || task.question || "").toLowerCase().includes("terrain") || (task.prompt || task.question || "").toLowerCase().includes("topography") || (task.prompt || task.question || "").toLowerCase().includes("dem") || (task.prompt || task.question || "").toLowerCase().includes("slope");
  const canShow3D = !!terrain3dArt || isLidar || isElevation;
  const profileSvgArt = artifacts.find((a) => {
    const name = typeof a === "string" ? a : a.name || "";
    return name.toLowerCase().includes("profile.svg") || name.toLowerCase().includes("profile") && name.toLowerCase().endsWith(".svg");
  });
  const isDone = task.status === "done";
  const isFailed = task.status === "failed";
  const finalAnswer = (() => {
    if (!isDone && !isFailed) return null;
    const textParts = (task.activities || []).filter((a) => a.type === "text" && a.text && a.text.trim()).map((a) => a.text);
    return textParts.length > 0 ? textParts.join("") : null;
  })();
  const relevantActivities = (task.activities || []).filter((act) => {
    if (act.type === "vision_input_gate") return false;
    return true;
  });
  return /* @__PURE__ */ React.createElement("div", { className: "single-task-workbench", style: { display: "flex", flexDirection: "column", gap: "12px" } }, /* @__PURE__ */ React.createElement("div", { className: "task-header-card", style: { background: "#111827", border: "1px solid #1E293B", borderRadius: "8px", padding: "12px 14px" } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: "10px" } }, /* @__PURE__ */ React.createElement("span", { className: "task-pill mono", style: { background: "#0F766E", color: "#FFFFFF", padding: "2px 8px", borderRadius: "4px", fontSize: "11px", fontWeight: "bold" } }, "#", taskNum), /* @__PURE__ */ React.createElement("div", { style: { flex: 1, minWidth: 0 } }, /* @__PURE__ */ React.createElement("div", { style: { fontWeight: 600, fontSize: "13.5px", color: "#F1F5F9", wordBreak: "break-word" } }, task.question ? task.question : `Sandbox Slot #${taskNum} (Idle)`), /* @__PURE__ */ React.createElement("div", { className: "mono", style: { fontSize: "11px", color: "#94A3B8", marginTop: "3px" } }, "Elapsed: ", formatSeconds(task), " \u2022 Status:", " ", /* @__PURE__ */ React.createElement("span", { style: { fontWeight: 600, color: task.status === "running" ? "#38BDF8" : task.status === "done" ? "#10B981" : task.status === "failed" ? "#F87171" : "#E2E8F0" } }, statusLabel))), (task.status === "running" || task.status === "pending_approval" || task.status === "pending_stac_approval") && /* @__PURE__ */ React.createElement(
    "button",
    {
      type: "button",
      className: "btn danger",
      style: { fontSize: "11px", padding: "4px 10px", background: "rgba(239, 68, 68, 0.2)", border: "1px solid #EF4444", color: "#FCA5A5", borderRadius: "4px", cursor: "pointer", flexShrink: 0 },
      onClick: () => onCancelTask && onCancelTask(taskId)
    },
    "Abort Task"
  ))), inputGateActivity && /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(ValidationViewer, { activity: inputGateActivity })), task.status === "pending_stac_approval" && task.stacPreview && /* @__PURE__ */ React.createElement("div", { className: "plan-approval-banner", style: { borderLeft: "4px solid #0284C7", background: "#0F172A", border: "1px solid #1E293B", borderRadius: "8px", padding: "14px" } }, /* @__PURE__ */ React.createElement("div", { className: "plan-header", style: { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "10px", flexWrap: "wrap", gap: "6px" } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: "13.5px", fontWeight: 700, color: "#38BDF8" } }, "\u{1F6F0}\uFE0F Satellite Scene Previews \u2014 Review Before Native-Resolution Staging"), /* @__PURE__ */ React.createElement("span", { className: "mono", style: { fontSize: "11px", color: "#38BDF8", background: "rgba(56, 189, 248, 0.15)", padding: "2px 8px", borderRadius: "10px" } }, "100% Native Resolution Preserved")), task.stacPreview.explanation && /* @__PURE__ */ React.createElement("div", { style: { fontSize: "12.5px", color: "#E2E8F0", marginBottom: "10px", lineHeight: 1.5 } }, /* @__PURE__ */ React.createElement(MarkdownView, { content: task.stacPreview.explanation })), /* @__PURE__ */ React.createElement("div", { className: "mono", style: { fontSize: "11px", color: "#94A3B8", background: "#1E293B", padding: "8px 10px", borderRadius: "6px", marginBottom: "12px", display: "flex", flexWrap: "wrap", gap: "14px" } }, /* @__PURE__ */ React.createElement("span", null, /* @__PURE__ */ React.createElement("strong", null, "Location:"), " ", task.stacPreview.location_name || "Custom AOI"), task.stacPreview.bbox && /* @__PURE__ */ React.createElement("span", null, /* @__PURE__ */ React.createElement("strong", null, "BBox:"), " [", task.stacPreview.bbox.map((n) => Number(n).toFixed(4)).join(", "), "]"), task.stacPreview.native_grid_estimate && /* @__PURE__ */ React.createElement("span", null, /* @__PURE__ */ React.createElement("strong", null, "Native Grid:"), " ~", task.stacPreview.native_grid_estimate.estimated_width_px, "\xD7", task.stacPreview.native_grid_estimate.estimated_height_px, " px (", task.stacPreview.native_grid_estimate.native_resolution_m, "m native res, ", task.stacPreview.native_grid_estimate.area_km2, " km\xB2)")), /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "10px", marginBottom: "14px" } }, (task.stacPreview.scenes || []).map((sc, idx) => /* @__PURE__ */ React.createElement("div", { key: sc.id || idx, style: { background: "#111827", border: "1px solid #1E293B", borderRadius: "6px", overflow: "hidden" } }, sc.thumbnail ? /* @__PURE__ */ React.createElement("div", { style: { background: "#090D14", textAlign: "center", height: "140px", display: "flex", alignItems: "center", justifyContent: "center", overflow: "hidden" } }, /* @__PURE__ */ React.createElement(
    "img",
    {
      src: sc.thumbnail,
      alt: sc.label || sc.id,
      style: { maxHeight: "140px", maxWidth: "100%", objectFit: "contain" }
    }
  )) : /* @__PURE__ */ React.createElement("div", { className: "mono", style: { height: "100px", background: "#090D14", color: "#64748B", display: "flex", alignItems: "center", justifyContent: "center", fontSize: "11px" } }, "No preview thumbnail"), /* @__PURE__ */ React.createElement("div", { style: { padding: "8px 10px", fontSize: "11px" } }, /* @__PURE__ */ React.createElement("div", { style: { fontWeight: 700, color: "#F1F5F9", marginBottom: "4px" } }, sc.label || `Scene ${idx + 1}`), /* @__PURE__ */ React.createElement("div", { className: "mono", style: { fontSize: "10px", color: "#94A3B8", lineHeight: 1.5 } }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("strong", null, "Collection:"), " ", sc.collection), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("strong", null, "Date:"), " ", (sc.datetime || "").slice(0, 10) || "N/A"), sc.cloud_cover !== null && sc.cloud_cover !== void 0 && /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("strong", null, "Cloud Cover:"), " ", sc.cloud_cover, "%"), sc.aoi_coverage_pct !== null && sc.aoi_coverage_pct !== void 0 && /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("strong", null, "AOI Coverage:"), " ", sc.aoi_coverage_pct, "%"), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("strong", null, "Bands:"), " ", (sc.assets || []).join(", "))))))), /* @__PURE__ */ React.createElement("div", { className: "plan-actions", style: { display: "flex", flexDirection: "column", gap: "8px" } }, /* @__PURE__ */ React.createElement(
    "button",
    {
      type: "button",
      className: "btn primary",
      style: { backgroundColor: "#0284C7", color: "#FFFFFF", padding: "8px 14px", borderRadius: "4px", border: "none", fontWeight: "bold", cursor: "pointer" },
      onClick: () => onApprovePlan && onApprovePlan(taskId)
    },
    "\u2713 Approve & Stage Native-Resolution Images"
  ), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: "8px", flex: 1 } }, /* @__PURE__ */ React.createElement(
    "input",
    {
      type: "text",
      className: "input mono",
      style: { flex: 1, fontSize: "11.5px", background: "#111827", border: "1px solid #1E293B", color: "#F1F5F9", padding: "6px 10px", borderRadius: "4px" },
      placeholder: "Or give feedback (e.g., 'cloudy, search July 2024 instead')\u2026",
      value: revisionFeedback,
      onChange: (e) => setRevisionFeedback(e.target.value)
    }
  ), /* @__PURE__ */ React.createElement(
    "button",
    {
      type: "button",
      className: "btn",
      style: { background: "#1E293B", color: "#E2E8F0", border: "1px solid #334155", borderRadius: "4px", padding: "6px 12px", cursor: "pointer" },
      onClick: () => {
        if (!revisionFeedback.trim()) {
          if (onNotify) onNotify("Please enter feedback for the satellite search.", "warning");
          return;
        }
        onRevisePlan && onRevisePlan(taskId, revisionFeedback.trim());
        setRevisionFeedback("");
      }
    },
    "Search Again"
  )))), task.status === "pending_approval" && /* @__PURE__ */ React.createElement("div", { className: "plan-approval-banner", style: { background: "#0F172A", border: "1px solid #1E293B", borderRadius: "8px", padding: "14px", borderLeft: "4px solid #14B8A6" } }, /* @__PURE__ */ React.createElement("div", { className: "plan-header", style: { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: "13.5px", fontWeight: 600, color: "#14B8A6" } }, "\u{1F4CB} Plan Proposed \u2014 User Review Required"), /* @__PURE__ */ React.createElement("span", { className: "mono", style: { fontSize: "10.5px", color: "#94A3B8" } }, "Autonomous container paused")), /* @__PURE__ */ React.createElement("div", { className: "plan-body", style: { color: "#E2E8F0", fontSize: "12px", marginBottom: "12px" } }, /* @__PURE__ */ React.createElement(MarkdownView, { content: task.plan || "No plan details provided." })), /* @__PURE__ */ React.createElement("div", { className: "plan-actions", style: { display: "flex", flexDirection: "column", gap: "8px" } }, /* @__PURE__ */ React.createElement(
    "button",
    {
      type: "button",
      className: "btn primary",
      style: { backgroundColor: "#0F766E", color: "#FFFFFF", padding: "8px 14px", borderRadius: "4px", border: "none", fontWeight: "bold", cursor: "pointer" },
      onClick: () => onApprovePlan && onApprovePlan(taskId)
    },
    "\u2713 Approve Plan & Execute Analysis"
  ), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: "8px", flex: 1 } }, /* @__PURE__ */ React.createElement(
    "input",
    {
      type: "text",
      className: "input mono",
      style: { flex: 1, fontSize: "11.5px", background: "#111827", border: "1px solid #1E293B", color: "#F1F5F9", padding: "6px 10px", borderRadius: "4px" },
      placeholder: "Request plan revisions (e.g., 'use threshold 0.25 and add confidence map')\u2026",
      value: revisionFeedback,
      onChange: (e) => setRevisionFeedback(e.target.value)
    }
  ), /* @__PURE__ */ React.createElement(
    "button",
    {
      type: "button",
      className: "btn",
      style: { background: "#1E293B", color: "#E2E8F0", border: "1px solid #334155", borderRadius: "4px", padding: "6px 12px", cursor: "pointer" },
      onClick: () => {
        if (!revisionFeedback.trim()) {
          if (onNotify) onNotify("Please enter revision feedback.", "warning");
          return;
        }
        onRevisePlan && onRevisePlan(taskId, revisionFeedback.trim());
        setRevisionFeedback("");
      }
    },
    "Send Revision"
  )))), (task.answer || finalAnswer) && /* @__PURE__ */ React.createElement("div", { className: "task-findings-card", style: { background: "#111827", border: "1px solid #1E293B", borderRadius: "8px", padding: "14px" } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: "8px", marginBottom: "10px" } }, /* @__PURE__ */ React.createElement("span", { style: { fontWeight: 700, fontSize: "13.5px", color: "#F1F5F9" } }, isDone ? "\u2705 Analysis Complete \u2014 Findings & Evidence" : "\u274C Task Failed \u2014 Details"), isDone && /* @__PURE__ */ React.createElement("span", { style: { fontSize: "10px", background: "rgba(16, 185, 129, 0.2)", color: "#10B981", padding: "2px 8px", borderRadius: "12px", fontWeight: 600 } }, "DONE")), /* @__PURE__ */ React.createElement("div", { className: "markdown-body", style: { maxHeight: "550px", overflowY: "auto", color: "#CBD5E1", fontSize: "12px", lineHeight: 1.6 } }, /* @__PURE__ */ React.createElement(MarkdownView, { content: task.answer || finalAnswer }))), hasTimeline && /* @__PURE__ */ React.createElement("div", { className: "time-series-viewer-card", style: { background: "#0F172A", borderRadius: "8px", padding: "12px", border: "1px solid #1E293B" } }, (timelineFrame || gifArt) && (() => {
    const frameFname = timelineFrame && timelineFrame.file ? getBasename(timelineFrame.file) : "";
    const matchingArt = frameFname ? (artifacts || []).find((a) => getBasename(typeof a === "string" ? a : a.name) === frameFname) : null;
    const gifUrl = gifArt ? typeof gifArt === "string" ? `/runs/${gifArt}` : gifArt.url : timelineFrame && timelineFrame.gif_url ? timelineFrame.gif_url : null;
    const initialSrc = matchingArt && matchingArt.url ? matchingArt.url : timelineFrame && timelineFrame.png_url ? timelineFrame.png_url : frameFname ? `/api/tasks/${taskId || task.id}/artifacts/${frameFname}` : gifUrl;
    if (!initialSrc) return null;
    return /* @__PURE__ */ React.createElement("div", { style: { textAlign: "center", marginBottom: "10px" } }, /* @__PURE__ */ React.createElement("div", { style: { position: "relative", display: "inline-block", maxWidth: "100%" } }, /* @__PURE__ */ React.createElement(
      "img",
      {
        src: initialSrc,
        alt: "Time Series Frame",
        style: {
          maxHeight: "400px",
          maxWidth: "100%",
          height: "auto",
          margin: "0 auto",
          borderRadius: "6px",
          border: "1px solid #334155",
          display: "block"
        },
        onError: (e) => {
          if (e.target.dataset.triedFallback === "true") {
            if (gifUrl && e.target.src !== gifUrl) {
              e.target.dataset.triedFallback = "gif";
              e.target.src = gifUrl;
            }
            return;
          }
          e.target.dataset.triedFallback = "true";
          if (frameFname) {
            const fbUrl = `/api/tasks/${taskId || task.id}/artifacts/${frameFname}`;
            if (e.target.src !== fbUrl) {
              e.target.src = fbUrl;
              return;
            }
          }
          if (gifUrl && e.target.src !== gifUrl) {
            e.target.src = gifUrl;
          }
        }
      }
    ), timelineFrame && (timelineFrame.label || timelineFrame.date) && /* @__PURE__ */ React.createElement("div", { style: {
      position: "absolute",
      bottom: "10px",
      left: "12px",
      background: "rgba(15, 23, 42, 0.85)",
      backdropFilter: "blur(4px)",
      color: "#38BDF8",
      padding: "4px 10px",
      borderRadius: "4px",
      fontSize: "11px",
      fontWeight: 600,
      fontFamily: "monospace",
      border: "1px solid rgba(56, 189, 248, 0.3)"
    } }, timelineFrame.label || timelineFrame.date || "")));
  })(), /* @__PURE__ */ React.createElement(
    TimeSeriesPanel,
    {
      taskId: taskId || task.id,
      runDir: task.run_dir,
      onFrameChange: (frame) => setTimelineFrame(frame)
    }
  )), artifacts.length > 0 && /* @__PURE__ */ React.createElement("div", { className: "task-deliverables-card", style: { background: "#111827", border: "1px solid #1E293B", borderRadius: "8px", padding: "14px" } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "10px", flexWrap: "wrap", gap: "6px" } }, /* @__PURE__ */ React.createElement("span", { style: { fontWeight: 600, fontSize: "13px", color: "#F1F5F9" } }, "\u{1F4E6} Generated Deliverables (", artifacts.length, " files)"), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: "6px" } }, canShow3D && /* @__PURE__ */ React.createElement(
    "button",
    {
      type: "button",
      className: "btn s",
      style: { fontSize: "11px", backgroundColor: isLidar ? "#047857" : "#0284C7", color: "#FFFFFF", border: "none", borderRadius: "4px", padding: "4px 8px", cursor: "pointer", display: "flex", alignItems: "center", gap: "4px" },
      onClick: () => setShowTerrain3D(true),
      title: isLidar ? "Open interactive 3D LiDAR Canopy & Structures Inspector" : "Open interactive 3D terrain viewer"
    },
    isLidar ? "\u{1F332} View 3D LiDAR & Canopy" : "\u{1F3D4}\uFE0F View 3D Terrain"
  ), /* @__PURE__ */ React.createElement(
    "button",
    {
      type: "button",
      className: "btn s primary",
      style: { fontSize: "11px", backgroundColor: "#0F766E", color: "#FFFFFF", border: "none", borderRadius: "4px", padding: "4px 8px", cursor: "pointer" },
      onClick: () => onSwitchToGlobe && onSwitchToGlobe(),
      title: "View all outputs overlaid on the 3D Globe"
    },
    "\u{1F30D} View on 3D Globe"
  ))), profileSvgArt && /* @__PURE__ */ React.createElement("div", { style: { marginBottom: "12px", background: "#0F172A", borderRadius: "8px", padding: "10px", border: "1px solid #1E293B", textAlign: "center" } }, /* @__PURE__ */ React.createElement(
    "img",
    {
      src: profileSvgArt.url || `/api/tasks/${taskId || task.id}/artifacts/${getBasename(typeof profileSvgArt === "string" ? profileSvgArt : profileSvgArt.name)}`,
      alt: "Elevation Cross-Section Profile",
      style: { maxWidth: "100%", height: "auto", display: "block", margin: "0 auto", borderRadius: "6px" }
    }
  )), /* @__PURE__ */ React.createElement("div", { className: "deliverables-grid", style: { display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: "8px" } }, artifacts.map((art, idx) => {
    const fname = typeof art === "string" ? art : art.name || "file";
    const artUrl = typeof art === "string" ? null : art.url;
    const ext = fname.toLowerCase().split(".").pop();
    const isTif = ext === "tif" || ext === "tiff";
    const isImg = ext === "png" || ext === "gif" || ext === "webp" || ext === "svg";
    const isPreviewable = isTif || isImg;
    const downloadUrl = artUrl || `/runs/${fname}`;
    return /* @__PURE__ */ React.createElement("div", { key: idx, className: "deliverable-chip", style: { display: "flex", alignItems: "center", gap: "6px", background: "#0B0F17", border: "1px solid #1E293B", padding: "6px 10px", borderRadius: "6px" } }, /* @__PURE__ */ React.createElement("span", { className: "file-icon", style: { fontSize: "14px" } }, isTif ? "\u{1F5FA}\uFE0F" : isImg ? "\u{1F5BC}\uFE0F" : "\u{1F4C4}"), /* @__PURE__ */ React.createElement("span", { className: "file-name mono", title: fname, style: { flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontSize: "11px", color: "#E2E8F0" } }, fname.split(/[/\\]/).pop()), /* @__PURE__ */ React.createElement("div", { style: { flexShrink: 0, display: "flex", gap: "4px" } }, isPreviewable ? /* @__PURE__ */ React.createElement(
      "button",
      {
        type: "button",
        className: "preview-btn",
        style: { background: "#1E293B", color: "#38BDF8", border: "1px solid #334155", borderRadius: "4px", fontSize: "10px", padding: "2px 6px", cursor: "pointer" },
        onClick: () => onPreviewFile && onPreviewFile(art)
      },
      "Preview"
    ) : /* @__PURE__ */ React.createElement(
      "a",
      {
        href: downloadUrl,
        download: fname.split(/[/\\]/).pop(),
        className: "preview-btn",
        style: { background: "#1E293B", color: "#94A3B8", border: "1px solid #334155", borderRadius: "4px", fontSize: "10px", padding: "2px 6px", textDecoration: "none", display: "inline-block" }
      },
      "Download"
    ), isTif && /* @__PURE__ */ React.createElement(
      "button",
      {
        type: "button",
        className: "globe-overlay-btn",
        style: { background: "#0F766E", color: "#FFFFFF", border: "none", borderRadius: "4px", fontSize: "10px", padding: "2px 6px", cursor: "pointer" },
        onClick: () => onSwitchToGlobe && onSwitchToGlobe(art),
        title: "Overlay on 3D Globe"
      },
      "\u{1F30D}"
    )));
  }))), canShow3D && /* @__PURE__ */ React.createElement(
    Terrain3DViewer,
    {
      isOpen: showTerrain3D,
      onClose: () => setShowTerrain3D(false),
      payloadUrl: terrain3dArt ? terrain3dArt.url || `/api/tasks/${taskId || task.id}/artifacts/${getBasename(typeof terrain3dArt === "string" ? terrain3dArt : terrain3dArt.name)}` : `/api/runs/${taskId || task.id}/terrain_3d.json`,
      availableTextures: artifacts.filter((a) => {
        const n = (typeof a === "string" ? a : a.name || "").toLowerCase();
        return (n.endsWith(".png") || n.endsWith(".jpg") || n.endsWith(".tif")) && !n.includes("profile.svg") && !n.includes("terrain_3d");
      }),
      title: isLidar ? "Interactive 3D LiDAR Canopy & Structures" : "Interactive 3D Digital Elevation Model"
    }
  ), relevantActivities.length > 0 && /* @__PURE__ */ React.createElement("div", { className: "task-execution-logs-card", style: { background: "#111827", border: "1px solid #1E293B", borderRadius: "8px", padding: "14px" } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "8px" } }, /* @__PURE__ */ React.createElement("span", { style: { fontWeight: 600, fontSize: "12.5px", color: "#E2E8F0" } }, "\u{1F52C} Execution Log & Reasoning (", relevantActivities.length, " events)"), /* @__PURE__ */ React.createElement(
    "button",
    {
      type: "button",
      className: "btn s",
      style: { fontSize: "11px", background: "#1E293B", color: "#E2E8F0", border: "1px solid #334155", padding: "2px 8px", borderRadius: "4px", cursor: "pointer" },
      onClick: () => setShowLogs(!showLogs)
    },
    showLogs ? "Hide Events" : "Show Events"
  )), showLogs && /* @__PURE__ */ React.createElement(
    "div",
    {
      ref: activityRef,
      onScroll: handleScroll,
      className: "worker-activity-feed",
      style: { marginTop: "10px", maxHeight: "540px", overflowY: "auto", overflowX: "hidden", display: "flex", flexDirection: "column", gap: "8px" }
    },
    relevantActivities.map((act, i) => {
      if (act.type === "thinking") {
        const textStr = act.text || "";
        const wordCount = textStr.trim() ? textStr.trim().split(/\s+/).filter(Boolean).length : 0;
        const charCount = textStr.length;
        const isLatestThinking = task.status === "running" && i === relevantActivities.length - 1;
        return /* @__PURE__ */ React.createElement(
          "details",
          {
            key: i,
            className: "claude-thinking",
            open: isLatestThinking || void 0,
            style: { border: "1px solid #1E293B", borderRadius: "6px", background: "#090D14", padding: "6px 10px" }
          },
          /* @__PURE__ */ React.createElement("summary", { className: "mono", style: { fontSize: "11px", cursor: "pointer", color: "#38BDF8", fontWeight: 600, userSelect: "none" } }, "\u{1F9E0} Reasoning trace (", wordCount, " words \xB7 ", charCount, " chars)"),
          /* @__PURE__ */ React.createElement(
            "div",
            {
              className: "mono",
              style: {
                whiteSpace: "pre-wrap",
                fontSize: "10.5px",
                marginTop: "6px",
                color: "#CBD5E1",
                wordBreak: "break-word",
                overflowWrap: "anywhere",
                maxHeight: "300px",
                overflowY: "auto",
                padding: "8px",
                background: "#0B0F17",
                borderRadius: "4px",
                borderLeft: "2px solid #0F766E"
              }
            },
            textStr || "Thinking\u2026"
          )
        );
      } else if (act.type === "text") {
        if (!act.text || !act.text.trim()) return null;
        return /* @__PURE__ */ React.createElement("div", { key: i, style: { padding: "6px 8px", background: "#0B0F17", borderRadius: "6px", border: "1px solid #1E293B", color: "#E2E8F0", fontSize: "11.5px" } }, /* @__PURE__ */ React.createElement(MarkdownView, { content: act.text }));
      } else if (act.type === "tool") {
        const argsObj = typeof act.args === "object" && act.args !== null ? act.args : null;
        const codeStr = argsObj && typeof argsObj.code === "string" ? argsObj.code : null;
        const inputFilesList = argsObj && Array.isArray(argsObj.input_files) ? argsObj.input_files : null;
        const isStacSearch = act.toolName === "search_stac";
        const isStacPropose = act.toolName === "propose_stac_scenes";
        const shortArgs = !codeStr && !isStacSearch && !isStacPropose ? typeof act.args === "string" ? act.args : JSON.stringify(act.args || {}) : "";
        return /* @__PURE__ */ React.createElement(
          "div",
          {
            key: i,
            className: `tool-card ${act.running ? "run" : act.ok ? "ok" : "bad"}`,
            style: {
              background: "#0B0F17",
              border: `1px solid ${act.running ? "#38BDF8" : act.ok ? "#0F766E" : "#EF4444"}`,
              borderLeft: `3px solid ${act.running ? "#38BDF8" : act.ok ? "#10B981" : "#EF4444"}`,
              borderRadius: "6px",
              padding: "8px 10px"
            }
          },
          /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: "8px", fontSize: "11.5px", flexWrap: "wrap" } }, /* @__PURE__ */ React.createElement("span", { className: "mono", style: { fontWeight: 600, color: "#38BDF8" } }, isStacSearch ? "\u{1F6F0}\uFE0F STAC Catalog Search (search_stac)" : isStacPropose ? "\u{1F6F0}\uFE0F Propose Satellite Previews (propose_stac_scenes)" : `\u{1F6E0}\uFE0F ${act.toolName}`), act.attempt && /* @__PURE__ */ React.createElement("span", { className: "mono", style: { fontSize: "10px", background: "#1E293B", color: "#CBD5E1", padding: "1px 6px", borderRadius: "4px" } }, "att ", act.attempt, act.max_attempts ? `/${act.max_attempts}` : ""), /* @__PURE__ */ React.createElement("span", { className: "mono", style: { marginLeft: "auto", fontSize: "10.5px", fontWeight: 600, color: act.running ? "#38BDF8" : act.ok ? "#10B981" : "#F87171" } }, act.running ? isStacSearch ? "\u23F3 querying Planetary Computer STAC\u2026" : "\u23F3 running in sandbox\u2026" : (act.duration_s != null ? `${act.duration_s}s \xB7 ` : "") + `exit ${act.exit_code ?? "\u2014"}`)),
          isStacSearch && argsObj && /* @__PURE__ */ React.createElement("div", { className: "mono", style: { fontSize: "10.5px", color: "#CBD5E1", marginTop: "6px", background: "#05080E", padding: "6px 8px", borderRadius: "4px", border: "1px solid #1E293B", display: "flex", flexWrap: "wrap", gap: "10px" } }, argsObj.location_name && /* @__PURE__ */ React.createElement("span", null, /* @__PURE__ */ React.createElement("strong", null, "Location:"), " ", argsObj.location_name), argsObj.collections && /* @__PURE__ */ React.createElement("span", null, /* @__PURE__ */ React.createElement("strong", null, "Collections:"), " ", Array.isArray(argsObj.collections) ? argsObj.collections.join(", ") : String(argsObj.collections)), (argsObj.start_date || argsObj.end_date) && /* @__PURE__ */ React.createElement("span", null, /* @__PURE__ */ React.createElement("strong", null, "Dates:"), " ", argsObj.start_date || "\u2026", " \u2192 ", argsObj.end_date || "\u2026"), argsObj.bbox && Array.isArray(argsObj.bbox) && /* @__PURE__ */ React.createElement("span", null, /* @__PURE__ */ React.createElement("strong", null, "BBox:"), " [", argsObj.bbox.map((n) => Number(n).toFixed(3)).join(", "), "]"), argsObj.max_cloud_cover != null && /* @__PURE__ */ React.createElement("span", null, /* @__PURE__ */ React.createElement("strong", null, "Max Cloud:"), " ", argsObj.max_cloud_cover, "%")),
          isStacPropose && argsObj && /* @__PURE__ */ React.createElement("div", { className: "mono", style: { fontSize: "10.5px", color: "#CBD5E1", marginTop: "6px", background: "#05080E", padding: "6px 8px", borderRadius: "4px", border: "1px solid #1E293B" } }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("strong", null, "Location:"), " ", argsObj.location_name || "Target AOI", " \u2022 ", /* @__PURE__ */ React.createElement("strong", null, "Proposed Scenes:"), " ", Array.isArray(argsObj.scenes) ? argsObj.scenes.length : 0), Array.isArray(argsObj.scenes) && argsObj.scenes.length > 0 && /* @__PURE__ */ React.createElement("div", { style: { marginTop: "4px", color: "#94A3B8", fontSize: "10px" } }, argsObj.scenes.map((s, idx) => `${s.collection || "STAC"} (${(s.datetime || s.id || "").slice(0, 10)})`).join(" \xB7 "))),
          inputFilesList && inputFilesList.length > 0 && /* @__PURE__ */ React.createElement("div", { className: "mono", style: { fontSize: "10px", color: "#94A3B8", marginTop: "4px" } }, "\u{1F4C2} Inputs (", inputFilesList.length, "): ", inputFilesList.map(getBasename).slice(0, 6).join(", "), inputFilesList.length > 6 ? ` +${inputFilesList.length - 6} more` : ""),
          codeStr && /* @__PURE__ */ React.createElement("details", { open: act.running || void 0, style: { marginTop: "6px", fontSize: "10.5px" } }, /* @__PURE__ */ React.createElement("summary", { className: "mono", style: { cursor: "pointer", color: "#14B8A6", fontWeight: 600, userSelect: "none" } }, "\u{1F4BB} Agent Python Code (", codeStr.split("\n").length, " lines)"), /* @__PURE__ */ React.createElement(
            "pre",
            {
              className: "mono",
              style: {
                margin: "4px 0 0 0",
                padding: "8px",
                background: "#05080E",
                border: "1px solid #1E293B",
                borderRadius: "4px",
                overflowX: "auto",
                overflowY: "auto",
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
                maxHeight: "260px",
                fontSize: "10px",
                color: "#E2E8F0"
              }
            },
            codeStr
          )),
          shortArgs && /* @__PURE__ */ React.createElement("div", { className: "mono", style: { fontSize: "10.5px", color: "#94A3B8", wordBreak: "break-all", overflowWrap: "anywhere", marginTop: "4px" } }, shortArgs.length > 260 ? shortArgs.slice(0, 257) + "\u2026" : shortArgs),
          (act.error || act.stdout) && /* @__PURE__ */ React.createElement("details", { open: act.ok === false || isStacSearch || void 0, style: { marginTop: "6px", fontSize: "10.5px" } }, /* @__PURE__ */ React.createElement("summary", { className: "mono", style: { cursor: "pointer", color: act.ok === false ? "#FCA5A5" : "#94A3B8", userSelect: "none" } }, isStacSearch ? "\u{1F4C4} STAC Search Results" : "\u{1F4C4} Output / Logs"), /* @__PURE__ */ React.createElement(
            "pre",
            {
              className: "mono",
              style: {
                margin: "4px 0 0 0",
                padding: "6px 8px",
                background: "#05080E",
                border: "1px solid #1E293B",
                borderRadius: "4px",
                overflowX: "auto",
                overflowY: "auto",
                whiteSpace: "pre-wrap",
                wordBreak: "break-all",
                overflowWrap: "anywhere",
                maxHeight: "220px",
                maxWidth: "100%",
                fontSize: "10px",
                color: act.ok === false ? "#FECACA" : "#CBD5E1"
              }
            },
            act.error || act.stdout
          ))
        );
      } else if (act.type === "stac_download") {
        return /* @__PURE__ */ React.createElement(
          "div",
          {
            key: i,
            className: `tool-card ${act.running ? "run" : act.ok ? "ok" : "bad"}`,
            style: {
              background: "#0B0F17",
              border: `1px solid ${act.running ? "#38BDF8" : act.ok ? "#0F766E" : "#EF4444"}`,
              borderLeft: `3px solid ${act.running ? "#38BDF8" : act.ok ? "#10B981" : "#EF4444"}`,
              borderRadius: "6px",
              padding: "8px 10px"
            }
          },
          /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: "8px", fontSize: "11.5px", flexWrap: "wrap" } }, /* @__PURE__ */ React.createElement("span", { className: "mono", style: { fontWeight: 600, color: "#38BDF8" } }, act.running ? "\u2B07\uFE0F Downloading STAC Band:" : act.ok ? "\u2705 Staged STAC Band:" : "\u274C STAC Download Failed:", " ", act.filename), /* @__PURE__ */ React.createElement("span", { className: "mono", style: { marginLeft: "auto", fontSize: "10.5px", fontWeight: 600, color: act.running ? "#38BDF8" : act.ok ? "#10B981" : "#F87171" } }, act.running ? "\u23F3 Cropping & downloading at 100% native resolution\u2026" : act.ok ? `${act.size_mb != null ? `${act.size_mb} MB \xB7 ` : ""}${act.duration_s != null ? `${act.duration_s}s` : "done"}` : act.error || "failed")),
          (act.collection || act.asset_key || act.width) && /* @__PURE__ */ React.createElement("div", { className: "mono", style: { fontSize: "10px", color: "#94A3B8", marginTop: "4px", display: "flex", flexWrap: "wrap", gap: "10px" } }, act.collection && /* @__PURE__ */ React.createElement("span", null, /* @__PURE__ */ React.createElement("strong", null, "Collection:"), " ", act.collection), act.asset_key && /* @__PURE__ */ React.createElement("span", null, /* @__PURE__ */ React.createElement("strong", null, "Band:"), " ", act.asset_key), act.date && /* @__PURE__ */ React.createElement("span", null, /* @__PURE__ */ React.createElement("strong", null, "Date:"), " ", act.date), act.width && act.height && /* @__PURE__ */ React.createElement("span", null, /* @__PURE__ */ React.createElement("strong", null, "Grid:"), " ", act.width, "\xD7", act.height, " px"))
        );
      } else if (act.type === "stac_staged") {
        const stagedList = act.files || [];
        return /* @__PURE__ */ React.createElement(
          "div",
          {
            key: i,
            className: "tool-card ok",
            style: {
              background: "#0B1320",
              border: "1px solid #0F766E",
              borderLeft: "3px solid #10B981",
              borderRadius: "6px",
              padding: "8px 10px"
            }
          },
          /* @__PURE__ */ React.createElement("div", { className: "mono", style: { fontWeight: 600, fontSize: "11.5px", color: "#10B981" } }, "\u{1F4E5} Staged ", stagedList.length, " Native-Resolution GeoTIFFs to Workspace"),
          stagedList.length > 0 && /* @__PURE__ */ React.createElement("div", { className: "mono", style: { fontSize: "10px", color: "#CBD5E1", marginTop: "4px", lineHeight: 1.5 } }, stagedList.map(getBasename).join(", "))
        );
      } else if (act.type === "stac_preview_ready") {
        const scCount = act.preview && Array.isArray(act.preview.scenes) ? act.preview.scenes.length : 0;
        return /* @__PURE__ */ React.createElement(
          "div",
          {
            key: i,
            className: "tool-card ok",
            style: {
              background: "#0B1120",
              border: "1px solid #0284C7",
              borderLeft: "3px solid #38BDF8",
              borderRadius: "6px",
              padding: "8px 10px"
            }
          },
          /* @__PURE__ */ React.createElement("div", { className: "mono", style: { fontWeight: 600, fontSize: "11.5px", color: "#38BDF8" } }, "\u{1F6F0}\uFE0F STAC Satellite Previews Ready (", scCount, " scene", scCount === 1 ? "" : "s", " proposed for review)")
        );
      } else if (act.type === "vision_check") {
        const imgName = act.image ? act.image.split(/[/\\]/).pop() : "image";
        const isStarted = act.state === "started";
        const isOk = act.verdict === "ok";
        const isBad = act.verdict === "needs_revision";
        const isNotVerified = act.verdict === "not_verified" || act.verdict === "insufficient_data";
        if (isStarted) {
          return /* @__PURE__ */ React.createElement("div", { key: i, className: "tool-card run", style: { padding: "6px 8px", borderLeft: "3px solid #3B82F6", marginTop: "6px", background: "#0B0F17", borderRadius: "4px" } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: "8px", fontSize: "11px", color: "#38BDF8" } }, /* @__PURE__ */ React.createElement("span", { className: "mono", style: { fontWeight: 600 } }, "\u{1F50D} Starting Visual QA: ", imgName), act.index && act.total && /* @__PURE__ */ React.createElement("span", { className: "mono", style: { marginLeft: "auto", fontSize: "10.5px", color: "#94A3B8" } }, act.index, " / ", act.total)));
        }
        return /* @__PURE__ */ React.createElement("div", { key: i, className: `tool-card ${isOk ? "ok" : isBad ? "bad" : isNotVerified ? "bad" : ""}`, style: { padding: "6px 8px", background: "#0B0F17", border: "1px solid #1E293B", borderRadius: "4px" } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: "8px", fontSize: "11px" } }, /* @__PURE__ */ React.createElement("span", { className: "mono", style: { fontWeight: 600, color: "#E2E8F0" } }, "\u{1F441}\uFE0F Visual QA: ", imgName), /* @__PURE__ */ React.createElement("span", { className: "mono", style: { marginLeft: "auto", fontSize: "10.5px", color: isOk ? "#10B981" : isBad ? "#EF4444" : "#F59E0B" } }, act.verdict || "checking\u2026")), act.text && act.text !== "ok" && /* @__PURE__ */ React.createElement("div", { style: { fontSize: "10.5px", color: "#CBD5E1", marginTop: "4px", whiteSpace: "pre-wrap", overflowWrap: "anywhere" } }, act.text));
      } else if (act.type && act.type.startsWith("vision_")) {
        return /* @__PURE__ */ React.createElement(ValidationViewer, { key: i, activity: act });
      }
      return null;
    })
  )));
}
export {
  SingleWorkerSlot
};

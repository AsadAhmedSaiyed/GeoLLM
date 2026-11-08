import React, { useState } from "https://esm.sh/react@18.2.0";
function QueryConsole({
  files = [],
  selectedFiles = [],
  setSelectedFiles,
  onSubmitTask,
  isSubmitting = false,
  onNotify
}) {
  const [prompt, setPrompt] = useState("");
  const removeSelectedFile = (fileName) => {
    setSelectedFiles(selectedFiles.filter((f) => f !== fileName));
  };
  const handleKeyDown = (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      handleRun();
    }
  };
  const handleRun = () => {
    const trimmedPrompt = prompt.trim();
    if (!trimmedPrompt) {
      if (onNotify) onNotify("Please enter a task description before running.", "warning");
      return;
    }
    const currentPrompt = trimmedPrompt;
    const currentFiles = [...selectedFiles || []];
    onSubmitTask(currentPrompt, currentFiles);
    setPrompt("");
    setSelectedFiles([]);
  };
  return /* @__PURE__ */ React.createElement("section", { className: "card comp", style: { background: "#111827", border: "1px solid #1E293B", borderRadius: "8px", padding: "14px", marginBottom: "14px" } }, /* @__PURE__ */ React.createElement("label", { className: "h", htmlFor: "q", style: { fontWeight: 600, fontSize: "12px", color: "#14B8A6", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: "6px", display: "block" } }, "Active Workspace Query Console"), /* @__PURE__ */ React.createElement(
    "textarea",
    {
      id: "q",
      placeholder: "Describe your geospatial task or location & dates in plain English (e.g. 'Show how green farming area changed near Basra, Iraq between May 2020 and May 2025')...",
      value: prompt,
      onChange: (e) => setPrompt(e.target.value),
      onKeyDown: handleKeyDown,
      "aria-label": "Active workspace task prompt",
      style: {
        width: "100%",
        minHeight: "80px",
        background: "#090D14",
        border: "1px solid #1E293B",
        borderRadius: "6px",
        color: "#F1F5F9",
        padding: "10px 12px",
        fontSize: "12px",
        fontFamily: "inherit",
        resize: "vertical",
        outline: "none",
        marginBottom: "8px"
      }
    }
  ), /* @__PURE__ */ React.createElement("div", { className: "att", style: { display: "flex", flexWrap: "wrap", gap: "6px", marginBottom: "10px" } }, selectedFiles.length === 0 ? /* @__PURE__ */ React.createElement("span", { style: { fontSize: "11px", color: "#38BDF8", fontWeight: 500, display: "flex", alignItems: "center", gap: "4px" } }, "\u{1F6F0}\uFE0F Autonomous STAC Mode \u2014 Agent will search & preview satellite imagery for your query (or select local files in sidebar)") : selectedFiles.map((fn) => /* @__PURE__ */ React.createElement("span", { key: fn, className: "at mono", style: { display: "inline-flex", alignItems: "center", gap: "6px", background: "#1E293B", color: "#14B8A6", padding: "3px 8px", borderRadius: "4px", fontSize: "10.5px" } }, fn, /* @__PURE__ */ React.createElement(
    "span",
    {
      className: "at-remove",
      onClick: () => removeSelectedFile(fn),
      title: "Remove dataset",
      style: { cursor: "pointer", color: "#EF4444", fontWeight: "bold" }
    },
    "\u2715"
  )))), /* @__PURE__ */ React.createElement("div", { className: "bar", style: { display: "flex", justifyContent: "flex-end", alignItems: "center" } }, /* @__PURE__ */ React.createElement(
    "button",
    {
      className: "btn p",
      onClick: handleRun,
      disabled: isSubmitting || !prompt.trim(),
      type: "button",
      style: {
        height: "36px",
        padding: "0 18px",
        display: "inline-flex",
        alignItems: "center",
        gap: "8px",
        backgroundColor: isSubmitting || !prompt.trim() ? "#1E293B" : "#0F766E",
        color: isSubmitting || !prompt.trim() ? "#64748B" : "#FFFFFF",
        border: "none",
        borderRadius: "6px",
        cursor: isSubmitting || !prompt.trim() ? "not-allowed" : "pointer",
        fontWeight: "bold",
        fontSize: "12px"
      }
    },
    /* @__PURE__ */ React.createElement("span", null, "Run task"),
    /* @__PURE__ */ React.createElement("span", { className: "mono", style: { fontSize: "10px", opacity: 0.85 } }, "Ctrl+Enter")
  )));
}
export {
  QueryConsole
};

// Edit this file to tune design without touching montage logic in index.html
window.__HF_THEME = {
  // CSS variables applied to :root at runtime
  cssVars: {
    "--font-main": "'Oswald', 'Segoe UI', sans-serif",
    "--bg-0": "#000000",
    "--bg-1": "#f4f5f9",
    "--bg-2": "#e2e8f0",
    "--ink-0": "#0f172a",
    "--ink-1": "#1e293b",
    "--ink-2": "#475569",
    "--line": "rgba(15, 23, 42, 0.08)",
    "--chip-ink": "#ffffff",
    "--accent": "#0f172a", // Accent is the main bold text color now
    "--bg-gradient":
      "linear-gradient(135deg, #f8fafc 0%, #f1f5f9 50%, #e2e8f0 100%)",
    "--safe-margins-border": "1px solid rgba(15, 23, 42, 0.05)",
    "--frame-outline-border": "2px solid rgba(15, 23, 42, 0.03)",
    "--frame-outline-shadow": "0 24px 48px rgba(15, 23, 42, 0.12)",
    "--panel-bg": "transparent", // Moving to a cleaner integrated look
    "--panel-shadow": "none",
    "--card-hero-bg": "transparent",
    "--card-steps-bg": "transparent",
    "--card-metrics-bg": "transparent",
    "--card-quote-bg": "transparent",
    "--scene-chip-bg": "rgba(15, 23, 42, 0.05)",
    "--scene-chip-border": "1px solid rgba(15, 23, 42, 0.1)",
    "--scene-tag-bg": "rgba(15, 23, 42, 0.08)",
    "--scene-tag-color": "#1e293b",
    "--scene-quote-border": "none",
    "--scene-quote-bg": "transparent",
    "--scene-quote-color": "#0f172a",
    "--scene-callout-bg": "transparent",
    "--scene-callout-border": "none",
    "--scene-callout-color": "#0f172a",
    "--metric-track-bg": "rgba(15, 23, 42, 0.1)",
    "--metric-fill-bg": "#0f172a",
    "--cue-pill-bg": "rgba(15, 23, 42, 0.05)",
    "--cue-pill-border": "1px solid rgba(15, 23, 42, 0.1)",
    "--cue-pill-color": "#0f172a",
    "--scene-cta-bg": "#0f172a",
    "--scene-cta-shadow": "0 10px 20px rgba(15, 23, 42, 0.15)",
    "--avatar-cue-bg": "rgba(15, 23, 42, 0.9)",
    "--avatar-cue-border": "1px solid rgba(255, 255, 255, 0.1)",
    "--avatar-cue-color": "#ffffff"
  },

  // Frame composition order for scenes where layoutMode is not explicitly set
  layoutCycle: ["avatar_frame", "presentation_full", "avatar_full", "presentation_full"],

  // Card style order for all scenes
  cardStyleCycle: ["hero", "steps", "quote"],

  // Card style order only for scenes where panel is visible (not avatar_full)
  visibleCardStyleCycle: ["hero", "steps", "quote"],

  // Labels shown in the top-right style pill
  cardStyleTag: {
    hero: "INTRO",
    steps: "PROCESS",
    quote: "SUMMARY"
  },

  // Character limits for text compaction
  textLimits: {
    titleMain: 100, // Allow more text with the new large style
    titleAccent: 80,
    lead: 150,
    insight: 250,
    step: 100,
    barLabel: 50
  }
};

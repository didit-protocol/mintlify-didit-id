export const AgentPromptAccordion = ({ prompt, title = "AI Agent Integration Prompt" }) => {
  const [copied, setCopied] = React.useState(false);

  const handleCopy = (e) => {
    e.stopPropagation();
    if (!prompt) return;
    navigator.clipboard.writeText(prompt.trim()).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  const agents = [
    "Claude Code",
    "Codex",
    "Cursor",
    "Devin",
    "Windsurf",
    "GitHub Copilot",
  ];

  return (
    <div className="didit-agent-card">
      {/* Header — macOS-style chrome with filename + copy */}
      <div className="didit-agent-titlebar">
        <div className="didit-agent-dots" aria-hidden="true">
          <span className="didit-agent-dot didit-agent-dot-red"></span>
          <span className="didit-agent-dot didit-agent-dot-yellow"></span>
          <span className="didit-agent-dot didit-agent-dot-green"></span>
        </div>
        <span className="didit-agent-filename">{title}</span>
        <button
          type="button"
          className={`didit-agent-copy ${copied ? "didit-agent-copy-copied" : ""}`}
          onClick={handleCopy}
          title="Copy prompt to clipboard"
          aria-label={copied ? "Copied!" : "Copy prompt to clipboard"}
        >
          {copied ? (
            <>
              <svg width="13" height="13" viewBox="0 0 16 16" fill="none">
                <path d="M3 8.5l3.5 3.5L13 4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
              <span>Copied</span>
            </>
          ) : (
            <>
              <svg width="13" height="13" viewBox="0 0 16 16" fill="none">
                <rect x="5" y="5" width="9" height="9" rx="1.5" stroke="currentColor" strokeWidth="1.5"/>
                <path d="M11 5V3.5A1.5 1.5 0 0 0 9.5 2h-6A1.5 1.5 0 0 0 2 3.5v6A1.5 1.5 0 0 0 3.5 11H5" stroke="currentColor" strokeWidth="1.5"/>
              </svg>
              <span>Copy</span>
            </>
          )}
        </button>
      </div>

      {/* Body — visible prompt, scrollable */}
      <pre className="didit-agent-body"><code>{prompt.trim()}</code></pre>

      {/* Footer — paste-into chips */}
      <div className="didit-agent-footer">
        <span className="didit-agent-footer-label">Paste into</span>
        <div className="didit-agent-chips">
          {agents.map((name) => (
            <span key={name} className="didit-agent-chip">{name}</span>
          ))}
        </div>
      </div>
    </div>
  );
};

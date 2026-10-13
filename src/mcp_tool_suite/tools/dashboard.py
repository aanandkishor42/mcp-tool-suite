"""Usage/cost dashboard tool: report accumulated tool and LLM usage.

Mirrors the ``/stats`` HTTP endpoint so clients that only speak MCP can still
read the in-process usage and estimated-cost totals.

The tool is also bound to an **MCP App** (``io.modelcontextprotocol/ui``): its
``_meta.ui.resourceUri`` points at :data:`DASHBOARD_URI`, an HTML page the host
renders in a sandboxed iframe and feeds the tool's result into. Hosts that do
not support MCP Apps get the plain text/Markdown answer, so the tool degrades
gracefully (SEP-2133).
"""

from __future__ import annotations

from mcp_tool_suite.context import AppContext
from mcp_tool_suite.registry import ToolCallable

DASHBOARD_URI = "ui://mcp-tool-suite/usage.html"
"""The ``ui://`` resource hosting the interactive usage dashboard."""

DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Usage dashboard</title>
<style>
  :root { color-scheme: light dark; }
  body { font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         margin: 0; padding: 16px; }
  h1 { font-size: 16px; margin: 0 0 12px; }
  .cards { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 16px; }
  .card { flex: 1 1 120px; border: 1px solid rgba(127,127,127,.35); border-radius: 8px;
          padding: 10px 12px; min-width: 120px; }
  .card .value { font-size: 20px; font-weight: 600; }
  .card .label { font-size: 11px; text-transform: uppercase; opacity: .65; letter-spacing: .04em; }
  table { width: 100%; border-collapse: collapse; margin-bottom: 16px; }
  caption { text-align: left; font-weight: 600; margin-bottom: 6px; }
  th, td { text-align: left; padding: 4px 8px; border-bottom: 1px solid rgba(127,127,127,.25); }
  th { font-size: 11px; text-transform: uppercase; opacity: .65; }
  .empty { opacity: .6; font-style: italic; }
  td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
</style>
</head>
<body>
  <h1>Usage &amp; estimated cost</h1>
  <div class="cards">
    <div class="card"><div class="value" id="toolCalls">0</div><div class="label">Tool calls</div></div>
    <div class="card"><div class="value" id="llmCalls">0</div><div class="label">LLM calls</div></div>
    <div class="card"><div class="value" id="tokens">0 / 0</div><div class="label">Tokens in / out</div></div>
    <div class="card"><div class="value" id="cost">$0.000000</div><div class="label">Est. cost (USD)</div></div>
  </div>
  <table><caption>Tools</caption>
    <thead><tr><th>Tool</th><th class="num">Calls</th><th class="num">Errors</th><th class="num">Avg ms</th></tr></thead>
    <tbody id="tools"></tbody>
  </table>
  <table><caption>Models</caption>
    <thead><tr><th>Model</th><th class="num">Calls</th><th class="num">In</th><th class="num">Out</th><th class="num">Cost</th></tr></thead>
    <tbody id="models"></tbody>
  </table>
<script>
  const parent = window.parent;
  let initialized = false;
  const num = (n) => (typeof n === "number" ? n.toLocaleString() : (n ?? 0));
  const usd = (n) => "$" + (typeof n === "number" ? n : 0).toFixed(6);
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  function render(summary) {
    const t = summary.totals || {};
    document.getElementById("toolCalls").textContent = num(t.tool_calls);
    document.getElementById("llmCalls").textContent = num(t.llm_calls);
    document.getElementById("tokens").textContent = num(t.input_tokens) + " / " + num(t.output_tokens);
    document.getElementById("cost").textContent = usd(t.estimated_cost_usd);

    const tools = Object.entries(summary.tools || {});
    document.getElementById("tools").innerHTML = tools.length
      ? tools.map(([name, e]) =>
          `<tr><td>${esc(name)}</td><td class="num">${num(e.count)}</td>` +
          `<td class="num">${num(e.errors)}</td><td class="num">${num(e.avg_ms)}</td></tr>`).join("")
      : '<tr><td colspan="4" class="empty">No tool calls yet.</td></tr>';

    const models = Object.values(summary.llms || {});
    document.getElementById("models").innerHTML = models.length
      ? models.map((e) =>
          `<tr><td>${esc(e.provider + ":" + e.model)}</td><td class="num">${num(e.calls)}</td>` +
          `<td class="num">${num(e.input_tokens)}</td><td class="num">${num(e.output_tokens)}</td>` +
          `<td class="num">${usd(e.estimated_cost_usd)}</td></tr>`).join("")
      : '<tr><td colspan="5" class="empty">No LLM calls yet.</td></tr>';
  }

  window.addEventListener("message", (event) => {
    if (event.source !== parent || event.data?.jsonrpc !== "2.0") return;
    if (event.data.id === 1 && event.data.result?.protocolVersion) {
      parent.postMessage({ jsonrpc: "2.0", method: "ui/notifications/initialized" }, "*");
      initialized = true;
      return;
    }
    if (!initialized || event.data.method !== "ui/notifications/tool-result") return;
    const params = event.data.params || {};
    let data = params.structuredContent;
    if (!data) {
      try { data = JSON.parse(params.content?.[0]?.text || "{}"); } catch (e) { data = {}; }
    }
    render(data);
  });

  parent.postMessage({
    jsonrpc: "2.0",
    id: 1,
    method: "ui/initialize",
    params: {
      appInfo: { name: "usage-dashboard", version: "1.0.0" },
      appCapabilities: {},
      protocolVersion: "2026-01-26",
    },
  }, "*");
</script>
</body>
</html>
"""


def render_usage(summary: dict) -> str:
    """Render a usage summary as a small Markdown dashboard."""
    totals = summary["totals"]
    lines = [
        "## Usage",
        "",
        f"- Tool calls: {totals['tool_calls']} ({totals['tool_errors']} errors)",
        f"- LLM calls: {totals['llm_calls']}",
        f"- Tokens: {totals['input_tokens']} in / {totals['output_tokens']} out",
        f"- Estimated cost: ${totals['estimated_cost_usd']:.6f}",
    ]
    if summary["tools"]:
        lines += ["", "### Tools", "", "| Tool | Calls | Errors | Avg ms |", "| --- | --- | --- | --- |"]
        for name, entry in summary["tools"].items():
            lines.append(
                f"| {name} | {entry['count']} | {entry['errors']} | {entry['avg_ms']} |"
            )
    if summary["llms"]:
        lines += [
            "",
            "### Models",
            "",
            "| Model | Calls | In | Out | Cost (USD) |",
            "| --- | --- | --- | --- | --- |",
        ]
        for entry in summary["llms"].values():
            lines.append(
                f"| {entry['provider']}:{entry['model']} | {entry['calls']} | "
                f"{entry['input_tokens']} | {entry['output_tokens']} | "
                f"{entry['estimated_cost_usd']:.6f} |"
            )
    return "\n".join(lines)


class UsageStatsTool:
    name = "usage_stats"
    description = (
        "Report tool-call and LLM-call usage for this server session, including call "
        "counts, latency and estimated USD cost. Returns structured totals plus a "
        "Markdown dashboard."
    )
    meta = {"ui": {"resourceUri": DASHBOARD_URI}}

    def create(self, ctx: AppContext) -> ToolCallable:
        async def usage_stats() -> dict:
            """Return accumulated tool and LLM usage with estimated cost."""
            summary = ctx.usage.summary()
            return {**summary, "dashboard": render_usage(summary)}

        return usage_stats

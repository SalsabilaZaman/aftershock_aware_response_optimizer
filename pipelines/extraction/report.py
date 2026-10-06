"""Self-contained HTML validation report — one card per dataset, no server,
all data inlined. This is the human checkpoint before anything downstream
(solver, dashboard) touches the data."""

import datetime
import html

PILL = {
    "pass": ("PASS", "#1a7f37", "#d2f4dd"),
    "warn": ("WARN", "#9a6700", "#fff1c2"),
    "fail": ("FAIL", "#cf222e", "#ffd7d9"),
}


def write_report(results, config, out_path):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    n_pass = sum(1 for r in results if r["status"] == "pass")
    n_warn = sum(1 for r in results if r["status"] == "warn")
    n_fail = sum(1 for r in results if r["status"] == "fail")

    cards = []
    for r in results:
        label, fg, bg = PILL[r["status"]]
        rows = []
        for i in r["issues"]:
            sev = i["severity"]
            state = " (auto-fixed)" if i.get("fixed") else ""
            color = "#57606a" if i.get("fixed") else ("#9a6700" if sev == "fixable" else "#cf222e")
            rows.append(
                f'<li style="color:{color}"><b>{sev}{state}:</b> '
                f"{html.escape(i['message'])}</li>"
            )
        issues_html = "<ul>" + "".join(rows) + "</ul>" if rows else "<p class='ok'>No issues.</p>"
        cards.append(f"""
    <div class="card">
      <div class="card-head">
        <h2>{html.escape(r['dataset'])}</h2>
        <span class="pill" style="color:{fg};background:{bg}">{label}</span>
      </div>
      <p class="meta">{r['row_count']:,} rows</p>
      {issues_html}
    </div>""")

    ev = config.get("event", {})
    doc = f"""<!doctype html>
<html><head><meta charset="utf-8">
<title>Extraction validation report</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 2rem auto; max-width: 900px;
         color: #1f2328; padding: 0 1rem; }}
  h1 {{ font-size: 1.4rem; }}
  .summary {{ color: #57606a; margin-bottom: 1.5rem; }}
  .card {{ border: 1px solid #d0d7de; border-radius: 8px; padding: 1rem 1.25rem;
          margin-bottom: 1rem; }}
  .card-head {{ display: flex; justify-content: space-between; align-items: center; }}
  .card h2 {{ font-size: 1.05rem; margin: 0; }}
  .pill {{ font-weight: 700; font-size: .8rem; padding: .2rem .7rem; border-radius: 999px; }}
  .meta {{ color: #57606a; margin: .3rem 0 .5rem; }}
  ul {{ margin: .25rem 0; padding-left: 1.3rem; }}
  li {{ margin: .2rem 0; }}
  .ok {{ color: #1a7f37; }}
</style></head><body>
<h1>Extraction validation report</h1>
<p class="summary">
  Scenario: {html.escape(str(ev.get('usgs_event_id', '')))} mainshock
  {html.escape(str(ev.get('mainshock_utc', '')))} UTC, window
  {html.escape(str(ev.get('window_start', '')))} → {html.escape(str(ev.get('window_end', '')))}
  · generated {now}<br>
  {n_pass} pass · {n_warn} warn · {n_fail} fail
</p>
{''.join(cards)}
</body></html>"""

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(doc)

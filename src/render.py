import json
from pathlib import Path

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Match Point</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Anton&family=Archivo:wght@500;600;700;800&family=Space+Mono:wght@400;700&display=swap');

  :root {{
    /* Court-inspired palette: deep court green, clay terracotta, hard-court blue, grass */
    --bg: #0e1912;
    --bg-elevated: #142218;
    --card-bg: #16261a;
    --card-border: #24382b;
    --card-border-hover: #35513f;
    --text-primary: #f4f1e6;
    --text-secondary: #93a394;
    --text-dim: #5e6f61;

    --clay: #c1571f;
    --clay-glow: rgba(193,87,31,0.22);
    --hard: #2e7fc4;
    --hard-glow: rgba(46,127,196,0.22);
    --grass: #5b9c4c;
    --grass-glow: rgba(91,156,76,0.22);
    --indoor: #8b6fc9;
    --indoor-glow: rgba(139,111,201,0.22);
    --unknown: #5e6f61;

    --high: #6fbf73;
    --medium: #d6a24a;
    --low: #d9704f;

    --bar-track: #1e2f22;
    --shadow: 0 1px 2px rgba(0,0,0,0.3), 0 8px 24px rgba(0,0,0,0.28);
  }}
  * {{ box-sizing: border-box; }}
  html {{ scroll-behavior: smooth; }}
  body {{
    background:
      radial-gradient(ellipse 900px 500px at 15% -10%, var(--clay-glow), transparent 60%),
      radial-gradient(ellipse 700px 500px at 100% 0%, var(--hard-glow), transparent 55%),
      var(--bg);
    color: var(--text-primary);
    font-family: 'Archivo', -apple-system, sans-serif;
    margin: 0;
    padding: 20px 14px 56px;
    -webkit-font-smoothing: antialiased;
    min-height: 100vh;
  }}

  /* ---------- Masthead ---------- */
  .masthead {{ margin-bottom: 20px; padding-top: 4px; }}
  .eyebrow {{
    font-family: 'Space Mono', monospace;
    font-size: 0.68rem;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    color: var(--clay);
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 6px;
  }}
  .eyebrow::before {{
    content: '';
    width: 7px; height: 7px;
    background: var(--clay);
    border-radius: 50%;
    box-shadow: 0 0 8px var(--clay);
  }}
  h1 {{
    font-family: 'Anton', 'Archivo', sans-serif;
    font-weight: 400;
    font-size: 2.6rem;
    letter-spacing: 0.01em;
    text-transform: uppercase;
    margin: 0;
    line-height: 0.92;
    background: linear-gradient(180deg, #ffffff 0%, #d8d2bf 100%);
    -webkit-background-clip: text;
    background-clip: text;
    -webkit-text-fill-color: transparent;
  }}
  .baseline {{
    margin-top: 10px;
    height: 0;
    border-top: 2px dashed var(--card-border);
    position: relative;
    width: 100%;
  }}
  .baseline::after {{
    content: '';
    position: absolute; left: 0; top: -2px;
    width: 64px; height: 2px;
    background: var(--clay);
  }}
  .meta {{
    color: var(--text-dim);
    font-family: 'Space Mono', monospace;
    font-size: 0.72rem;
    margin-top: 12px;
    letter-spacing: 0.01em;
  }}

  /* ---------- Tabs ---------- */
  .tabs {{ display: flex; gap: 6px; margin: 22px 0 18px; }}
  .tab {{
    background: var(--bg-elevated);
    border: 1px solid var(--card-border);
    color: var(--text-secondary);
    padding: 8px 20px;
    border-radius: 8px;
    cursor: pointer;
    font-size: 0.82rem;
    font-weight: 700;
    letter-spacing: 0.03em;
    text-transform: uppercase;
    transition: all 0.15s ease;
  }}
  .tab.active {{
    color: #fff8ee;
    background: var(--clay);
    border-color: var(--clay);
    box-shadow: 0 2px 14px var(--clay-glow);
  }}

  /* ---------- Cards ---------- */
  .cards {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(330px, 1fr)); gap: 14px; }}
  .card {{
    background: var(--card-bg);
    border: 1px solid var(--card-border);
    border-left: 3px solid var(--surface-color, var(--unknown));
    border-radius: 12px;
    padding: 16px 18px 18px;
    box-shadow: var(--shadow);
    position: relative;
    transition: border-color 0.15s ease;
  }}
  .card:hover {{ border-color: var(--card-border-hover); }}
  .card:hover {{ border-left-color: var(--surface-color, var(--unknown)); }}

  .card-top {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; gap: 8px; }}
  .surface-tag {{
    font-family: 'Space Mono', monospace;
    font-size: 0.66rem;
    font-weight: 700;
    letter-spacing: 0.09em;
    text-transform: uppercase;
    color: var(--surface-color, var(--text-dim));
    display: flex; align-items: center; gap: 6px;
  }}
  .surface-tag::before {{
    content: '';
    width: 8px; height: 8px;
    border-radius: 2px;
    background: var(--surface-color, var(--unknown));
  }}
  .surface-tag .tour {{ color: var(--text-dim); font-weight: 500; }}

  .confidence-meter {{ display: flex; align-items: center; gap: 5px; }}
  .confidence-meter .dot {{ width: 6px; height: 6px; border-radius: 50%; background: var(--card-border); }}
  .confidence-meter.high .dot:nth-child(-n+3) {{ background: var(--high); }}
  .confidence-meter.medium .dot:nth-child(-n+2) {{ background: var(--medium); }}
  .confidence-meter.low .dot:nth-child(-n+1) {{ background: var(--low); }}
  .confidence-label {{
    font-family: 'Space Mono', monospace;
    font-size: 0.64rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-left: 3px;
  }}
  .confidence-meter.high .confidence-label {{ color: var(--high); }}
  .confidence-meter.medium .confidence-label {{ color: var(--medium); }}
  .confidence-meter.low .confidence-label {{ color: var(--low); }}

  .matchup {{
    font-family: 'Archivo', sans-serif;
    font-weight: 800;
    font-size: 1.22rem;
    line-height: 1.2;
    margin-bottom: 3px;
    letter-spacing: -0.01em;
  }}
  .matchup .vs {{ color: var(--text-dim); font-weight: 500; font-size: 0.95rem; margin: 0 2px; }}

  .sub-row {{
    display: flex; justify-content: space-between; align-items: baseline;
    margin-bottom: 16px; gap: 10px;
  }}
  .tournament {{ font-size: 0.78rem; color: var(--text-secondary); }}
  .match-time {{
    font-family: 'Space Mono', monospace;
    font-size: 0.7rem;
    font-weight: 700;
    color: var(--clay);
    background: rgba(193,87,31,0.12);
    padding: 3px 9px;
    border-radius: 5px;
    white-space: nowrap;
    flex-shrink: 0;
  }}
  .match-time.tbd {{ color: var(--text-dim); background: rgba(94,111,97,0.14); }}

  /* score bar */
  .score-bar {{ margin-bottom: 14px; }}
  .score-bar-labels {{
    display: flex; justify-content: space-between;
    font-family: 'Space Mono', monospace;
    font-size: 1rem; font-weight: 700;
    margin-bottom: 6px;
  }}
  .score-bar-labels .leader {{ color: var(--clay); }}
  .score-bar-track {{
    display: flex; height: 8px; border-radius: 4px; overflow: hidden;
    background: var(--bar-track);
    gap: 2px;
  }}
  .score-bar-fill-a {{ background: var(--clay); height: 100%; border-radius: 3px 0 0 3px; }}
  .score-bar-fill-b {{ background: var(--text-dim); height: 100%; border-radius: 0 3px 3px 0; }}
  .score-bar-names {{
    display: flex; justify-content: space-between;
    font-size: 0.72rem; color: var(--text-secondary); margin-top: 5px;
    font-weight: 600;
  }}

  /* stat grid */
  .stat-grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1px;
    background: var(--card-border);
    border-radius: 8px;
    overflow: hidden;
    margin-top: 12px;
  }}
  .stat-cell {{
    background: var(--bg-elevated);
    padding: 9px 11px;
  }}
  .stat-cell.full {{ grid-column: 1 / -1; }}
  .stat-label {{
    font-size: 0.66rem;
    color: var(--text-dim);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 3px;
  }}
  .stat-value {{
    font-family: 'Space Mono', monospace;
    font-size: 0.82rem;
    font-weight: 700;
    color: var(--text-primary);
  }}
  .stat-value.dim {{ font-weight: 400; color: var(--text-secondary); font-size: 0.78rem; }}

  .empty {{
    color: var(--text-dim);
    padding: 70px 20px;
    text-align: center;
    font-size: 0.9rem;
    font-family: 'Space Mono', monospace;
    grid-column: 1 / -1;
  }}
</style>
</head>
<body>
  <div class="masthead">
    <div class="eyebrow">Live model output</div>
    <h1>Match Point</h1>
    <div class="baseline"></div>
    <div class="meta">{generated_at} &nbsp;/&nbsp; {n_predictions} matches &nbsp;/&nbsp; {n_gaps} data gap(s) flagged &nbsp;/&nbsp; local time</div>
  </div>

  <div class="tabs">
    <div class="tab active" onclick="showTab('all')" id="tab-all">All</div>
    <div class="tab" onclick="showTab('atp')" id="tab-atp">ATP</div>
    <div class="tab" onclick="showTab('wta')" id="tab-wta">WTA</div>
  </div>

  <div class="cards" id="cards-all">{cards_all}</div>
  <div class="cards" id="cards-atp" style="display:none;">{cards_atp}</div>
  <div class="cards" id="cards-wta" style="display:none;">{cards_wta}</div>

  <script>
    function showTab(tour) {{
      ['all', 'atp', 'wta'].forEach(t => {{
        document.getElementById('cards-' + t).style.display = (t === tour) ? 'grid' : 'none';
        document.getElementById('tab-' + t).classList.toggle('active', t === tour);
      }});
    }}

    // Convert each card's raw UTC timestamp (in data-utc) into the
    // viewer's own local time client-side, since this page is static
    // and generated once but viewed from any timezone.
    function renderLocalTimes() {{
      document.querySelectorAll('.match-time[data-utc]').forEach(el => {{
        const raw = el.getAttribute('data-utc');
        if (!raw) {{
          el.textContent = 'Time TBD';
          el.classList.add('tbd');
          return;
        }}
        const d = new Date(raw);
        if (isNaN(d.getTime())) {{
          el.textContent = 'Time TBD';
          el.classList.add('tbd');
          return;
        }}
        const now = new Date();
        const isToday = d.toDateString() === now.toDateString();
        const tomorrow = new Date(now); tomorrow.setDate(now.getDate() + 1);
        const isTomorrow = d.toDateString() === tomorrow.toDateString();
        const timeStr = d.toLocaleTimeString(undefined, {{ hour: 'numeric', minute: '2-digit' }});
        let dayStr;
        if (isToday) dayStr = 'Today';
        else if (isTomorrow) dayStr = 'Tomorrow';
        else dayStr = d.toLocaleDateString(undefined, {{ month: 'short', day: 'numeric' }});
        el.textContent = dayStr + ' \\u00b7 ' + timeStr;
      }});
    }}
    renderLocalTimes();
  </script>
</body>
</html>
"""


CARD_TEMPLATE = """
<div class="card" style="--surface-color: {surface_color};">
  <div class="card-top">
    <span class="surface-tag"><span class="tour">{tour}</span> &middot; {surface}</span>
    <span class="confidence-meter {confidence}">
      <span class="dot"></span><span class="dot"></span><span class="dot"></span>
      <span class="confidence-label">{confidence}</span>
    </span>
  </div>
  <div class="matchup">{player_a}<span class="vs">vs</span>{player_b}</div>
  <div class="sub-row"><span class="tournament">{tournament}</span><span class="match-time" data-utc="{time}">&nbsp;</span></div>
  <div class="score-bar">
    <div class="score-bar-labels"><span class="{a_leader}">{a_pct}%</span><span class="{b_leader}">{b_pct}%</span></div>
    <div class="score-bar-track"><div class="score-bar-fill-a" style="width:{a_pct}%"></div><div class="score-bar-fill-b" style="width:{b_pct}%"></div></div>
    <div class="score-bar-names"><span>{player_a}</span><span>{player_b}</span></div>
  </div>
  <div class="stat-grid">
    <div class="stat-cell"><div class="stat-label">Fair odds</div><div class="stat-value">{fair_a} / {fair_b}</div></div>
    <div class="stat-cell"><div class="stat-label">Straight sets</div><div class="stat-value dim">{straight_a}% / {straight_b}%</div></div>
    <div class="stat-cell"><div class="stat-label">Total games</div><div class="stat-value">avg {avg} &middot; med {median}</div></div>
    <div class="stat-cell"><div class="stat-label">Tiebreak chance</div><div class="stat-value">{tb}%</div></div>
    <div class="stat-cell full"><div class="stat-label">Model agreement</div><div class="stat-value dim">{agreement} &middot; uncertainty {uncertainty}</div></div>
  </div>
</div>
"""

SURFACE_COLORS = {
    "clay": "var(--clay)",
    "hard": "var(--hard)",
    "grass": "var(--grass)",
    "indoor_hard": "var(--indoor)",
    "indoor_clay": "var(--indoor)",
    "unknown": "var(--unknown)",
}

def render_card(p):
    a_pct = round(p['match_winner']['player_a_prob']*100, 1)
    b_pct = round(p['match_winner']['player_b_prob']*100, 1)
    surface = p.get('surface', 'unknown') or 'unknown'
    return CARD_TEMPLATE.format(
        tour=p.get('tour', ''),
        surface=surface,
        surface_color=SURFACE_COLORS.get(surface, "var(--unknown)"),
        confidence=p.get('confidence', 'low'),
        player_a=p.get('player_a', ''),
        player_b=p.get('player_b', ''),
        tournament=p.get('tournament', ''),
        time=p.get('match_time_utc') or '',
        a_pct=a_pct, b_pct=b_pct,
        a_leader='leader' if a_pct >= b_pct else '',
        b_leader='leader' if b_pct > a_pct else '',
        fair_a=p.get('fair_odds', {}).get('player_a', '—'),
        fair_b=p.get('fair_odds', {}).get('player_b', '—'),
        straight_a=round(p['set_winner']['player_a_straight_sets_prob']*100, 1),
        straight_b=round(p['set_winner']['player_b_straight_sets_prob']*100, 1),
        avg=p['games_total']['average'], median=p['games_total']['median'],
        tb=round(p.get('tiebreak_probability', 0)*100, 1),
        agreement=p.get('model_agreement', '—'),
        uncertainty=p.get('uncertainty', '—'),
    )

def render_site(data, output_path='index.html'):
    predictions = data.get('predictions', [])
    atp = [p for p in predictions if p.get('tour') == 'ATP']
    wta = [p for p in predictions if p.get('tour') == 'WTA']
    html = HTML_TEMPLATE.format(
        generated_at=data.get('generated_at', ''),
        n_predictions=len(predictions),
        n_gaps=len(data.get('data_quality', {}).get('errors', [])),
        cards_all=''.join(render_card(p) for p in predictions) or '<div class="empty">No matches found.</div>',
        cards_atp=''.join(render_card(p) for p in atp) or '<div class="empty">No ATP matches found.</div>',
        cards_wta=''.join(render_card(p) for p in wta) or '<div class="empty">No WTA matches found.</div>',
    )
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)

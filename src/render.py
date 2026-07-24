import json
from pathlib import Path

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Tennis Predictions</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;600;700&family=Inter:wght@400;500;600&family=Roboto+Mono:wght@500;600&display=swap');

  :root {{
    /* Light theme -- warm neutral paper, green as accent only */
    --bg: #f6f5f1;
    --bg-line: #ece9e1;
    --card-bg: #ffffff;
    --card-border: #e2e0d8;
    --text-primary: #24261f;
    --text-secondary: #77786d;
    --accent: #4a7c59;
    --high: #3f7a4f;
    --medium: #b8863f;
    --low: #c1573f;
    --bar-track: #eae8e0;
    --time-bg: #eef0e8;
    --shadow: 0 1px 2px rgba(20,20,15,0.05), 0 1px 10px rgba(20,20,15,0.03);
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      /* Dark theme -- neutral charcoal, green as accent only */
      --bg: #17181a;
      --bg-line: #1e2022;
      --card-bg: #1f2123;
      --card-border: #2c2f31;
      --text-primary: #eceae4;
      --text-secondary: #93958f;
      --accent: #7fbb8f;
      --high: #7fbb8f;
      --medium: #d6ab68;
      --low: #d98a72;
      --bar-track: #2a2d2f;
      --time-bg: #232826;
      --shadow: 0 1px 3px rgba(0,0,0,0.35);
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    background: var(--bg);
    background-image: repeating-linear-gradient(
      to bottom, transparent, transparent 79px, var(--bg-line) 79px, var(--bg-line) 80px
    );
    color: var(--text-primary);
    font-family: 'Inter', -apple-system, sans-serif;
    margin: 0;
    padding: 24px 16px 48px;
    -webkit-font-smoothing: antialiased;
  }}
  .masthead {{ margin-bottom: 22px; }}
  h1 {{
    font-family: 'Barlow Condensed', sans-serif;
    font-weight: 700;
    font-size: 2.1rem;
    letter-spacing: 0.01em;
    margin: 0 0 2px;
    line-height: 1;
  }}
  h1::after {{
    content: '';
    display: block;
    width: 46px;
    height: 3px;
    background: var(--accent);
    margin-top: 10px;
    border-radius: 2px;
  }}
  .meta {{ color: var(--text-secondary); font-size: 0.82rem; margin-top: 12px; }}
  .tabs {{ display: flex; gap: 8px; margin: 20px 0 18px; }}
  .tab {{
    background: transparent;
    border: 1px solid var(--card-border);
    color: var(--text-secondary);
    padding: 7px 18px;
    border-radius: 999px;
    cursor: pointer;
    font-size: 0.85rem;
    font-weight: 500;
    transition: all 0.15s ease;
  }}
  .tab.active {{ color: var(--bg); background: var(--accent); border-color: var(--accent); }}
  .cards {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 12px; }}
  .card {{
    background: var(--card-bg);
    border: 1px solid var(--card-border);
    border-radius: 10px;
    padding: 14px 18px 18px;
    box-shadow: var(--shadow);
  }}
  .card-top {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }}
  .tour-badge {{
    font-family: 'Roboto Mono', monospace;
    font-size: 0.68rem;
    color: var(--text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.08em;
  }}
  .confidence {{
    font-family: 'Roboto Mono', monospace;
    font-size: 0.65rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    padding: 3px 9px;
    border-radius: 999px;
  }}
  .confidence.high {{ background: rgba(74,124,89,0.14); color: var(--high); }}
  .confidence.medium {{ background: rgba(184,134,63,0.16); color: var(--medium); }}
  .confidence.low {{ background: rgba(193,87,63,0.14); color: var(--low); }}
  .matchup {{
    font-family: 'Barlow Condensed', sans-serif;
    font-weight: 600;
    font-size: 1.28rem;
    line-height: 1.15;
    margin-bottom: 2px;
  }}
  .sub-row {{
    display: flex; justify-content: space-between; align-items: baseline;
    margin-bottom: 14px; gap: 10px;
  }}
  .tournament {{ font-size: 0.78rem; color: var(--text-secondary); }}
  .match-time {{
    font-family: 'Roboto Mono', monospace;
    font-size: 0.72rem;
    font-weight: 500;
    color: var(--accent);
    background: var(--time-bg);
    padding: 2px 8px;
    border-radius: 5px;
    white-space: nowrap;
    flex-shrink: 0;
  }}
  .match-time.tbd {{ color: var(--text-secondary); }}

  .winner-bar {{ margin-bottom: 12px; }}
  .winner-bar-labels {{
    display: flex; justify-content: space-between;
    font-family: 'Roboto Mono', monospace;
    font-size: 0.9rem; font-weight: 600;
    margin-bottom: 5px;
  }}
  .winner-bar-track {{
    display: flex; height: 7px; border-radius: 4px; overflow: hidden;
    background: var(--bar-track);
  }}
  .winner-bar-fill-a {{ background: var(--accent); height: 100%; }}
  .winner-bar-fill-b {{ background: var(--text-secondary); opacity: 0.35; height: 100%; }}
  .winner-bar-names {{
    display: flex; justify-content: space-between;
    font-size: 0.72rem; color: var(--text-secondary); margin-top: 4px;
  }}

  .market-row {{
    display: flex; justify-content: space-between; align-items: baseline;
    font-size: 0.82rem; padding: 7px 0;
    border-top: 1px solid var(--card-border);
  }}
  .market-label {{ color: var(--text-secondary); }}
  .market-value {{ font-family: 'Roboto Mono', monospace; font-weight: 500; text-align: right; }}
  .empty {{ color: var(--text-secondary); padding: 60px 20px; text-align: center; font-size: 0.9rem; }}
</style>
</head>
<body>
  <div class="masthead">
    <h1>Tennis Predictions</h1>
    <div class="meta">Generated {generated_at} &middot; {n_predictions} matches &middot; {n_gaps} data gap(s) flagged &middot; times shown in your local timezone</div>
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
<div class="card">
  <div class="card-top"><span class="tour-badge">{tour} · {surface}</span><span class="confidence {confidence}">{confidence} confidence</span></div>
  <div class="matchup">{player_a} vs {player_b}</div>
  <div class="sub-row"><span class="tournament">{tournament}</span><span class="match-time" data-utc="{time}">&nbsp;</span></div>
  <div class="winner-bar"><div class="winner-bar-labels"><span>{a_pct}%</span><span>{b_pct}%</span></div><div class="winner-bar-track"><div class="winner-bar-fill-a" style="width:{a_pct}%"></div><div class="winner-bar-fill-b" style="width:{b_pct}%"></div></div><div class="winner-bar-names"><span>{player_a}</span><span>{player_b}</span></div></div>
  <div class="market-row"><span class="market-label">Fair odds</span><span class="market-value">{fair_a} / {fair_b}</span></div>
  <div class="market-row"><span class="market-label">Straight sets</span><span class="market-value">{player_a} {straight_a}% / {player_b} {straight_b}%</span></div>
  <div class="market-row"><span class="market-label">Total games</span><span class="market-value">avg {avg} · median {median} · TB {tb}%</span></div>
  <div class="market-row"><span class="market-label">Model agreement</span><span class="market-value">{agreement} · uncertainty {uncertainty}</span></div>
</div>
"""

def render_card(p):
    return CARD_TEMPLATE.format(tour=p.get('tour',''),surface=p.get('surface','unknown'),confidence=p.get('confidence','low'),player_a=p.get('player_a',''),player_b=p.get('player_b',''),tournament=p.get('tournament',''),time=p.get('match_time_utc') or '',a_pct=round(p['match_winner']['player_a_prob']*100,1),b_pct=round(p['match_winner']['player_b_prob']*100,1),fair_a=p.get('fair_odds',{}).get('player_a','—'),fair_b=p.get('fair_odds',{}).get('player_b','—'),straight_a=round(p['set_winner']['player_a_straight_sets_prob']*100,1),straight_b=round(p['set_winner']['player_b_straight_sets_prob']*100,1),avg=p['games_total']['average'],median=p['games_total']['median'],tb=round(p.get('tiebreak_probability',0)*100,1),agreement=p.get('model_agreement','—'),uncertainty=p.get('uncertainty','—'))

def render_site(data, output_path='index.html'):
    predictions=data.get('predictions',[])
    atp=[p for p in predictions if p.get('tour')=='ATP']; wta=[p for p in predictions if p.get('tour')=='WTA']
    html=HTML_TEMPLATE.format(generated_at=data.get('generated_at',''),n_predictions=len(predictions),n_gaps=len(data.get('data_quality',{}).get('errors',[])),cards_all=''.join(render_card(p) for p in predictions) or '<div class="empty">No matches found.</div>',cards_atp=''.join(render_card(p) for p in atp) or '<div class="empty">No ATP matches found.</div>',cards_wta=''.join(render_card(p) for p in wta) or '<div class="empty">No WTA matches found.</div>')
    with open(output_path,'w',encoding='utf-8') as f: f.write(html)

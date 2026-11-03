from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path

from .progression import (
    STATUS_ORDER,
    ExerciseAnalysis,
    ProgressionConfig,
    analyze_all,
    muscle_for,
    plan_workouts,
    weekly_muscle_volume,
)

RECORD_REPS = (1, 3, 5, 8, 10, 12, 15)


def _records(analysis: ExerciseAnalysis) -> list[dict[str, object]]:
    """Best weight achieved for at least N reps (least assistance for assisted lifts)."""
    assisted = analysis.kind == "assisted"
    records = []
    for target in RECORD_REPS:
        best: tuple[float, str, int] | None = None
        for session in analysis.sessions:
            for s in session.sets:
                if s.set_type in ("warmup", "dropset") or s.reps < target:
                    continue
                if assisted and s.weight <= 0:
                    continue  # blank assistance is ambiguous, not a record
                better = best is None or (s.weight < best[0] if assisted else s.weight > best[0])
                if better:
                    best = (s.weight, session.started_at[:10], s.reps)
        if best is not None:
            records.append({"reps": target, "weight": best[0], "date": best[1], "actual_reps": best[2]})
    return records


def _summary(analysis: ExerciseAnalysis) -> str:
    if analysis.kind == "assisted":
        best = min(s.working_weight for s in analysis.sessions)
        head = f"Least assistance {best:g} lb"
    elif analysis.kind == "bodyweight":
        head = f"Best set {max(max(s.reps) for s in analysis.sessions)} reps"
    else:
        head = f"Best Est. 1RM {max(analysis.scores):.0f} lb"
    return f"{head} · {analysis.status}: {analysis.status_reason}"


def _exercise_payload(analysis: ExerciseAnalysis) -> dict[str, object]:
    sessions = []
    running_best: float | None = None
    for session, score in zip(analysis.sessions, analysis.scores):
        is_pr = running_best is None or score > running_best
        running_best = score if running_best is None else max(running_best, score)
        working_ids = {id(s) for s in session.working_sets}
        sessions.append(
            {
                "date": session.started_at[:10],
                "workout": session.workout_name,
                "weight": session.working_weight,
                "score": score,
                "pr": is_pr,
                "total": session.total_reps,
                "sets": [
                    [s.weight, s.reps, s.rpe, s.set_type, id(s) in working_ids]
                    for s in session.sets
                ],
            }
        )
    p = analysis.prescription
    return {
        "kind": analysis.kind,
        "muscle": muscle_for(analysis.name),
        "status": analysis.status,
        "status_reason": analysis.status_reason,
        "change_4w": analysis.change_4w,
        "change_12w": analysis.change_12w,
        "rep_range": [analysis.rep_range.low, analysis.rep_range.high],
        "rep_range_source": analysis.rep_range.source,
        "step": (
            "weights you have used: " + ", ".join(f"{w:g}" for w in analysis.ladder)
            if analysis.ladder
            else f"+{analysis.increment:g} lb"
        ),
        "prescription": (
            {
                "action": p.action,
                "weight": p.weight,
                "targets": list(p.target_reps),
                "text": p.describe(),
                "reason": p.reason,
            }
            if p
            else None
        ),
        "records": _records(analysis),
        "sessions": sessions,
        "summary": _summary(analysis),
    }


_PAGE_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Lifting Progress</title>
  <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
  <style>
    :root {
      --bg: #f6f6f8; --card: #fff; --text: #1a202c; --muted: #64748b; --line: #e2e8f0;
      --accent: #6b46c1; --accent-soft: #ede9fe;
      --good: #15803d; --good-bg: #dcfce7; --warn: #b45309; --warn-bg: #fef3c7;
      --bad: #b91c1c; --bad-bg: #fee2e2; --info: #1d4ed8; --info-bg: #dbeafe;
      --neutral: #475569; --neutral-bg: #f1f5f9;
    }
    * { box-sizing: border-box; }
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      margin: 0; background: var(--bg); color: var(--text); }
    .container { max-width: 760px; margin: 0 auto; padding: 0 12px 40px; }
    header { position: sticky; top: 0; background: var(--bg); padding: 10px 0 8px; z-index: 5; }
    .asof { color: var(--muted); font-size: 12px; margin: 0 2px 8px; }
    .tabs { display: flex; gap: 4px; background: var(--card); border-radius: 10px; padding: 4px;
      box-shadow: 0 1px 2px rgba(0,0,0,0.06); }
    .tabs button { flex: 1; border: 0; background: transparent; padding: 9px 4px; border-radius: 7px;
      font-size: 14px; color: var(--muted); font-weight: 600; }
    .tabs button.active { background: var(--accent); color: #fff; }
    .view { display: none; }
    .view.active { display: block; }
    .pills { display: flex; gap: 6px; overflow-x: auto; margin: 12px 0; padding-bottom: 2px; }
    .pills button { white-space: nowrap; border: 1px solid var(--line); background: var(--card);
      border-radius: 999px; padding: 7px 12px; font-size: 13px; color: var(--text); }
    .pills button.active { background: var(--accent-soft); border-color: var(--accent); color: var(--accent); font-weight: 600; }
    .pills .tag { font-size: 10px; text-transform: uppercase; letter-spacing: .04em; margin-left: 4px; color: var(--accent); }
    .card { background: var(--card); border-radius: 10px; box-shadow: 0 1px 3px rgba(0,0,0,0.08);
      padding: 12px; margin-bottom: 10px; }
    .card h3 { margin: 0 0 6px; font-size: 15px; font-weight: 600; }
    .row-head { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
    .ex-name { font-weight: 600; font-size: 15px; cursor: pointer; }
    .ex-name:hover { color: var(--accent); }
    .chip { font-size: 11px; font-weight: 600; padding: 3px 8px; border-radius: 999px; white-space: nowrap; }
    .chip.Progressing { color: var(--good); background: var(--good-bg); }
    .chip.Holding, .chip.Archived { color: var(--neutral); background: var(--neutral-bg); }
    .chip.Stalled { color: var(--warn); background: var(--warn-bg); }
    .chip.Regressing { color: var(--bad); background: var(--bad-bg); }
    .chip.Returning { color: var(--info); background: var(--info-bg); }
    .rx { font-size: 22px; font-weight: 700; margin: 6px 0 2px; font-variant-numeric: tabular-nums; }
    .rx .action { font-size: 12px; font-weight: 600; color: var(--accent); margin-left: 6px; text-transform: uppercase; letter-spacing: .04em; }
    .reason { font-size: 13px; color: var(--text); margin: 2px 0 6px; }
    .meta { font-size: 12px; color: var(--muted); }
    .board-row { display: grid; grid-template-columns: minmax(0, 1fr) 80px 58px 58px; gap: 8px; align-items: center;
      padding: 9px 2px; border-bottom: 1px solid var(--line); cursor: pointer; }
    .board-row:last-child { border-bottom: 0; }
    .board-row .name { font-size: 14px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .board-row .sub { font-size: 12px; color: var(--muted); margin-top: 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .board-head { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: .04em; cursor: default; padding-top: 0; }
    .pct { font-size: 13px; text-align: right; font-variant-numeric: tabular-nums; }
    .pct.up { color: var(--good); } .pct.down { color: var(--bad); } .pct.flat { color: var(--muted); }
    details summary { cursor: pointer; color: var(--muted); font-size: 14px; padding: 6px 2px; }
    .controls { display: flex; align-items: center; gap: 8px; margin: 12px 0 6px; }
    select { font-size: 16px; padding: 10px 12px; border-radius: 8px; border: 1px solid var(--line);
      background: var(--card); flex: 1; min-width: 0; }
    .summary { color: var(--muted); font-size: 13px; margin: 0 2px 10px; }
    .range-buttons { display: flex; gap: 6px; margin-bottom: 10px; }
    .range-buttons button { flex: 1; padding: 7px 0; font-size: 13px; border: 1px solid var(--line);
      background: var(--card); border-radius: 6px; color: var(--muted); }
    .range-buttons button.active { background: var(--accent); border-color: var(--accent); color: #fff; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; font-variant-numeric: tabular-nums; }
    th, td { text-align: left; padding: 6px 4px; border-bottom: 1px solid var(--line); vertical-align: top; }
    th { color: var(--muted); font-weight: 600; font-size: 12px; }
    .set { display: inline-block; margin: 0 6px 2px 0; }
    .set.extra { color: var(--muted); }
    .rpe { color: var(--muted); font-size: 11px; }
    .vol-row { display: grid; grid-template-columns: 92px 1fr 70px; gap: 10px; align-items: center; padding: 8px 0;
      border-bottom: 1px solid var(--line); }
    .vol-row:last-child { border-bottom: 0; }
    .vol-name { font-size: 13px; font-weight: 600; }
    .track { position: relative; height: 14px; background: var(--neutral-bg); border-radius: 7px; }
    .band { position: absolute; top: 0; bottom: 0; background: var(--good-bg); border-radius: 7px; }
    .marker { position: absolute; top: -3px; width: 4px; height: 20px; background: var(--accent); border-radius: 2px; margin-left: -2px; }
    .vol-num { font-size: 12px; text-align: right; color: var(--muted); }
    .vol-num b { color: var(--text); font-size: 14px; }
    .legend { font-size: 12px; color: var(--muted); margin: 4px 0 8px; }
    .legend span { display: inline-block; width: 10px; height: 10px; border-radius: 2px; vertical-align: -1px; margin-right: 4px; }
    .empty { color: var(--muted); font-size: 14px; padding: 16px 4px; }
    @media (max-width: 480px) {
      .board-row { grid-template-columns: minmax(0, 1fr) 64px 56px; }
      .board-row .c12 { display: none; }
      .vol-row { grid-template-columns: 80px 1fr 60px; }
    }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div class="asof" id="asof"></div>
      <nav class="tabs" id="tabs">
        <button data-view="next" class="active">Next</button>
        <button data-view="board">Progress</button>
        <button data-view="exercise">Exercise</button>
        <button data-view="volume">Volume</button>
      </nav>
    </header>

    <section class="view active" id="view-next">
      <div class="pills" id="workout-pills"></div>
      <div id="next-list"></div>
    </section>

    <section class="view" id="view-board">
      <div class="card" id="board-active"></div>
      <details id="board-archived-wrap"><summary id="board-archived-label"></summary>
        <div class="card" id="board-archived"></div>
      </details>
    </section>

    <section class="view" id="view-exercise">
      <div class="controls">
        <label for="exercise-select">Exercise:</label>
        <select id="exercise-select"></select>
      </div>
      <div class="summary" id="summary"></div>
      <div class="card" id="exercise-next"></div>
      <div class="range-buttons" id="range-buttons">
        <button data-months="1">1M</button>
        <button data-months="3">3M</button>
        <button data-months="6">6M</button>
        <button data-months="12" class="active">1Y</button>
        <button data-months="0">All</button>
      </div>
      <div class="card"><h3 id="trend-title">Strength trend (Est. 1RM, lb)</h3><div id="chart-trend"></div></div>
      <div class="card"><h3>Reps at working weight</h3>
        <div class="meta">Total working reps per session. Colour changes when the weight changes, so rep gains at the same weight show as rising bars.</div>
        <div id="chart-reps"></div></div>
      <div class="card"><h3>Rep records</h3><div id="records"></div></div>
      <div class="card"><h3>Recent sessions</h3><div id="recent"></div></div>
    </section>

    <section class="view" id="view-volume">
      <div class="card">
        <h3>Hard sets per muscle per week</h3>
        <div class="legend"><span style="background: var(--good-bg)"></span>approx. productive range (RP guideline)
          &nbsp; <span style="background: var(--accent)"></span>your 4-week average</div>
        <div id="volume-rows"></div>
      </div>
      <div class="card"><h3>Weekly sets, last 12 weeks</h3><div id="chart-volume"></div></div>
      <div class="meta" id="volume-unmapped"></div>
    </section>
  </div>
  <script>
    const DATA = __DATA__;
    const exerciseNames = DATA.exercise_names;
    const chartData = DATA.exercises;
    const STATUS_ORDER = DATA.status_order;
    const PURPLE = '#7c3aed';
    const WEIGHT_COLORS = ['#7c3aed', '#0d9488', '#db2777', '#2563eb', '#d97706', '#4f46e5'];
    const MUSCLE_COLORS = ['#7c3aed', '#2563eb', '#0891b2', '#0d9488', '#16a34a', '#65a30d',
      '#ca8a04', '#d97706', '#dc2626', '#db2777', '#9333ea', '#64748b', '#94a3b8'];
    const CONFIG = { displayModeBar: false, responsive: true };

    function el(tag, cls, text) {
      const node = document.createElement(tag);
      if (cls) node.className = cls;
      if (text !== undefined && text !== null) node.textContent = text;
      return node;
    }
    function fmt(w) { return (Math.round(w * 10) / 10).toString(); }
    function fmtDate(d) {
      const dt = new Date(d + 'T00:00:00');
      return dt.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
    }
    function setsText(session, workingOnly) {
      return session.sets.filter(s => !workingOnly || s[4])
        .map(s => fmt(s[0]) + '×' + s[1] + (s[2] !== null ? ' @' + s[2] : '')).join(', ');
    }
    function chip(status) { return el('span', 'chip ' + status, status); }

    document.getElementById('asof').textContent = 'Updated ' + fmtDate(DATA.as_of);

    // ---- Tabs ----
    const tabButtons = document.querySelectorAll('#tabs button');
    function showView(name) {
      tabButtons.forEach(b => b.classList.toggle('active', b.dataset.view === name));
      document.querySelectorAll('.view').forEach(v => v.classList.toggle('active', v.id === 'view-' + name));
      if (name === 'exercise') renderCharts();
      if (name === 'volume') renderVolumeChart();
      window.scrollTo(0, 0);
    }
    tabButtons.forEach(b => b.addEventListener('click', () => showView(b.dataset.view)));
    function openExercise(name) {
      select.value = name;
      showView('exercise');
    }

    // ---- Next workout ----
    function prescriptionBlock(name, data, compact) {
      const wrap = el('div');
      const p = data.prescription;
      if (!p) {
        wrap.appendChild(el('div', 'meta', 'Not trained recently — no recommendation.'));
        return wrap;
      }
      const rx = el('div', 'rx', p.text);
      const labels = { increase: 'move up', hold: 'hold', 'add-reps': 'add reps', deload: 'deload',
        'drop-back': 'drop back', 'return': 'ease back', 'add-load': 'add load' };
      rx.appendChild(el('span', 'action', labels[p.action] || p.action));
      wrap.appendChild(rx);
      wrap.appendChild(el('div', 'reason', p.reason));
      const last = data.sessions[data.sessions.length - 1];
      wrap.appendChild(el('div', 'meta',
        'Last: ' + setsText(last, false) + ' · ' + fmtDate(last.date) +
        ' · Range ' + data.rep_range[0] + '–' + data.rep_range[1] + ' · Steps ' + data.step));
      return wrap;
    }

    function renderNext() {
      const pills = document.getElementById('workout-pills');
      const list = document.getElementById('next-list');
      if (!DATA.workouts.length) {
        list.appendChild(el('div', 'empty', 'No workouts in the last 60 days.'));
        return;
      }
      let current = DATA.next_workout || DATA.workouts[0].name;
      function draw() {
        pills.innerHTML = '';
        DATA.workouts.forEach(w => {
          const b = el('button', w.name === current ? 'active' : '', w.name);
          if (w.name === DATA.next_workout) b.appendChild(el('span', 'tag', 'up next'));
          b.addEventListener('click', () => { current = w.name; draw(); });
          pills.appendChild(b);
        });
        list.innerHTML = '';
        const plan = DATA.workouts.find(w => w.name === current);
        list.appendChild(el('div', 'meta', 'Based on your last ' + plan.name + ' session (' + fmtDate(plan.last_date) + ')'));
        list.lastChild.style.margin = '0 2px 8px';
        plan.exercises.forEach(name => {
          const data = chartData[name];
          if (!data) return;
          const card = el('div', 'card');
          const head = el('div', 'row-head');
          const title = el('span', 'ex-name', name);
          title.addEventListener('click', () => openExercise(name));
          head.appendChild(title);
          head.appendChild(chip(data.status));
          card.appendChild(head);
          card.appendChild(prescriptionBlock(name, data));
          list.appendChild(card);
        });
      }
      draw();
    }

    // ---- Progress board ----
    function sparkline(values) {
      const w = 64, h = 26, pad = 3;
      const ns = 'http://www.w3.org/2000/svg';
      const svg = document.createElementNS(ns, 'svg');
      svg.setAttribute('width', w); svg.setAttribute('height', h);
      svg.setAttribute('viewBox', '0 0 ' + w + ' ' + h);
      if (values.length < 2) return svg;
      const min = Math.min(...values), max = Math.max(...values);
      const span = max - min || 1;
      const pts = values.map((v, i) => [pad + i * (w - 2 * pad) / (values.length - 1), h - pad - (v - min) * (h - 2 * pad) / span]);
      const path = document.createElementNS(ns, 'polyline');
      path.setAttribute('points', pts.map(p => p.join(',')).join(' '));
      path.setAttribute('fill', 'none'); path.setAttribute('stroke', PURPLE); path.setAttribute('stroke-width', '1.5');
      svg.appendChild(path);
      const dot = document.createElementNS(ns, 'circle');
      const last = pts[pts.length - 1];
      dot.setAttribute('cx', last[0]); dot.setAttribute('cy', last[1]); dot.setAttribute('r', 2.5); dot.setAttribute('fill', PURPLE);
      svg.appendChild(dot);
      return svg;
    }
    function pctCell(value, cls) {
      const node = el('div', 'pct ' + (cls || ''));
      if (value === null || value === undefined) { node.textContent = '–'; node.classList.add('flat'); return node; }
      node.textContent = (value > 0 ? '+' : '') + value.toFixed(1) + '%';
      node.classList.add(value >= 1 ? 'up' : value <= -1 ? 'down' : 'flat');
      return node;
    }
    function recentScores(data) {
      const cutoff = new Date(DATA.as_of + 'T00:00:00');
      cutoff.setDate(cutoff.getDate() - 84);
      const iso = cutoff.toISOString().slice(0, 10);
      let s = data.sessions.filter(x => x.date >= iso);
      if (s.length < 2) s = data.sessions.slice(-6);
      return s.map(x => data.kind === 'assisted' ? -x.weight : x.score);
    }
    function boardRow(name) {
      const data = chartData[name];
      const row = el('div', 'board-row');
      const left = el('div');
      const top = el('div', 'name', name);
      left.appendChild(top);
      const sub = el('div', 'sub');
      sub.appendChild(chip(data.status));
      sub.appendChild(document.createTextNode(' ' + (data.prescription ? 'Next: ' + data.prescription.text : data.status_reason)));
      left.appendChild(sub);
      row.appendChild(left);
      row.appendChild(sparkline(recentScores(data)));
      row.appendChild(pctCell(data.change_4w));
      row.appendChild(pctCell(data.change_12w, 'c12'));
      row.addEventListener('click', () => openExercise(name));
      return row;
    }
    function renderBoard() {
      const active = exerciseNames.filter(n => chartData[n].status !== 'Archived');
      const archived = exerciseNames.filter(n => chartData[n].status === 'Archived');
      active.sort((a, b) => STATUS_ORDER.indexOf(chartData[a].status) - STATUS_ORDER.indexOf(chartData[b].status));
      const root = document.getElementById('board-active');
      const head = el('div', 'board-row board-head');
      ['Exercise', '12 weeks', '4 wk', '12 wk'].forEach((t, i) => {
        const c = el('div', i >= 2 ? 'pct' + (i === 3 ? ' c12' : '') : '', t);
        head.appendChild(c);
      });
      root.appendChild(head);
      if (!active.length) root.appendChild(el('div', 'empty', 'Nothing trained in the last 60 days.'));
      active.forEach(n => root.appendChild(boardRow(n)));
      document.getElementById('board-archived-label').textContent = 'Archived — not trained in 60+ days (' + archived.length + ')';
      const arch = document.getElementById('board-archived');
      archived.forEach(n => arch.appendChild(boardRow(n)));
      if (!archived.length) document.getElementById('board-archived-wrap').style.display = 'none';
    }

    // ---- Exercise detail ----
    const select = document.getElementById('exercise-select');
    (function buildSelect() {
      const active = el('optgroup'); active.label = 'Active';
      const archived = el('optgroup'); archived.label = 'Archived';
      exerciseNames.forEach(name => {
        const opt = el('option', null, name);
        opt.value = name;
        (chartData[name].status === 'Archived' ? archived : active).appendChild(opt);
      });
      if (active.children.length) select.appendChild(active);
      if (archived.children.length) select.appendChild(archived);
    })();
    select.addEventListener('change', renderCharts);

    let currentMonths = 12;
    const rangeButtons = document.querySelectorAll('#range-buttons button');
    rangeButtons.forEach(btn => btn.addEventListener('click', () => {
      rangeButtons.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      currentMonths = parseInt(btn.dataset.months, 10);
      renderCharts();
    }));
    function rangeCutoff() {
      if (!currentMonths) return null;
      const dt = new Date(DATA.as_of + 'T00:00:00');
      dt.setMonth(dt.getMonth() - currentMonths);
      return dt.toISOString().slice(0, 10);
    }
    function baseLayout(extra) {
      return Object.assign({
        height: 240, margin: { t: 8, b: 32, l: 46, r: 10 }, showlegend: false,
        xaxis: { fixedrange: true, tickfont: { size: 11 }, gridcolor: '#eee', type: 'date' },
        yaxis: { fixedrange: true, tickfont: { size: 11 }, gridcolor: '#eee' },
        plot_bgcolor: '#fff', paper_bgcolor: '#fff', bargap: 0.25
      }, extra || {});
    }
    function rolling(values, n) {
      return values.map((_, i) => {
        const win = values.slice(Math.max(0, i - n + 1), i + 1);
        return win.reduce((a, b) => a + b, 0) / win.length;
      });
    }

    function renderTrend(data, sessions) {
      const x = sessions.map(s => s.date);
      const hover = sessions.map(s => setsText(s, true));
      let traces, layout;
      if (data.kind === 'assisted') {
        document.getElementById('trend-title').textContent = 'Assistance (lb, lower is better)';
        traces = [{ x: x, y: sessions.map(s => s.weight), mode: 'lines+markers', line: { color: PURPLE, width: 2, shape: 'hv' },
          marker: { size: 6, color: PURPLE }, text: hover, hovertemplate: '%{x|%b %d, %Y}<br>%{text}<extra></extra>' }];
        layout = baseLayout({ yaxis: { fixedrange: true, autorange: 'reversed', tickfont: { size: 11 }, gridcolor: '#eee' } });
      } else {
        document.getElementById('trend-title').textContent = data.kind === 'bodyweight'
          ? 'Strength trend (relative score)' : 'Strength trend (Est. 1RM, lb)';
        const y = sessions.map(s => s.score);
        const prs = sessions.filter(s => s.pr);
        traces = [
          { x: x, y: y, mode: 'markers', marker: { size: 6, color: PURPLE, opacity: 0.55 }, text: hover,
            hovertemplate: '%{x|%b %d, %Y}<br>Est. 1RM %{y:.0f}<br>%{text}<extra></extra>' },
          { x: x, y: rolling(y, 5), mode: 'lines', line: { color: PURPLE, width: 2.5, shape: 'spline' }, hoverinfo: 'skip' },
          { x: prs.map(s => s.date), y: prs.map(s => s.score), mode: 'markers',
            marker: { symbol: 'star', size: 11, color: '#d97706' }, hovertemplate: 'PR %{y:.0f}<extra></extra>' }
        ];
        layout = baseLayout();
      }
      Plotly.react('chart-trend', traces, layout, CONFIG);
    }

    function renderReps(data, sessions) {
      const weights = [];
      sessions.forEach(s => { if (!weights.includes(s.weight)) weights.push(s.weight); });
      let band = -1, prev = null;
      const colors = sessions.map(s => {
        if (s.weight !== prev) { band += 1; prev = s.weight; }
        return WEIGHT_COLORS[band % WEIGHT_COLORS.length];
      });
      const trace = {
        x: sessions.map(s => s.date), y: sessions.map(s => s.total), type: 'bar',
        marker: { color: colors },
        text: sessions.map(s => fmt(s.weight)), textposition: 'inside', insidetextanchor: 'start',
        textfont: { color: '#fff', size: 10 },
        customdata: sessions.map(s => setsText(s, true)),
        hovertemplate: '%{x|%b %d, %Y}<br>%{customdata}<br>%{y} reps<extra></extra>'
      };
      Plotly.react('chart-reps', [trace], baseLayout(), CONFIG);
    }

    function renderRecords(data) {
      const root = document.getElementById('records');
      root.innerHTML = '';
      if (!data.records.length) { root.appendChild(el('div', 'empty', 'No records yet.')); return; }
      const table = el('table');
      const head = el('tr');
      ['Reps', data.kind === 'assisted' ? 'Least assistance' : 'Best weight', 'Date'].forEach(t => head.appendChild(el('th', null, t)));
      table.appendChild(head);
      data.records.forEach(r => {
        const tr = el('tr');
        tr.appendChild(el('td', null, r.reps + '+'));
        tr.appendChild(el('td', null, fmt(r.weight) + ' lb × ' + r.actual_reps));
        tr.appendChild(el('td', null, fmtDate(r.date)));
        table.appendChild(tr);
      });
      root.appendChild(table);
    }

    function renderRecent(data) {
      const root = document.getElementById('recent');
      root.innerHTML = '';
      const table = el('table');
      const head = el('tr');
      ['Date', 'Sets (weight × reps @RPE)'].forEach(t => head.appendChild(el('th', null, t)));
      table.appendChild(head);
      data.sessions.slice(-6).reverse().forEach(s => {
        const tr = el('tr');
        tr.appendChild(el('td', null, fmtDate(s.date)));
        const td = el('td');
        s.sets.forEach(set => {
          const span = el('span', 'set' + (set[4] ? '' : ' extra'), fmt(set[0]) + '×' + set[1]);
          if (set[2] !== null) span.appendChild(el('span', 'rpe', ' @' + set[2]));
          if (set[3] !== 'normal') span.appendChild(el('span', 'rpe', ' ' + set[3]));
          td.appendChild(span);
        });
        tr.appendChild(td);
        table.appendChild(tr);
      });
      root.appendChild(table);
    }

    function renderCharts() {
      const data = chartData[select.value];
      if (!data) return;
      document.getElementById('summary').textContent = data.summary || '';
      const next = document.getElementById('exercise-next');
      next.innerHTML = '';
      next.appendChild(el('h3', null, 'Next session'));
      next.appendChild(prescriptionBlock(select.value, data));
      const cutoff = rangeCutoff();
      let sessions = data.sessions;
      if (cutoff) sessions = sessions.filter(s => s.date >= cutoff);
      if (!document.getElementById('view-exercise').classList.contains('active')) return;
      renderTrend(data, sessions);
      renderReps(data, sessions);
      renderRecords(data);
      renderRecent(data);
    }

    // ---- Volume ----
    function renderVolumeRows() {
      const v = DATA.volume;
      const root = document.getElementById('volume-rows');
      if (!v.muscles.length) { root.appendChild(el('div', 'empty', 'No sets in the last 12 weeks.')); return; }
      // Average over the last 4 complete weeks (exclude the current, partial week).
      const n = v.weeks.length;
      const scaleMax = Math.max(24, ...v.muscles.map(m => Math.max(...v.sets[m]))) * 1.05;
      v.muscles.forEach(m => {
        const full = v.sets[m].slice(Math.max(0, n - 5), n - 1);
        const avg = full.length ? full.reduce((a, b) => a + b, 0) / full.length : 0;
        const row = el('div', 'vol-row');
        row.appendChild(el('div', 'vol-name', m));
        const track = el('div', 'track');
        const t = v.targets[m];
        if (t) {
          const band = el('div', 'band');
          band.style.left = (t[0] / scaleMax * 100) + '%';
          band.style.width = ((t[1] - t[0]) / scaleMax * 100) + '%';
          track.appendChild(band);
        }
        const marker = el('div', 'marker');
        marker.style.left = Math.min(100, avg / scaleMax * 100) + '%';
        track.appendChild(marker);
        row.appendChild(track);
        const num = el('div', 'vol-num');
        num.appendChild(el('b', null, avg.toFixed(1)));
        num.appendChild(document.createTextNode(' /wk'));
        num.appendChild(el('div', null, 'this wk ' + v.sets[m][n - 1]));
        row.appendChild(num);
        root.appendChild(row);
      });
      if (v.unmapped.length) {
        document.getElementById('volume-unmapped').textContent = 'Counted as "Other": ' + v.unmapped.join(', ');
      }
    }
    function renderVolumeChart() {
      const v = DATA.volume;
      if (!v.muscles.length) return;
      const traces = v.muscles.map((m, i) => ({
        x: v.weeks, y: v.sets[m], name: m, type: 'bar',
        marker: { color: MUSCLE_COLORS[i % MUSCLE_COLORS.length] },
        hovertemplate: m + ': %{y} sets<extra>week of %{x|%b %d}</extra>'
      }));
      Plotly.react('chart-volume', traces, baseLayout({
        height: 300, barmode: 'stack', showlegend: true,
        legend: { orientation: 'h', y: -0.2, font: { size: 11 } }, margin: { t: 8, b: 70, l: 36, r: 10 }
      }), CONFIG);
    }

    renderNext();
    renderBoard();
    renderVolumeRows();
    if (exerciseNames.length > 0) {
      select.value = exerciseNames.find(n => chartData[n].status !== 'Archived') || exerciseNames[0];
      renderCharts();
    }
    if (DATA.single_exercise) openExercise(exerciseNames[0]);
  </script>
</body>
</html>"""


def _json_default(obj: object) -> object:
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    if hasattr(obj, "__float__"):
        return float(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _escape(payload: object) -> str:
    """Serialize JSON for safe embedding inside a <script> tag."""
    return (
        json.dumps(payload, default=_json_default)
        .replace("</", "<\\/")
        .replace("<!--", "<\\!--")
    )


def _build_page_data(
    connection: sqlite3.Connection,
    analyses: dict[str, ExerciseAnalysis],
    as_of: date,
    single_exercise: bool = False,
) -> dict[str, object]:
    plans, next_workout = plan_workouts(connection, analyses, as_of)
    # exercise_names comes first so the most-recent-first order appears first in the page.
    return {
        "exercise_names": list(analyses.keys()),
        "exercises": {name: _exercise_payload(a) for name, a in analyses.items()},
        "as_of": as_of.isoformat(),
        "status_order": list(STATUS_ORDER),
        "workouts": [
            {"name": p.name, "last_date": p.last_date, "exercises": p.exercises} for p in plans
        ],
        "next_workout": next_workout,
        "volume": weekly_muscle_volume(analyses, as_of),
        "single_exercise": single_exercise,
    }


def _write_page(page_data: dict[str, object], output_path: str) -> None:
    html_content = _PAGE_TEMPLATE.replace("__DATA__", _escape(page_data))
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(html_content, encoding="utf-8")


def generate_exercise_progress_chart(
    connection: sqlite3.Connection,
    exercise_name: str,
    output_path: str,
    start_date: str | None = None,
    end_date: str | None = None,
    config: ProgressionConfig | None = None,
    as_of: date | None = None,
) -> int:
    """Write a dashboard page focused on one exercise. Returns its session count."""
    as_of = as_of or date.today()
    analyses = analyze_all(connection, config, as_of, start_date, end_date)
    if exercise_name not in analyses:
        raise ValueError(f"No data found for exercise: {exercise_name}")
    focused = {exercise_name: analyses[exercise_name]}
    _write_page(_build_page_data(connection, focused, as_of, single_exercise=True), output_path)
    return len(focused[exercise_name].sessions)


def generate_all_exercises_page(
    connection: sqlite3.Connection,
    output_path: str,
    start_date: str | None = None,
    end_date: str | None = None,
    config: ProgressionConfig | None = None,
    as_of: date | None = None,
) -> int:
    """Write the full dashboard (next workout, progress board, exercise detail, volume).

    Exercises are ordered by most recent workout first. Returns the exercise count.
    """
    as_of = as_of or date.today()
    analyses = analyze_all(connection, config, as_of, start_date, end_date)
    if not analyses:
        raise ValueError("No exercise data found for the selected date range")
    _write_page(_build_page_data(connection, analyses, as_of), output_path)
    return len(analyses)

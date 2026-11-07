"""The fridge tablet page (/fridge): four full screens to swipe, for an always-on landscape tablet.
Served by panel.py (deployed side by side); its data comes from /api/fridge, /api/status and the cameras.
"""
import json

TEXT = {
    "en": {
        "title": "Home", "names": {"casa": "Home", "calendario": "Calendar", "camaras": "Cameras", "estado": "Status"},
        "left_today": "What's left today", "now": "NOW", "until": "until {t}", "until_short": "until {t}",
        "all_day": "all day", "nothing": "Nothing else today", "stale": "no connection to the calendar",
        "more": "+{n} more", "today": "Today", "week": "This week", "playing": "Playing on Spotify", "on_device": "on {d}",
    },
    "es": {
        "title": "Casa", "names": {"casa": "Casa", "calendario": "Calendario", "camaras": "Cámaras", "estado": "Estado"},
        "left_today": "Lo que queda de hoy", "now": "AHORA", "until": "hasta las {t}", "until_short": "hasta {t}",
        "all_day": "todo el día", "nothing": "Nada más por hoy", "stale": "sin conexión con el calendario",
        "more": "+{n} más", "today": "Hoy", "week": "Esta semana", "playing": "Sonando en Spotify", "on_device": "en {d}",
    },
}

FRIDGE_PAGE = r"""<!doctype html>
<html lang="__LANG__">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  :root { --bg:#05070b; --ink:#dfe8f5; --muted:#6f7d92; --glow:#5ee1ff; --now:#7cf5b0; --edge:#1a2433; --all:#c49bff; }
  * { box-sizing:border-box; }
  [hidden] { display:none !important; }
  html, body { margin:0; height:100%; background:var(--bg); color:var(--ink); overflow:hidden;
               font-family:system-ui, "Segoe UI", Roboto, sans-serif; -webkit-user-select:none; user-select:none; }
  body { background:radial-gradient(ellipse at 30% 20%, #0b1626 0%, var(--bg) 60%); }
  #wrap { position:fixed; inset:0; transition:transform 2s ease, filter 3s ease; }
  body.dim #wrap { filter:brightness(.35); }
  #strip { display:flex; height:100%; overflow-x:auto; overflow-y:hidden; scroll-snap-type:x mandatory;
           scrollbar-width:none; overscroll-behavior:contain; }
  #strip::-webkit-scrollbar { display:none; }
  .screen { flex:0 0 100%; height:100%; scroll-snap-align:start; scroll-snap-stop:always; position:relative;
            padding:30px 48px 50px; display:flex; flex-direction:column; min-width:0; }
  .head { display:flex; justify-content:space-between; align-items:baseline; margin-bottom:14px; }
  .head .clock { font-size:40px; font-weight:200; color:#eaf6ff; text-shadow:0 0 14px #5ee1ff44; font-variant-numeric:tabular-nums; }
  .colon { color:var(--glow); opacity:.8; }
  .label { color:var(--glow); text-transform:uppercase; letter-spacing:4px; font-size:13px; opacity:.85; }
  .quiet { color:var(--muted); font-size:13px; letter-spacing:1px; }
  .q { color:var(--muted); font-size:.8em; margin-left:4px; }
  .more { color:var(--muted); font-size:13px; padding-top:4px; }
  .dots { position:absolute; bottom:14px; left:0; right:0; display:flex; justify-content:center; gap:10px;
          color:var(--muted); font-size:12px; letter-spacing:2px; text-transform:uppercase; }
  .dots span { padding:6px 8px; cursor:pointer; }
  .dots span::before { content:""; display:inline-block; width:7px; height:7px; border-radius:50%; background:#2a3546;
                       margin-right:7px; vertical-align:middle; }
  .dots span.on { color:var(--ink); }
  .dots span.on::before { background:var(--glow); box-shadow:0 0 8px var(--glow); }

  /* Casa: clock on the left, what's left of today on the right, what's playing at the bottom */
  #casa { padding-top:36px; }
  #casa .top { display:flex; gap:44px; align-items:center; flex:1; min-height:0; }
  .time { font-weight:200; font-variant-numeric:tabular-nums; letter-spacing:-2px; line-height:1;
          text-shadow:0 0 24px #5ee1ff55; color:#eaf6ff; font-size:160px; }
  .date { color:var(--muted); text-transform:uppercase; letter-spacing:6px; font-size:20px; margin-top:14px; }
  #casa .right { flex:1; align-self:stretch; border-left:1px solid var(--edge); padding-left:36px; min-width:0;
                 display:flex; flex-direction:column; justify-content:center; }
  #today { min-height:0; overflow:hidden; margin-top:6px; }
  .ev { display:flex; gap:18px; align-items:baseline; padding:9px 0 9px 12px; border-top:1px solid var(--edge);
        border-left:3px solid var(--glow); }
  .ev .h { font-variant-numeric:tabular-nums; color:var(--glow); font-size:19px; min-width:70px; font-weight:300; flex:none; }
  .ev .t { font-size:19px; font-weight:300; }
  .ev .w { color:var(--muted); font-size:15px; margin-top:2px; }
  .ev.all .h { color:var(--all); font-size:13px; letter-spacing:1px; }
  .ev.now .h { color:var(--now); }
  .tag { color:var(--now); border:1px solid #7cf5b066; border-radius:20px; font-size:11px; letter-spacing:2px;
         padding:2px 8px; margin-left:8px; vertical-align:middle; }
  #casa.empty .top { flex-direction:column; justify-content:center; gap:0; }
  #casa.empty .right { display:none; }
  #casa.empty .left { text-align:center; }
  #casa.empty .time { font-size:220px; }
  #casa .nothing { color:var(--muted); margin-top:26px; font-size:18px; letter-spacing:2px; text-align:center; }
  .play { display:flex; gap:20px; align-items:center; border:1px solid var(--edge); border-radius:18px; padding:14px 18px;
          margin-top:12px; background:linear-gradient(90deg, #0e1a2a, #0a0f18); }
  .cover { width:74px; height:74px; border-radius:10px; flex:none; object-fit:cover;
           background:linear-gradient(135deg,#ff5f9e,#7c5cff 55%,#2bd9ff); box-shadow:0 0 18px #7c5cff55; }
  .play .mid { flex:1; min-width:0; }
  .play .src { color:#1ed760; font-size:12px; letter-spacing:3px; text-transform:uppercase; }
  .play .song { font-size:22px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .play .art { color:var(--muted); font-size:16px; margin-top:2px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .bar { height:3px; background:#1f2a3a; border-radius:3px; margin-top:10px; position:relative; }
  .bar i { position:absolute; left:0; top:0; bottom:0; width:0; background:var(--glow); border-radius:3px; box-shadow:0 0 8px var(--glow); }
  .play .where { color:var(--muted); font-size:14px; text-align:right; max-width:200px; font-variant-numeric:tabular-nums; }

  /* Calendario: today and the next six days */
  #week { display:grid; grid-template-columns:repeat(7, 1fr); gap:10px; flex:1; min-height:0; }
  .col { border:1px solid var(--edge); border-radius:14px; padding:10px 9px; background:#0a111c88; min-width:0;
         display:flex; flex-direction:column; min-height:0; }
  .col.today { border-color:#5ee1ff77; box-shadow:0 0 16px #5ee1ff22 inset; }
  .col .dn { color:var(--muted); font-size:12px; letter-spacing:2px; text-transform:uppercase; white-space:nowrap; }
  .col .dd { font-size:28px; font-weight:200; margin-bottom:4px; }
  .col.today .dn, .col.today .dd { color:var(--glow); }
  .its { flex:1; min-height:0; overflow:hidden; }
  .it { border-left:2px solid var(--glow); padding:3px 0 3px 7px; margin:7px 0; font-size:14px; line-height:1.25;
        overflow:hidden; overflow-wrap:anywhere; }
  .it b { display:block; font-weight:400; color:var(--glow); font-size:12px; font-variant-numeric:tabular-nums; }
  .it.all b { color:var(--all); }
  .it.past { opacity:.35; }
  .none { color:#3a4658; font-size:13px; }
</style>
</head>
<body>
<div id="wrap">
<main id="strip">
  <section class="screen" id="casa">
    <div class="top">
      <div class="left"><div class="time" id="bigclock"></div><div class="date" id="date"></div>
        <div class="nothing" id="nothing" hidden></div></div>
      <div class="right"><div class="label" id="left-today"></div><div id="today"></div>
        <div class="quiet stale" hidden></div></div>
    </div>
    <div class="play" id="play" hidden></div>
  </section>
  <section class="screen" id="calendario">
    <div class="head"><div><span class="label" id="week-label"></span> <span class="quiet stale" hidden></span></div>
      <div class="clock"></div></div>
    <div id="week"></div>
  </section>
  <section class="screen" id="camaras">
    <div class="head"><div class="label" data-name="camaras"></div><div class="clock"></div></div>
  </section>
  <section class="screen" id="estado">
    <div class="head"><div class="label" data-name="estado"></div><div class="clock"></div></div>
  </section>
</main>
<nav class="dots" id="dots"></nav>
</div>
<script>
const T = __TEXT__;
const LANG = document.documentElement.lang;
const $ = (s, el = document) => el.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'})[c]);
const fmt = (s, v) => s.replace(/\{(\w+)\}/g, (_, k) => v[k]);
const pad = n => String(n).padStart(2, '0');
const hm = d => pad(d.getHours()) + ':' + pad(d.getMinutes());
const dkey = d => d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
const midnight = d => new Date(d.getFullYear(), d.getMonth(), d.getDate());
const addDays = (d, n) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
const clockHTML = d => pad(d.getHours()) + '<span class="colon">:</span>' + pad(d.getMinutes());
const mss = ms => { const s = Math.floor(ms / 1000); return Math.floor(s / 60) + ':' + pad(s % 60); };
// event times come as local "YYYY-MM-DD" (all day) or "YYYY-MM-DDTHH:MM"
const parse = s => new Date(+s.slice(0, 4), +s.slice(5, 7) - 1, +s.slice(8, 10), +(s.slice(11, 13) || 0), +(s.slice(14, 16) || 0));

let data = {agenda: {calendars: [], events: [], stale: false}, playing: null, settings: {dim: '00:00-07:00', back_s: 120}};
let gotAt = Date.now();

// --- Screens: swipe sideways (scroll snap), dots, hooks for the screen that is showing ---
const strip = $('#strip');
let screens = [];
let current = null;
const hooks = {show: {}, hide: {}};
const onShow = (id, fn) => (hooks.show[id] ||= []).push(fn);
const onHide = (id, fn) => (hooks.hide[id] ||= []).push(fn);
function setCurrent(id) {
  if (id === current) return;
  const old = current;
  current = id;
  if (old) for (const fn of hooks.hide[old] || []) fn();
  for (const fn of hooks.show[id] || []) fn();
  for (const d of $('#dots').children) d.classList.toggle('on', d.dataset.s === id);
}
const go = id => { const s = document.getElementById(id); if (s) strip.scrollTo({left: s.offsetLeft, behavior: 'smooth'}); };
const seen = new IntersectionObserver(entries => {
  for (const e of entries) if (e.isIntersecting) setCurrent(e.target.id);
}, {root: strip, threshold: 0.6});
function buildScreens() {
  screens = [...strip.children].map(s => s.id);
  $('#dots').innerHTML = screens.map(id => `<span data-s="${id}"${id === current ? ' class="on"' : ''}>${esc(T.names[id])}</span>`).join('');
  for (const d of $('#dots').children) d.onclick = () => go(d.dataset.s);
  for (const s of strip.children) seen.observe(s);
}
function dropScreen(id) {  // e.g. no cameras: the screen and its dot go
  const s = document.getElementById(id);
  if (!s) return;
  seen.unobserve(s);
  s.remove();
  buildScreens();
}
for (const el of document.querySelectorAll('[data-name]')) el.textContent = T.names[el.dataset.name];
$('#left-today').textContent = T.left_today;
$('#week-label').textContent = T.week;
$('#nothing').textContent = T.nothing;
for (const el of document.querySelectorAll('.stale')) el.textContent = T.stale;
buildScreens();

// back to the first screen after a while untouched
let touched = Date.now();
for (const name of ['pointerdown', 'touchstart', 'keydown']) addEventListener(name, () => { touched = Date.now(); }, {passive: true});
strip.addEventListener('scroll', () => { touched = Date.now(); }, {passive: true});
setInterval(() => {
  if (current && current !== screens[0] && Date.now() - touched > data.settings.back_s * 1000) go(screens[0]);
}, 5000);

// screen care: everything moves a few pixels every 3 minutes, and the page dims at night
const wrap = $('#wrap');
setInterval(() => {
  const r = () => Math.round(Math.random() * 12 - 6);
  wrap.style.transform = `translate(${r()}px, ${r()}px)`;
}, 180000);
function dimNow(d) {
  const m = /^(\d\d):(\d\d)-(\d\d):(\d\d)$/.exec(data.settings.dim || '');
  if (!m) return false;
  const a = +m[1] * 60 + +m[2], b = +m[3] * 60 + +m[4], x = d.getHours() * 60 + d.getMinutes();
  return a < b ? a <= x && x < b : a > b ? x >= a || x < b : false;
}

// --- Events ---
function span(ev) {
  const s = parse(ev.start), e = parse(ev.end);
  return [s, +e > +s ? e : new Date(+s + 60000)];  // an event with no length still lasts a minute
}
const onDay = (ev, day) => { const [s, e] = span(ev); return s < addDays(day, 1) && e > day; };
const allDayFirst = (a, b) => (b.all_day - a.all_day) || (a.start < b.start ? -1 : a.start > b.start ? 1 : 0);
function bar(ev) {  // the event's calendar color(s); colors are #rrggbb, checked by the server
  const c = (ev.cals || []).map(i => (data.agenda.calendars[i] || {}).color).filter(Boolean);
  if (!c.length) return '';
  // several calendars: their colors stacked in the left bar
  return c.length > 1 ? `border-left-color:transparent;background:linear-gradient(${c.join(',')}) 0 0 / 3px 100% no-repeat border-box`
                      : `border-left-color:${c[0]}`;
}
const titleHTML = ev => esc(ev.title) + (ev.unsure ? '<span class="q">?</span>' : '');
function fit(box, sel) {  // more than fits: hide the last ones and say how many
  const over = () => box.scrollHeight > box.clientHeight + 1;
  if (!over()) return;
  const more = document.createElement('div');
  more.className = 'more';
  box.append(more);
  let hidden = 0;
  do {
    const items = box.querySelectorAll(sel);
    if (!items.length) break;
    items[items.length - 1].remove();
    more.textContent = fmt(T.more, {n: ++hidden});
  } while (over());
}
const dayName = d => new Intl.DateTimeFormat(LANG, {weekday: 'short'}).format(d).replace('.', '');

function drawClock(now) {
  $('#bigclock').innerHTML = clockHTML(now);
  $('#date').textContent = new Intl.DateTimeFormat(LANG, {weekday: 'long', day: 'numeric', month: 'long'}).format(now).replace(',', '');
  for (const c of document.querySelectorAll('.head .clock')) c.innerHTML = clockHTML(now);
}

function drawToday(now) {
  const today = midnight(now);
  const left = data.agenda.events.filter(ev => onDay(ev, today) && (ev.all_day || span(ev)[1] > now)).sort(allDayFirst);
  $('#casa').classList.toggle('empty', !left.length);
  $('#nothing').hidden = !!left.length;
  $('#today').innerHTML = left.map(ev => {
    const [s, e] = span(ev);
    const live = !ev.all_day && s <= now && now < e;
    const second = live ? [fmt(T.until, {t: hm(e)}), ev.where].filter(Boolean).join(' · ') : ev.where;
    return `<div class="ev${live ? ' now' : ''}${ev.all_day ? ' all' : ''}" style="${bar(ev)}">` +
      `<div class="h">${ev.all_day ? esc(T.all_day) : hm(s)}</div><div><div class="t">${titleHTML(ev)}` +
      `${live ? `<span class="tag">${esc(T.now)}</span>` : ''}</div>${second ? `<div class="w">${esc(second)}</div>` : ''}</div></div>`;
  }).join('');
  fit($('#today'), '.ev');
  for (const el of document.querySelectorAll('.stale')) el.hidden = !data.agenda.stale;
}

function drawWeek(now) {
  const today = midnight(now);
  $('#week').innerHTML = [0, 1, 2, 3, 4, 5, 6].map(i => {
    const day = addDays(today, i);
    const items = data.agenda.events.filter(ev => onDay(ev, day)).sort(allDayFirst).map(ev => {
      const [s, e] = span(ev);
      const when = ev.all_day ? esc(T.all_day) : s < day ? esc(fmt(T.until_short, {t: hm(e)})) : hm(s);
      const past = i === 0 && !ev.all_day && e <= now;
      return `<div class="it${ev.all_day ? ' all' : ''}${past ? ' past' : ''}" style="${bar(ev)}"><b>${when}</b>${titleHTML(ev)}</div>`;
    }).join('');
    return `<div class="col${i === 0 ? ' today' : ''}"><div class="dn">${i === 0 ? esc(T.today) + ' · ' : ''}${esc(dayName(day))}</div>` +
      `<div class="dd">${day.getDate()}</div><div class="its">${items || '<div class="none">—</div>'}</div></div>`;
  }).join('');
  for (const box of document.querySelectorAll('#week .its')) fit(box, '.it');
}

// --- Now playing ---
let playingKey = '';
function drawPlaying() {
  const p = data.playing, box = $('#play');
  box.hidden = !p;
  if (!p) { playingKey = ''; return; }
  const key = [p.song, p.artist, p.album, p.cover, p.device].join('|');
  if (key !== playingKey) {  // same song: only the progress moves, the cover isn't fetched again
    playingKey = key;
    const cover = /^https:\/\//.test(p.cover || '') ? `<img class="cover" src="${esc(p.cover)}" alt="">` : '<div class="cover"></div>';
    box.innerHTML = cover + `<div class="mid"><div class="src">● ${esc(T.playing)}</div><div class="song">${esc(p.song)}</div>` +
      `<div class="art">${esc([p.artist, p.album].filter(Boolean).join(' · '))}</div><div class="bar"><i></i></div></div>` +
      `<div class="where">${p.device ? esc(fmt(T.on_device, {d: p.device})) + '<br>' : ''}<span class="pos"></span></div>`;
  }
  drawProgress();
}
function drawProgress() {
  const p = data.playing;
  if (!p || !p.duration_ms) return;
  const at = Math.min(p.duration_ms, p.progress_ms + (Date.now() - gotAt));
  $('#play .bar i').style.width = (100 * at / p.duration_ms).toFixed(2) + '%';
  $('#play .pos').textContent = mss(at) + ' / ' + mss(p.duration_ms);
}

// --- Time and data ---
let lastMinute = '';
function drawAll(now) {
  drawClock(now);
  drawToday(now);
  drawWeek(now);
  document.body.classList.toggle('dim', dimNow(now));
}
setInterval(() => {
  const now = new Date();
  const minute = dkey(now) + hm(now);
  if (minute !== lastMinute) { lastMinute = minute; drawAll(now); }  // also moves the week on at midnight
  drawProgress();
}, 1000);

let asking = false;
async function poll() {
  if (asking) return;
  asking = true;
  try {
    const r = await fetch('/api/fridge', {cache: 'no-store'});
    if (r.ok) {
      data = await r.json();
      gotAt = Date.now();
      drawAll(new Date());
      drawPlaying();
    }
  } catch (e) {
    // server restarting or Wi-Fi gone: keep what's on screen, try again later
  } finally {
    asking = false;
  }
}
drawAll(new Date());
poll();
setInterval(poll, 15000);
</script>
</body>
</html>
"""


def render(lang):
    lang = lang if lang in TEXT else "en"
    text = TEXT[lang]
    page = FRIDGE_PAGE.replace("__LANG__", lang).replace("__TITLE__", text["title"])
    # "<" escaped so no text can close the <script> it sits in
    return page.replace("__TEXT__", json.dumps(text).replace("<", "\\u003c")).encode()

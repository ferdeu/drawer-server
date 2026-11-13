"""The fridge tablet page (/fridge): four full screens to swipe, for an always-on landscape tablet.
Served by panel.py (deployed side by side); its data comes from /api/fridge, /api/status and the cameras.
"""
import json

TEXT = {
    "en": {
        "title": "Home", "names": {"casa": "Home", "calendario": "Calendar", "camaras": "Cameras", "estado": "Status"},
        "left_today": "What's left today", "now": "NOW", "until": "until {t}", "until_short": "until {t}",
        "all_day": "all day", "nothing": "Nothing else today", "stale": "no connection to the calendar", "offline": "no connection to the server",
        "more": "+{n} more", "today": "Today", "week": "This week", "playing": "Playing on Spotify", "on_device": "on {d}",
        "live": "LIVE", "home_only": "Home only",
        "k_internet": "Internet", "k_home": "At home", "k_printer": "Printer", "k_server": "Server", "k_disk": "Storage",
        "k_devices": "Devices · {on} of {n} connected", "last_test": "Last test {t}", "alerts": "with alerts",
        "wifi": "Wi-Fi {s}", "cpu": "processor {n}%", "plug_on": "plug on ({lo}–{hi}%)", "plug_off": "plug off ({lo}–{hi}%)",
        "plug_error": "smart plug not answering", "down": "{s} down", "no_battery": "battery not read",
        "free": "GB free", "photos": "photos {gb} GB", "up_to_date": "up to date ✓", "to_go": "{gb} GB to go",
        "backup_near": "photo backup near its limit", "backup_paused": "photo backup paused",
        "ink": {"black": "black", "cyan": "cyan", "magenta": "magenta", "yellow": "yellow",
                "light cyan": "light cyan", "light magenta": "light magenta"},
        "svc": {"SSH": "Remote access", "NextDNS": "Ad blocking", "Luanti": "Kids' game", "Syncthing": "Photo backup",
                "Cameras": "Cameras", "Recorder": "Recorder"},
        "sp_device": "Fridge", "sp_idle": "Nothing playing", "sp_here": "Playing here", "sp_away": "Playing on {d}",
        "sp_paused": "Paused", "sp_resume": "Play «{t}» again", "sp_search": "Find music", "sp_move": "Play here",
        "sp_find": "Song, artist, album or playlist", "sp_recent": "Played lately", "sp_lists": "Your playlists",
        "sp_songs": "Songs", "sp_more": "Artists, albums and playlists", "sp_none": "Nothing found",
        "sp_failed": "Spotify didn't answer", "sp_kind": {"artist": "Artist", "album": "Album", "playlist": "Playlist"},
        "sp_open_app": "Open the Spotify app on this tablet to play here", "sp_no_device": "Spotify can't see «{d}»",
    },
    "es": {
        "title": "Casa", "names": {"casa": "Casa", "calendario": "Calendario", "camaras": "Cámaras", "estado": "Estado"},
        "left_today": "Lo que queda de hoy", "now": "AHORA", "until": "hasta las {t}", "until_short": "hasta {t}",
        "all_day": "todo el día", "nothing": "Nada más por hoy", "stale": "sin conexión con el calendario", "offline": "sin conexión con el server",
        "more": "+{n} más", "today": "Hoy", "week": "Esta semana", "playing": "Sonando en Spotify", "on_device": "en {d}",
        "live": "VIVO", "home_only": "Solo en casa",
        "k_internet": "Internet", "k_home": "En casa", "k_printer": "Impresora", "k_server": "Server", "k_disk": "Disco",
        "k_devices": "Dispositivos · {on} de {n} conectados", "last_test": "Último test {t}", "alerts": "con alertas",
        "wifi": "Wi-Fi {s}", "cpu": "procesador {n}%", "plug_on": "enchufe prendido ({lo}–{hi}%)",
        "plug_off": "enchufe apagado ({lo}–{hi}%)", "plug_error": "el enchufe no contesta", "down": "{s} caído",
        "no_battery": "no leo la batería", "free": "GB libres", "photos": "fotos {gb} GB", "up_to_date": "al día ✓",
        "to_go": "faltan {gb} GB", "backup_near": "backup de fotos cerca del límite",
        "backup_paused": "backup de fotos en pausa",
        "ink": {"black": "negro", "cyan": "cian", "magenta": "magenta", "yellow": "amarillo",
                "light cyan": "cian claro", "light magenta": "magenta claro"},
        "svc": {"SSH": "Acceso remoto", "NextDNS": "Bloqueo de publicidad", "Luanti": "Juego de los chicos",
                "Syncthing": "Backup de fotos", "Cameras": "Cámaras", "Recorder": "Grabador"},
        "sp_device": "Heladera", "sp_idle": "No está sonando nada", "sp_here": "Sonando en la heladera",
        "sp_away": "Sonando en {d}", "sp_paused": "En pausa", "sp_resume": "Seguir con «{t}»",
        "sp_search": "Buscar música", "sp_move": "Pasar a la heladera", "sp_find": "Tema, artista, disco o lista",
        "sp_recent": "Escuchado hace poco", "sp_lists": "Tus listas", "sp_songs": "Temas",
        "sp_more": "Artistas, discos y listas", "sp_none": "No encontré nada", "sp_failed": "Spotify no contestó",
        "sp_kind": {"artist": "Artista", "album": "Disco", "playlist": "Lista"},
        "sp_open_app": "Abrí la app de Spotify en esta tablet para escuchar acá", "sp_no_device": "Spotify no ve «{d}»",
    },
}

FRIDGE_PAGE = r"""<!doctype html>
<html lang="__LANG__">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<link rel="manifest" href="/fridge-manifest.json">
<link rel="icon" href="/icon-192.png">
<meta name="theme-color" content="#05070b">
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
           scrollbar-width:none; overscroll-behavior:contain; touch-action:pan-x; }  /* no page zoom: it slid screens */
  body.full #strip { overflow:hidden; }
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
  #casa .left .stale { text-align:center; margin-top:12px; }
  #casa:not(.empty) .left .stale { display:none; }  /* with events, the line sits under the list */
  .offline { position:absolute; top:8px; left:0; right:0; text-align:center; color:#ff6b6b; font-size:13px; letter-spacing:2px;
             z-index:6; }  /* above a full-screen camera too */
  #casa .nothing { color:var(--muted); margin-top:26px; font-size:18px; letter-spacing:2px; text-align:center; }
  /* Spotify strip: what's playing (here or elsewhere), its buttons, and the search screen */
  .play { display:flex; gap:18px; align-items:center; border:1px solid var(--edge); border-radius:18px; padding:12px 16px;
          margin-top:12px; background:linear-gradient(90deg, #0e1a2a, #0a0f18); min-height:98px; }
  .cover { width:72px; height:72px; border-radius:10px; flex:none; object-fit:cover;
           background:linear-gradient(135deg,#ff5f9e,#7c5cff 55%,#2bd9ff); box-shadow:0 0 18px #7c5cff55; }
  .cover.dull { opacity:.35; box-shadow:none; }
  .play .mid { flex:1; min-width:0; }
  .play .src { color:#1ed760; font-size:12px; letter-spacing:3px; text-transform:uppercase; white-space:nowrap;
               overflow:hidden; text-overflow:ellipsis; }
  .play .src.away { color:#ffc857; }
  .play .song { font-size:22px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .play .art { color:var(--muted); font-size:16px; margin-top:2px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .play .idle { color:var(--muted); font-size:20px; letter-spacing:1px; }
  .bar { height:3px; background:#1f2a3a; border-radius:3px; margin-top:10px; position:relative; }
  .bar i { position:absolute; left:0; top:0; bottom:0; width:0; background:var(--glow); border-radius:3px; box-shadow:0 0 8px var(--glow); }
  .btns { display:flex; gap:10px; align-items:center; flex:none; min-width:0; }
  .rb { width:58px; height:58px; border-radius:50%; border:1px solid #2a3546; background:#0b1422; display:grid;
        place-items:center; cursor:pointer; color:var(--ink); font-size:22px; }
  .rb svg { width:24px; height:24px; fill:var(--ink); }
  .rb.main { width:66px; height:66px; border-color:#5ee1ff88; box-shadow:0 0 14px #5ee1ff33; }
  .rb.main svg { fill:var(--glow); width:28px; height:28px; }
  .rb:active, .pill:active, .row:active, .card:active { opacity:.6; }
  .pill { height:58px; border-radius:29px; border:1px solid #2a3546; background:#0b1422; display:flex; align-items:center;
          gap:10px; padding:0 22px; font-size:18px; color:var(--ink); white-space:nowrap; cursor:pointer; max-width:330px; min-width:0;
          flex:0 1 auto; }
  .pill span { overflow:hidden; text-overflow:ellipsis; }
  .pill svg { width:22px; height:22px; fill:var(--glow); flex:none; }
  .pill.go { border-color:#ffc85788; color:#ffc857; }
  .pill.go svg { fill:#ffc857; }
  .vol { display:flex; flex-direction:column; gap:6px; }
  .vol .rb { width:42px; height:42px; }
  .vol .rb svg { width:18px; height:18px; }
  #sx { position:fixed; inset:0; z-index:5; padding:26px 40px; display:flex; flex-direction:column;
        background:radial-gradient(ellipse at 30% 10%, #0b1626 0%, var(--bg) 70%); }
  #sx .top { display:flex; gap:14px; align-items:center; }
  #sx .box { flex:1; height:58px; border-radius:29px; border:1px solid #5ee1ff77; background:#0a111c; display:flex;
             align-items:center; gap:12px; padding:0 22px; box-shadow:0 0 16px #5ee1ff22; }
  #sx .box svg { width:22px; height:22px; fill:var(--glow); flex:none; }
  #sx input { flex:1; min-width:0; background:none; border:0; outline:0; color:var(--ink); font:inherit; font-size:22px;
              -webkit-user-select:text; user-select:text; }
  #sx input::placeholder { color:var(--muted); }
  #sx .cols { display:grid; grid-template-columns:1.25fr 1fr; gap:34px; margin-top:22px; flex:1; min-height:0; }
  #sx .cols > div { min-height:0; overflow:hidden; }
  #sx h4 { margin:0 0 8px; color:var(--glow); font-weight:400; font-size:12px; letter-spacing:3px; text-transform:uppercase; opacity:.85; }
  #sx .msg { color:var(--muted); font-size:18px; margin-top:30px; }
  .row { display:flex; gap:14px; align-items:center; padding:9px 4px; border-top:1px solid var(--edge); cursor:pointer; }
  .row .c { width:50px; height:50px; border-radius:8px; flex:none; object-fit:cover; background:#1a2433; }
  .row .t { font-size:19px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .row .a { color:var(--muted); font-size:14px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .row > div { min-width:0; }
  .row .d { margin-left:auto; color:var(--muted); font-size:14px; font-variant-numeric:tabular-nums; flex:none; }
  .cards { display:grid; grid-template-columns:repeat(3, 1fr); gap:14px; }
  .card { cursor:pointer; min-width:0; }
  .card .c { width:100%; aspect-ratio:1; border-radius:12px; object-fit:cover; display:block; background:#1a2433; }
  .card.round .c { border-radius:50%; }
  .card .t { font-size:15px; margin-top:7px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .card .a { color:var(--muted); font-size:12px; letter-spacing:1px; text-transform:uppercase; }

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

  /* Cámaras: one big and live, the others as stills */
  .cams { flex:1; display:grid; grid-template-columns:2fr 1fr; grid-template-rows:repeat(var(--small, 1), 1fr); gap:12px;
          min-height:0; }
  .cams.one { grid-template-columns:1fr; }
  .cam { position:relative; border-radius:14px; overflow:hidden; border:1px solid var(--edge); background:#000; min-height:0; }
  .cam { cursor:pointer; }
  .cam img, .cam cam-live, .cam video { position:absolute; inset:0; width:100%; height:100%; object-fit:cover; display:block; }
  .cam.big { grid-row:1 / -1; border-color:#5ee1ff66; box-shadow:0 0 18px #5ee1ff22; }
  /* the big one tapped: whole screen, pinch to zoom, drag to look around */
  .cam.full { position:fixed; inset:0; z-index:5; border:0; border-radius:0; touch-action:none; }
  .cam.full img, .cam.full cam-live { transform-origin:0 0; transform:translate(var(--x, 0), var(--y, 0)) scale(var(--z, 1)); }
  .cam.full img, .cam.full video { object-fit:contain; }
  .cam .close { display:none; position:absolute; left:14px; top:10px; z-index:1; width:44px; height:44px; border-radius:50%;
                background:#000a; color:var(--ink); font-size:22px; line-height:44px; text-align:center; }
  .cam.full .close { display:block; }
  .cam .live { position:absolute; right:10px; top:8px; font-size:11px; letter-spacing:2px; color:var(--now);
               background:#000a; padding:3px 8px; border-radius:8px; z-index:1; }
  .away { flex:1; display:flex; align-items:center; justify-content:center; color:var(--muted); font-size:22px; letter-spacing:3px; }

  /* Estado: tiles from /api/status */
  #tiles { flex:1; display:grid; grid-template-columns:repeat(4, 1fr); grid-template-rows:1fr 1fr; grid-auto-flow:dense;
           gap:12px; min-height:0; }
  .tile { border:1px solid var(--edge); border-radius:14px; padding:12px 14px; background:#0a111c88; overflow:hidden;
          display:flex; flex-direction:column; min-height:0; }
  .tile.wide { grid-column:span 2; }
  .tile .k { color:var(--glow); font-size:11px; letter-spacing:3px; text-transform:uppercase; opacity:.85; }
  .tile .v { font-size:34px; font-weight:200; margin-top:6px; font-variant-numeric:tabular-nums; }
  .tile .v small { font-size:16px; color:var(--muted); }
  .tile .s { color:var(--muted); font-size:13px; margin-top:4px; line-height:1.35; }
  .ok { color:var(--now); }
  .warn { color:#ffc857 !important; }
  .bad { color:#ff6b6b !important; }
  .pp { display:flex; gap:10px; margin-top:10px; flex-wrap:wrap; }
  .pp span { border:1px solid #7cf5b055; color:var(--now); border-radius:20px; padding:4px 12px; font-size:16px; }
  .pp span.off { border-color:#2a3546; color:#4a586c; }
  .inks { display:flex; gap:10px; flex:1; min-height:30px; max-height:70px; align-items:flex-end; margin-top:10px; }
  .inks i { flex:1; border-radius:4px; background:var(--c); opacity:.85; box-shadow:0 0 8px var(--c); }
  .dv { display:flex; flex-wrap:wrap; align-content:flex-start; gap:6px; margin-top:10px; flex:1; min-height:0; overflow:hidden; }
  .dv span { border:1px solid #7cf5b044; color:#bff5d6; border-radius:16px; padding:3px 10px; font-size:13px; white-space:nowrap; }
  .dv span.off { border-color:#222c3a; color:#4a586c; }
  .dv span.bad { border-color:#ff6b6b55; }

  /* Held upright (on the wall it lies down): the same screens, stacked */
  @media (orientation: portrait) {
    .screen { padding:28px 24px 50px; }
    #casa .top { flex-direction:column; align-items:stretch; justify-content:center; gap:26px; }
    #casa .left { text-align:center; }
    #casa .right { flex:0 1 auto; border-left:0; border-top:1px solid var(--edge); padding:18px 0 0; }
    .play { flex-wrap:wrap; }
    .play .btns { flex:1 1 100%; justify-content:center; }
    #sx { padding:22px 20px; }
    #sx .cols { display:block; overflow-y:auto; scrollbar-width:none; }
    #sx .cols > div { overflow:visible; }
    #sx .cols > div + div { margin-top:22px; }
    #week { grid-template-columns:1fr; grid-template-rows:repeat(7, minmax(0, 1fr)); gap:8px; }
    .col { display:grid; grid-template-columns:88px 1fr; grid-template-rows:auto 1fr; column-gap:12px; padding:8px 12px; }
    .col .dn { white-space:normal; }
    .col .dd { grid-row:2; margin:0; }
    .col .its { grid-column:2; grid-row:1 / -1; display:flex; flex-wrap:wrap; align-content:flex-start; gap:6px 18px; }
    .col .it { margin:0; max-width:100%; }
    .col .more { width:100%; padding:0; }
    .cams { grid-template-columns:repeat(var(--small, 1), 1fr); grid-template-rows:2fr 1fr; }
    .cams.one { grid-template-columns:1fr; grid-template-rows:1fr; }
    .cam.big { grid-row:auto; grid-column:1 / -1; }
    #tiles { grid-template-columns:repeat(2, 1fr); grid-template-rows:none; grid-auto-rows:minmax(0, 1fr); }
  }
</style>
</head>
<body>
<div id="wrap">
<main id="strip">
  <section class="screen" id="casa">
    <div class="top">
      <div class="left"><div class="time" id="bigclock"></div><div class="date" id="date"></div>
        <div class="nothing" id="nothing" hidden></div>
        <div class="quiet stale" hidden></div></div>
      <div class="right"><div class="label" id="left-today"></div><div id="today"></div>
        <div class="quiet stale" hidden></div></div>
    </div>
    <div class="play" id="play" hidden></div>
  </section>
  <section class="screen" id="camaras">
    <div class="head"><div class="label" data-name="camaras"></div><div class="clock"></div></div>
    <div class="cams" id="cams"></div><div class="away" id="cams-away" hidden></div>
  </section>
  <section class="screen" id="calendario">
    <div class="head"><div><span class="label" id="week-label"></span> <span class="quiet stale" hidden></span></div>
      <div class="clock"></div></div>
    <div id="week"></div>
  </section>
  <section class="screen" id="estado">
    <div class="head"><div class="label" data-name="estado"></div><div class="clock"></div></div>
    <div id="tiles"></div>
  </section>
</main>
<div class="offline" id="offline" hidden></div>
<nav class="dots" id="dots"></nav>
<div id="sx" hidden>
  <div class="top"><label class="box"><svg viewBox="0 0 24 24"><path d="M10 3a7 7 0 0 1 5.6 11.2l5.1 5.1-1.4 1.4-5.1-5.1A7 7 0 1 1 10 3zm0 2a5 5 0 1 0 0 10 5 5 0 0 0 0-10z"/></svg>
    <input id="sq" type="search" autocomplete="off" enterkeyhint="search"></label><div class="rb" id="sx-close">✕</div></div>
  <div class="cols"><div><h4 id="sx-h1"></h4><div id="sx-l"></div></div><div><h4 id="sx-h2"></h4><div class="cards" id="sx-r"></div></div></div>
</div>
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

let data = {agenda: {calendars: [], events: [], stale: false}, playing: null,
            settings: {dim: '00:00-07:00', back_s: 120, player: 'page'}};
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
  if (Date.now() - touched <= data.settings.back_s * 1000) return;
  closeSearch();
  if (current && current !== screens[0]) go(screens[0]);
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

// --- Spotify: the strip on Casa, always there once Spotify is set up. Over https the page is itself a
// Spotify speaker ("Heladera"), so music can be found and played right here; over http it only shows. ---
const ICON = {
  prev: '<svg viewBox="0 0 24 24"><path d="M6 6h2v12H6zm3.5 6 8.5 6V6z"/></svg>',
  next: '<svg viewBox="0 0 24 24"><path d="M16 6h2v12h-2zM6 18l8.5-6L6 6z"/></svg>',
  pause: '<svg viewBox="0 0 24 24"><path d="M6 5h4v14H6zm8 0h4v14h-4z"/></svg>',
  play: '<svg viewBox="0 0 24 24"><path d="M7 5v14l12-7z"/></svg>',
  plus: '<svg viewBox="0 0 24 24"><path d="M11 5h2v14h-2zM5 11h14v2H5z"/></svg>',
  minus: '<svg viewBox="0 0 24 24"><path d="M5 11h14v2H5z"/></svg>',
  down: '<svg viewBox="0 0 24 24"><path d="M11 4h2v11l4-4 1.4 1.4L12 18.8l-6.4-6.4L7 11l4 4z"/></svg>',
  search: '<svg viewBox="0 0 24 24"><path d="M10 3a7 7 0 0 1 5.6 11.2l5.1 5.1-1.4 1.4-5.1-5.1A7 7 0 1 1 10 3zm0 2a5 5 0 1 0 0 10 5 5 0 0 0 0-10z"/></svg>',
};
const CAN_PLAY = location.protocol === 'https:';  // Spotify's spPlayer only works in https pages
const img = (url, cls) => /^https:\/\//.test(url || '') ? `<img class="${cls}" src="${esc(url)}" alt="">` : `<div class="${cls}"></div>`;
const coverOf = (images, size = 300) => {
  const ok = (images || []).filter(i => i && i.url);
  return ok.length ? ok.reduce((a, b) => Math.abs((a.width || 0) - size) <= Math.abs((b.width || 0) - size) ? a : b).url : '';
};

let spToken = null, spTokenAt = 0;
async function token() {  // an hour-long token from the server; asked again every 5 minutes
  if (spToken && Date.now() - spTokenAt < 300000) return spToken;
  const r = await get('/api/spotify/token');
  if (!r.ok) throw new Error('token ' + r.status);
  spToken = (await r.json()).token;
  spTokenAt = Date.now();
  return spToken;
}
async function api(method, path, body) {
  for (let i = 0; i < 2; i++) {
    const stop = new AbortController(), timer = setTimeout(() => stop.abort(), 10000);
    try {
      const r = await fetch('https://api.spotify.com/v1' + path, {method, signal: stop.signal,
        headers: {Authorization: 'Bearer ' + await token(), 'Content-Type': 'application/json'},
        body: body ? JSON.stringify(body) : undefined});
      if (r.status !== 401 || i) return r;
      spToken = null;  // the token died early: ask for a new one, once
    } finally { clearTimeout(timer); }
  }
}
const json = async r => (r && r.ok && r.status !== 204) ? r.json() : null;

let spPlayer = null, myDevice = null, local = null, localAt = 0;
// FRIDGE_SPOTIFY_PLAYER: "page" plays in the page itself (the player below); "app" sends the music to the
// Spotify app on the tablet (for tablets whose browser goes silent after a few seconds) and a name to that
// speaker. The strip, the buttons and the search are the same: only where the sound comes out changes.
const playerSetting = () => data.settings.player || 'page';
const viaApp = () => playerSetting() !== 'page';
let appVolume = null, appVolumeOk = false, devicesAt = 0, goneDevice = null;
async function findDevice() {  // the app or speaker, among the devices the account sees; asked on every poll (15 s)
  if (!viaApp() || !CAN_PLAY || !data.spotify || Date.now() - devicesAt < 14000) return;
  devicesAt = Date.now();
  let got;
  try { got = await json(await api('GET', '/me/player/devices')); } catch (e) { return; }
  if (!got || !Array.isArray(got.devices)) return;  // Spotify hiccup: keep what we knew, ask again next poll
  // "app": the account's tablet (only one tablet should be logged in; otherwise put the tablet's name instead)
  const want = playerSetting().toLowerCase();
  const d = got.devices.find(x => want === 'app' ? x.type === 'Tablet' : (x.name || '').toLowerCase() === want);
  if (!d && myDevice) goneDevice = myDevice;  // the app was closed: Spotify still says it plays there for a while
  myDevice = d ? d.id : null;
  if (d) goneDevice = null;
  appVolumeOk = !!(d && d.supports_volume);
  if (d && d.volume_percent != null) appVolume = d.volume_percent;
  drawPlaying();
}
function startPlayer() {
  if (spPlayer || !CAN_PLAY || !data.spotify || viaApp()) return;
  spPlayer = 'loading';
  window.onSpotifyWebPlaybackSDKReady = () => {
    spPlayer = new Spotify.Player({name: T.sp_device, getOAuthToken: cb => token().then(cb, () => {}), volume: 0.7});
    spPlayer.addListener('ready', ({device_id}) => { myDevice = device_id; drawPlaying(); });
    spPlayer.addListener('not_ready', () => { myDevice = null; local = null; drawPlaying(); });
    spPlayer.addListener('player_state_changed', s => {
      local = s && s.track_window && s.track_window.current_track ? s : null;
      localAt = Date.now();
      drawPlaying();
    });
    for (const name of ['initialization_error', 'authentication_error', 'account_error', 'playback_error'])
      spPlayer.addListener(name, e => console.warn('spotify', name, e && e.message));
    spPlayer.connect();
  };
  const s = document.createElement('script');
  s.src = 'https://sdk.scdn.co/spotify-player.js';
  s.onerror = () => { spPlayer = null; };  // no internet: tried again on the next poll
  document.head.append(s);
}

// what the strip shows: here (playing or paused on this tablet), away (playing on another device) or idle
function view() {
  if (local) {
    const t = local.track_window.current_track;
    return {mode: 'here', paused: local.paused, song: t.name, artist: t.artists.map(a => a.name).join(', '),
            album: t.album.name, cover: coverOf(t.album.images), duration: local.duration,
            at: local.position + (local.paused ? 0 : Date.now() - localAt)};
  }
  const p = data.playing && data.playing.device_id !== goneDevice ? data.playing : null;
  const here = !!(p && p.device_id && p.device_id === myDevice);
  // paused on our own device: shown, with a play button; paused elsewhere: that's just nothing playing
  if (p && (p.playing || here)) return {mode: here ? 'here' : 'away', paused: !p.playing, song: p.song,
                 artist: p.artist, album: p.album, cover: p.cover, device: p.device, duration: p.duration_ms,
                 at: p.progress_ms + (p.playing ? Date.now() - gotAt : 0)};
  return {mode: 'idle'};
}
let playingKey = '', lastPlayed = null, lastPlayedAt = 0;
function drawPlaying() {
  const v = view(), box = $('#play');
  box.hidden = !data.spotify && v.mode === 'idle';
  if (box.hidden) { playingKey = ''; return; }
  const ready = CAN_PLAY && !!myDevice;
  const key = JSON.stringify([v.mode, v.paused, v.song, v.artist, v.cover, v.device, ready, appVolumeOk, lastPlayed && lastPlayed.name]);
  if (key !== playingKey) {  // same song: only the progress moves, the cover isn't fetched again
    playingKey = key;
    const search = ready ? `<div class="rb" data-do="search">${ICON.search}</div>` : '';
    if (v.mode === 'idle') {
      const hint = CAN_PLAY && viaApp() && !myDevice ?  // the app or speaker isn't there: say what to do
        (playerSetting() === 'app' ? T.sp_open_app : fmt(T.sp_no_device, {d: playerSetting()})) : T.sp_idle;
      box.innerHTML = '<div class="cover dull"></div>' +
        `<div class="mid"><div class="src">● Spotify</div><div class="idle">${esc(hint)}</div></div><div class="btns">` +
        (ready && lastPlayed ? `<div class="pill" data-do="resume">${ICON.play}<span>${esc(fmt(T.sp_resume, {t: lastPlayed.name}))}</span></div>` : '') +
        (ready ? `<div class="pill" data-do="search">${ICON.search}<span>${esc(T.sp_search)}</span></div>` : '') + '</div>';
    } else {
      const here = v.mode === 'here';
      const where = here ? (v.paused ? T.sp_paused : T.sp_here) : fmt(T.sp_away, {d: v.device || 'Spotify'});
      box.innerHTML = img(v.cover, 'cover') +
        `<div class="mid"><div class="src${here ? '' : ' away'}">● ${esc(where)}</div><div class="song">${esc(v.song)}</div>` +
        `<div class="art">${esc([v.artist, v.album].filter(Boolean).join(' · '))}</div><div class="bar"><i></i></div></div>` +
        // over http there's no token (it only goes out encrypted): the strip just shows
        '<div class="btns">' + (CAN_PLAY ? `<div class="rb" data-do="prev">${ICON.prev}</div>` +
        `<div class="rb main" data-do="toggle">${v.paused ? ICON.play : ICON.pause}</div><div class="rb" data-do="next">${ICON.next}</div>` : '') +
        (here && (local || (viaApp() && appVolumeOk)) ? `<div class="vol"><div class="rb" data-do="up">${ICON.plus}</div><div class="rb" data-do="down">${ICON.minus}</div></div>` : '') +
        (!here && ready ? `<div class="pill go" data-do="move">${ICON.down}<span>${esc(T.sp_move)}</span></div>` : '') + search + '</div>';
    }
  }
  drawProgress();
}
function drawProgress() {
  const v = view(), bar = $('#play .bar i');
  if (!bar || !v.duration) return;
  bar.style.width = (100 * Math.min(1, v.at / v.duration)).toFixed(2) + '%';
}

const soon = () => setTimeout(poll, 1500);  // after a button: the server's view of what plays
async function playHere(body) {
  if (!myDevice) return;
  const r = await api('PUT', '/me/player/play?device_id=' + encodeURIComponent(myDevice), body);
  if (!r || !r.ok) throw new Error('play ' + (r && r.status));
}
async function appVolumeBy(step) {  // the app's or speaker's volume, through Spotify
  appVolume = Math.max(0, Math.min(100, (appVolume == null ? 50 : appVolume) + step));
  await api('PUT', '/me/player/volume?volume_percent=' + appVolume + '&device_id=' + encodeURIComponent(myDevice));
}
const ACTIONS = {
  async prev() { local ? await spPlayer.previousTrack() : await api('POST', '/me/player/previous'); soon(); },
  async next() { local ? await spPlayer.nextTrack() : await api('POST', '/me/player/next'); soon(); },
  async toggle() {
    if (local) await spPlayer.togglePlay();
    else await api('PUT', view().paused ? '/me/player/play?device_id=' + encodeURIComponent(myDevice) : '/me/player/pause');
    soon();
  },
  async up() { local ? await spPlayer.setVolume(Math.min(1, (await spPlayer.getVolume()) + 0.1)) : await appVolumeBy(10); },
  async down() { local ? await spPlayer.setVolume(Math.max(0, (await spPlayer.getVolume()) - 0.1)) : await appVolumeBy(-10); },
  async move() { await api('PUT', '/me/player', {device_ids: [myDevice], play: true}); soon(); },
  async resume() { await playHere(lastPlayed.body); },
  async search() { openSearch(); },
};
$('#play').addEventListener('click', e => {
  const b = e.target.closest('[data-do]');
  if (!b) return;
  if (spPlayer && spPlayer.activateElement) spPlayer.activateElement();  // in the tap itself, or the tablet won't play sound
  ACTIONS[b.dataset.do]().catch(err => console.warn('spotify', b.dataset.do, err));
});

// what to offer when nothing plays: the last thing played, from its album or playlist
async function loadLastPlayed() {
  if (!CAN_PLAY || !data.spotify) return;
  try {
    const got = await json(await api('GET', '/me/player/recently-played?limit=1'));
    const it = got && got.items && got.items[0];
    if (!it) return;
    const t = it.track, ctx = it.context && it.context.uri;
    lastPlayed = {name: t.name, body: ctx ? {context_uri: ctx, offset: {uri: t.uri}} : {uris: [t.uri]}};
    drawPlaying();
  } catch (e) { /* stays without it */ }
}

// --- Spotify search screen ---
const sq = $('#sq');
sq.placeholder = T.sp_find;
const trackBody = t => t.album && t.album.uri ? {context_uri: t.album.uri, offset: {uri: t.uri}} : {uris: [t.uri]};
let found = [];  // what each row and card plays, by index
function rowHTML(t) {
  found.push(trackBody(t));
  return `<div class="row" data-i="${found.length - 1}">${img(coverOf(t.album && t.album.images, 64), 'c')}` +
    `<div><div class="t">${esc(t.name)}</div><div class="a">${esc((t.artists || []).map(a => a.name).join(', '))}</div></div>` +
    `<div class="d">${mss(t.duration_ms || 0)}</div></div>`;
}
function cardHTML(x) {
  found.push({context_uri: x.uri});
  return `<div class="card${x.type === 'artist' ? ' round' : ''}" data-i="${found.length - 1}">${img(coverOf(x.images), 'c')}` +
    `<div class="t">${esc(x.name)}</div><div class="a">${esc(T.sp_kind[x.type] || '')}</div></div>`;
}
function showResults(h1, tracks, h2, cards) {
  found = [];
  $('#sx-h1').textContent = h1;
  $('#sx-h2').textContent = cards.length ? h2 : '';
  $('#sx-l').innerHTML = tracks.length ? tracks.map(rowHTML).join('') : `<div class="msg">${esc(T.sp_none)}</div>`;
  $('#sx-r').innerHTML = cards.map(cardHTML).join('');
}
const failed = () => { found = []; $('#sx-l').innerHTML = `<div class="msg">${esc(T.sp_failed)}</div>`; $('#sx-r').innerHTML = ''; };
async function showStart() {  // before typing: played lately and the account's playlists
  try {
    const [recent, lists] = await Promise.all([api('GET', '/me/player/recently-played?limit=20').then(json),
                                               api('GET', '/me/playlists?limit=6').then(json)]);
    if (sq.value.trim()) return;
    const seen = new Set(), tracks = [];
    for (const it of (recent && recent.items) || []) {
      if (it.track && !seen.has(it.track.id)) { seen.add(it.track.id); tracks.push(it.track); }
    }
    showResults(T.sp_recent, tracks.slice(0, 5), T.sp_lists, ((lists && lists.items) || []).filter(Boolean));
  } catch (e) { failed(); }
}
let typing = null, searchSeq = 0;
sq.addEventListener('input', () => {
  clearTimeout(typing);
  const q = sq.value.trim();
  if (!q) { showStart(); return; }
  typing = setTimeout(async () => {
    const mine = ++searchSeq;
    try {
      const r = await json(await api('GET', '/search?type=track,artist,album,playlist&limit=6&q=' + encodeURIComponent(q)));
      if (mine !== searchSeq || !r) return;
      const ok = list => ((list && list.items) || []).filter(Boolean);
      const cards = [...ok(r.artists).slice(0, 1), ...ok(r.albums).slice(0, 3), ...ok(r.playlists).slice(0, 2)];
      showResults(T.sp_songs, ok(r.tracks).slice(0, 5), T.sp_more, cards);
    } catch (e) { if (mine === searchSeq) failed(); }
  }, 450);
});
function openSearch() {
  $('#sx').hidden = false;
  document.body.classList.add('full');
  sq.value = '';
  showResults(T.sp_recent, [], T.sp_lists, []);
  $('#sx-l').innerHTML = '';
  showStart();
  sq.focus();
}
function closeSearch() {
  if ($('#sx').hidden) return;
  $('#sx').hidden = true;
  sq.blur();
  if (!$('#cams .full')) document.body.classList.remove('full');
}
$('#sx-close').onclick = closeSearch;
$('#sx').addEventListener('click', e => {
  const el = e.target.closest('[data-i]');
  if (!el || !found[+el.dataset.i]) return;
  if (spPlayer && spPlayer.activateElement) spPlayer.activateElement();
  const body = found[+el.dataset.i];
  closeSearch();
  playHere(body).then(soon, err => console.warn('spotify play', err));
});

// over https the screen can be kept on by the page itself (no kiosk app needed)
async function keepAwake() {
  try { if (navigator.wakeLock && document.visibilityState === 'visible') await navigator.wakeLock.request('screen'); } catch (e) {}
}
document.addEventListener('visibilitychange', keepAwake);
keepAwake();

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
  // no answer from the server for 2 minutes: say so, and don't pretend a song is still playing
  const off = Date.now() - gotAt > 120000;
  $('#offline').hidden = !off;
  if (off && data.playing) { data.playing = null; drawPlaying(); }
  drawProgress();
}, 1000);

$('#offline').textContent = T.offline;
async function get(url) {  // a hung connection (e.g. after a Wi-Fi change) gives up after 10 s
  const stop = new AbortController(), timer = setTimeout(() => stop.abort(), 10000);
  try { return await fetch(url, {cache: 'no-store', signal: stop.signal}); } finally { clearTimeout(timer); }
}
let asking = false;
async function poll() {
  if (asking) return;
  asking = true;
  try {
    const r = await get('/api/fridge');
    if (r.ok) {
      data = await r.json();
      gotAt = Date.now();
      drawAll(new Date());
      drawPlaying();
      startPlayer();
      findDevice();
      if (data.spotify && !lastPlayed && !view().song && Date.now() - lastPlayedAt > 600000) {
        lastPlayedAt = Date.now();
        loadLastPlayed();
      }
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

// --- Status (the panel's /api/status): asked at start (are there cameras?), then only while it shows ---
let lastStatus = null, asked = false;
async function refreshStatus() {
  if (asked) return;
  asked = true;
  try {
    const r = await get('/api/status');
    if (r.ok) { lastStatus = await r.json(); gotStatus(); }
  } catch (e) {
    // keep the last one
  } finally {
    asked = false;
  }
}
function gotStatus() {
  const s = lastStatus, c = s.cameras && (s.cameras.names || []).length ? s.cameras : null;
  if (!c) dropScreen('camaras');
  const wasHome = !!(cams && cams.home);
  cams = c;
  if (camsOn && c && !!c.home !== wasHome) drawCams();
  drawStatus(s);
}
let statusTimer = null;
onShow('estado', () => { refreshStatus(); statusTimer = setInterval(refreshStatus, 30000); });
onHide('estado', () => clearInterval(statusTimer));

// --- Cámaras: the big one live (go2rtc's player, through the panel), the others as stills ---
let cams = null, big = 1, camsOn = false, stillTimer = null, player = null, Player = null, playToken = 0;
$('#cams-away').textContent = T.home_only;
async function loadPlayer() {
  if (Player) return true;
  try {
    const {VideoRTC} = await import('/live/video-rtc.js');
    Player = class extends VideoRTC {};
    customElements.define('cam-live', Player);
    return true;
  } catch (e) { return false; }
}
function clearStills() {  // a wall tablet runs this for days: every picture is freed
  for (const img of document.querySelectorAll('#cams img')) if (img.dataset.url) URL.revokeObjectURL(img.dataset.url);
  $('#cams').innerHTML = '';
}
function drawCams() {
  closeFull();
  stopPlayer();
  clearStills();
  const home = !!(cams && cams.home);
  $('#cams-away').hidden = home || !cams;  // not asked yet: neither
  $('#cams').hidden = !home;
  if (!home || !camsOn) return;
  const n = cams.names.length;
  if (big > n) big = 1;
  const order = [big, ...[...Array(n)].map((_, i) => i + 1).filter(i => i !== big)];
  $('#cams').classList.toggle('one', n === 1);
  $('#cams').style.setProperty('--small', Math.max(1, n - 1));
  $('#cams').innerHTML = order.map((c, i) => `<div class="cam${i ? '' : ' big'}" data-n="${c}">` +
    `<img alt="" data-n="${c}" style="visibility:hidden">` +
    `${i ? '' : `<div class="live" hidden>● ${esc(T.live)}</div><div class="close">✕</div>`}</div>`).join('');
  for (const t of document.querySelectorAll('#cams .cam:not(.big)')) t.onclick = () => { big = +t.dataset.n; drawCams(); };
  zoomable($('#cams .big'));
  stills();
  play(big, true);
}
function stills() {
  if (!camsOn) return;
  for (const img of document.querySelectorAll('#cams img')) {
    if (img.dataset.busy || img.closest('.playing')) continue;  // a slow answer must not pile up requests
    img.dataset.busy = 1;
    fetch('/api/camera/' + img.dataset.n + '.jpg?t=' + Date.now()).then(async r => {
      if (r.status !== 200) return;  // 204: no fresh still yet, keep the last one
      const blob = await r.blob();
      if (!img.isConnected) return;
      if (img.dataset.url) URL.revokeObjectURL(img.dataset.url);
      img.dataset.url = URL.createObjectURL(blob);
      img.src = img.dataset.url;
      img.style.visibility = '';
    }).catch(() => {}).finally(() => { delete img.dataset.busy; });
  }
}
async function play(n, hd) {
  stopPlayer();
  const mine = ++playToken;
  if (!(await loadPlayer()) || mine !== playToken || !camsOn) return;
  const tile = $('#cams .big');
  if (!tile) return;
  const el = document.createElement('cam-live');
  Object.assign(el, {mode: 'mse', media: 'video', visibilityCheck: false});
  tile.append(el);
  el.video.controls = false;
  el.video.muted = true;
  el.video.playsInline = true;
  el.src = new URL('/live/ws?src=cam' + n + (hd ? '_hd' : ''), location.href).href;
  player = el;
  // a weak screen can't decode the big stream: drop to the small one (the still stays meanwhile)
  const fallback = () => { if (player !== el) return; clearTimeout(el.timer); if (hd) play(n, false); };
  el.video.addEventListener('playing', () => {
    if (player !== el) return;
    clearTimeout(el.timer);
    tile.classList.add('playing');
    $('.live', tile).hidden = false;
  });
  el.video.addEventListener('error', fallback);
  el.timer = setTimeout(fallback, hd ? 5000 : 10000);
}
function stopPlayer() {
  playToken++;
  if (!player) return;
  clearTimeout(player.timer);
  player.ondisconnect();
  const tile = player.closest('.cam');
  if (tile) { tile.classList.remove('playing'); $('.live', tile).hidden = true; }
  player.remove();
  player = null;
}
// the big one tapped goes full screen (same video, no reconnect): pinch zooms 1 to 5 times, one finger drags
// while zoomed, and ✕ or a tap while not zoomed closes it. Swiping to other screens is off meanwhile.
let zoom = {z: 1, x: 0, y: 0};
function setZoom(tile, z, x, y) {
  z = Math.min(5, Math.max(1, z));
  const w = tile.clientWidth, h = tile.clientHeight;
  zoom = {z, x: Math.min(0, Math.max(w - w * z, x)), y: Math.min(0, Math.max(h - h * z, y))};
  tile.style.setProperty('--z', zoom.z);
  tile.style.setProperty('--x', zoom.x + 'px');
  tile.style.setProperty('--y', zoom.y + 'px');
}
function closeFull() {
  const t = $('#cams .full');
  if (t) { t.classList.remove('full'); setZoom(t, 1, 0, 0); }
  document.body.classList.remove('full');
}
function zoomable(tile) {
  const fingers = new Map();
  let from = null, moved = false;  // from: where the fingers and the zoom were when this gesture started
  const at = e => { const r = tile.getBoundingClientRect(); return {x: e.clientX - r.left, y: e.clientY - r.top}; };
  const restart = () => {
    const p = [...fingers.values()];
    from = !p.length ? null : p.length === 1 ? {p: p[0], zoom}
      : {zoom, d: Math.hypot(p[0].x - p[1].x, p[0].y - p[1].y) || 1, m: {x: (p[0].x + p[1].x) / 2, y: (p[0].y + p[1].y) / 2}};
  };
  tile.addEventListener('pointerdown', e => {
    if (!tile.classList.contains('full')) return;
    if (!fingers.size) moved = false;
    fingers.set(e.pointerId, at(e));
    restart();
  });
  tile.addEventListener('pointermove', e => {
    if (!fingers.has(e.pointerId) || !from) return;
    fingers.set(e.pointerId, at(e));
    const p = [...fingers.values()], z0 = from.zoom;
    if (p.length >= 2 && from.d) {  // the point between the two fingers stays under them
      const d = Math.hypot(p[0].x - p[1].x, p[0].y - p[1].y), m = {x: (p[0].x + p[1].x) / 2, y: (p[0].y + p[1].y) / 2};
      const z = Math.min(5, Math.max(1, z0.z * d / from.d));
      setZoom(tile, z, m.x - (from.m.x - z0.x) * z / z0.z, m.y - (from.m.y - z0.y) * z / z0.z);
      moved = true;
    } else if (p.length === 1 && from.p) {
      const dx = p[0].x - from.p.x, dy = p[0].y - from.p.y;
      if (Math.abs(dx) + Math.abs(dy) > 8) moved = true;
      setZoom(tile, z0.z, z0.x + dx, z0.y + dy);
    }
  });
  for (const name of ['pointerup', 'pointercancel']) tile.addEventListener(name, e => { fingers.delete(e.pointerId); restart(); });
  tile.addEventListener('click', e => {
    if (!tile.classList.contains('full')) {
      tile.classList.add('full');
      document.body.classList.add('full');
      setZoom(tile, 1, 0, 0);
    } else if (e.target.closest('.close') || (!moved && zoom.z === 1)) closeFull();
  });
}

onShow('camaras', () => { camsOn = true; drawCams(); stillTimer = setInterval(stills, 2500); refreshStatus(); });
onHide('camaras', () => { camsOn = false; closeFull(); clearInterval(stillTimer); stopPlayer(); clearStills(); });

// --- Estado ---
const num = (x, d = 0) => Number(x).toLocaleString(LANG, {maximumFractionDigits: d});
const INK = {black: '#ddd', cyan: '#00c8ff', magenta: '#ff3ea5', yellow: '#ffe14d', 'light cyan': '#7fe3ff', 'light magenta': '#ff9fd2'};
const tile = (key, body, wide) => `<div class="tile${wide ? ' wide' : ''}"><div class="k">${key}</div>${body}</div>`;
const lines = list => list.length ? `<div class="s">${list.join('<br>')}</div>` : '';
function drawStatus(s) {
  const h = s.home || {}, out = [];

  const sl = h.starlink, last = s.speed && s.speed.last;
  if (sl || last) {
    const sub = [];
    let v;
    if (sl && sl.error) v = '<div class="v bad">–</div>';
    else if (sl) v = `<div class="v ${(sl.alerts || []).length ? 'warn' : 'ok'}">OK <small>${num(sl.latency_ms)} ms</small></div>`;
    else v = `<div class="v">${num(last[1])} <small>Mbps</small></div>`;
    if (sl && (sl.alerts || []).length) sub.push(`<span class="warn">${esc(T.alerts)}</span>`);
    if (last) sub.push(esc(fmt(T.last_test, {t: hm(new Date(last[0] * 1000))})) + `<br>↓ ${num(last[1])} · ↑ ${num(last[2])} Mbps`);
    out.push(tile(esc(T.k_internet), v + lines(sub)));
  }

  const people = h.people || [];
  if (people.length) {
    const ssid = (h.devices || {}).ssid;
    out.push(tile(esc(T.k_home), `<div class="pp">${people.map(p => `<span${p.home ? '' : ' class="off"'}>${esc(p.name)}</span>`).join('')}</div>` +
      (ssid ? `<div class="s" style="margin-top:12px">${esc(fmt(T.wifi, {s: ssid}))}</div>` : ''), true));
  }

  const inks = (h.printer || {}).inks || [];
  if (inks.length) {
    out.push(tile(esc(T.k_printer), `<div class="inks">${inks.map(k => `<i style="--c:${INK[k.color] || '#888'};height:${Math.max(4, Math.min(100, +k.level || 0))}%"></i>`).join('')}</div>` +
      `<div class="s">${inks.map(k => `<span${k.level <= 15 ? ' class="warn"' : ''}>${esc((T.ink || {})[k.color] || k.color)} ${num(k.level)}</span>`).join(' · ')} %</div>`));
  }

  const b = s.battery || {}, cpu = s.system && s.system.cpu_pct, sub = [];
  const temp = b.temperature != null ? `<span${b.temperature >= 40 ? ' class="bad"' : ''}>${num(b.temperature)} °C</span>` : '';
  sub.push([temp, cpu != null ? esc(fmt(T.cpu, {n: num(cpu)})) : ''].filter(Boolean).join(' · '));
  if (s.plug) sub.push(s.plug.error ? `<span class="bad">${esc(T.plug_error)}</span>`
    : esc(fmt(s.plug.on ? T.plug_on : T.plug_off, {lo: s.plug.low, hi: s.plug.high})));
  if (s.battery_stale) sub.push(`<span class="bad">${esc(T.no_battery)}</span>`);
  for (const v of s.services || []) if (!v.ok) sub.push(`<span class="bad">${esc(fmt(T.down, {s: T.svc[v.name] || v.name}))}</span>`);
  out.push(tile(esc(T.k_server), `<div class="v">${b.percentage != null ? num(b.percentage) + '<small>%</small>' : '–'}</div>` + lines(sub.filter(Boolean))));

  const d = s.disk || {};
  if (d.free_gb != null) {
    const dsub = [], photos = (d.kinds || []).find(k => k.kind === 'backup'), folders = (h.backup || {}).folders || [];
    if (photos) {
      const need = folders.reduce((t, f) => t + (f.need_gb || 0), 0);
      const state = !folders.length ? '' : need > 0.05 ? esc(fmt(T.to_go, {gb: num(need, 1)})) : esc(T.up_to_date);
      dsub.push([esc(fmt(T.photos, {gb: num(photos.gb, 1)})), state].filter(Boolean).join(' · '));
    }
    if (d.warn) dsub.push(`<span class="warn">${esc(d.warn === 'paused' ? T.backup_paused : T.backup_near)}</span>`);
    out.push(tile(esc(T.k_disk), `<div class="v">${num(d.free_gb)} <small>${esc(T.free)}</small></div>` + lines(dsub)));
  }

  const devs = (h.devices || {}).devices || [];
  if (devs.length) {
    const on = devs.filter(x => x.online), off = devs.filter(x => !x.online);
    const chip = x => `<span class="${x.online ? '' : x.kind === 'camera' ? 'off bad' : 'off'}">${esc(x.name || x.ip || x.mac)}</span>`;
    out.push(tile(esc(fmt(T.k_devices, {on: on.length, n: devs.length})), `<div class="dv">${on.concat(off).map(chip).join('')}</div>`, true));
  }

  $('#tiles').innerHTML = out.join('');
  const dv = $('#tiles .dv');
  if (dv) fitChips(dv);
}
function fitChips(box) {  // the devices that don't fit become "+N"
  const over = () => box.scrollHeight > box.clientHeight + 1;
  if (!over()) return;
  const more = document.createElement('span');
  more.className = 'off';
  box.append(more);
  let hidden = 0;
  while (over() && box.children.length > 1) {
    more.previousElementSibling.remove();
    more.textContent = '+' + ++hidden;
  }
}
matchMedia('(orientation: portrait)').addEventListener('change', () => {
  drawAll(new Date());
  if (lastStatus) drawStatus(lastStatus);
  const s = document.getElementById(current);
  if (s) strip.scrollLeft = s.offsetLeft;
});
refreshStatus();
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

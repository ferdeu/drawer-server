"""The fridge tablet page (/fridge): four full screens to swipe, for an always-on landscape tablet.
Served by panel.py (deployed side by side); its data comes from /api/fridge, /api/status and the cameras.
"""
import json

TEXT = {
    "en": {"title": "Home"},
    "es": {"title": "Casa"},
}

FRIDGE_PAGE = """<!doctype html>
<html lang="__LANG__">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fridge</title>
</head>
<body>
<script>const T = __TEXT__;</script>
</body>
</html>
"""


def render(lang):
    text = TEXT.get(lang, TEXT["en"])
    page = FRIDGE_PAGE.replace("__LANG__", lang if lang in TEXT else "en")
    # "<" escaped so no text can close the <script> it sits in
    return page.replace("__TEXT__", json.dumps(text).replace("<", "\\u003c")).encode()

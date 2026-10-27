#!/usr/bin/env bash
# PostToolUse hook for Edit/Write: shellcheck for .sh files, a syntax check for .py files.
# Problems go back to Claude (exit 2) so they get fixed before anything reaches the phone.
input="$(cat)"
file="$(printf '%s' "$input" | grep -oE '"file_path" *: *"[^"]*"' | head -1 |
  sed -E 's/^.*: *"//; s/"$//; s/\\\\/\//g')"
[ -f "$file" ] || exit 0

case "$file" in
  *.sh)
    cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0
    if command -v shellcheck >/dev/null 2>&1; then
      out="$(shellcheck -S warning -x "$file" 2>&1)"
    else
      out="$(bash -n "$file" 2>&1)"
    fi
    ;;
  *.py)
    py=python; python -c '' >/dev/null 2>&1 || py=python3
    out="$("$py" -c '
import ast, sys
try:
    ast.parse(open(sys.argv[1], encoding="utf-8").read(), sys.argv[1])
except SyntaxError as e:
    print(f"line {e.lineno}: {e.msg}: {(e.text or "").strip()}")' "$file" 2>&1)"
    ;;
  *) exit 0 ;;
esac

[ -z "$out" ] && exit 0
printf 'Check failed for %s, please fix it:\n%s\n' "$file" "$out" >&2
exit 2

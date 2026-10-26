#!/bin/sh
# install.sh: link claude-session-mover (and its short name, csm) into ~/.local/bin.
#   ./install.sh                  the command only
#   ./install.sh --skill          also link skills/move-session into every account home's
#                                 skills/, because each CLAUDE_CONFIG_DIR reads its own
#   ./install.sh --no-short-name  link claude-session-mover only, NOT csm: for a machine
#                                 where something else already owns the name `csm` — most
#                                 usefully a wrapper of your own that sets this tool's
#                                 environment (an accounts file, a quota meter, a log) and
#                                 execs it. A `csm` here would shadow that wrapper and hand
#                                 you the bare tool with none of its inputs.
# The two options may be given together, in either order.
# CSM_BIN_DIR overrides ~/.local/bin. Nothing that already exists and is not ours is replaced.
set -eu
skill=no
short=yes
for arg in "$@"; do
  case "$arg" in
    --skill) skill=yes ;;
    --no-short-name) short=no ;;
    -h|--help|help) echo "usage: $0 [--skill] [--no-short-name]"; exit 0 ;;
    *) echo "unknown option: $arg (usage: $0 [--skill] [--no-short-name])" >&2; exit 2 ;;
  esac
done
here=$(cd "$(dirname "$0")" && pwd)
tool="$here/claude-session-mover"
bin="${CSM_BIN_DIR:-$HOME/.local/bin}"
mkdir -p "$bin"

link() {   # link <source> <destination>
  if [ -e "$2" ] && [ ! -L "$2" ]; then
    echo "skipped $2: it exists and is not a link (remove it, or set CSM_BIN_DIR)"
    return
  fi
  if [ -L "$2" ] && [ "$(readlink "$2")" != "$1" ]; then
    case "$(readlink "$2")" in
      *claude-session-mover*) ;;
      *) echo "skipped $2: it links to $(readlink "$2")"; return ;;
    esac
  fi
  ln -sfn "$1" "$2"
  echo "linked $2"
}

chmod +x "$tool"
link "$tool" "$bin/claude-session-mover"
if [ "$short" = yes ]; then
  link "$tool" "$bin/csm"
else
  echo "not linking $bin/csm (--no-short-name)"
fi
case ":$PATH:" in
  *":$bin:"*) ;;
  *) echo "note: $bin is not on your PATH" ;;
esac

if [ "$skill" = yes ]; then
  homes=$(python3 "$tool" accounts --json | python3 -c \
    'import json, sys; print("\n".join(a["home"] for a in json.load(sys.stdin)))')
  if [ -z "$homes" ]; then
    echo "no account homes found (see: csm accounts --help)"
    exit 0
  fi
  echo "$homes" | while IFS= read -r home; do
    [ -d "$home" ] || continue
    mkdir -p "$home/skills"
    link "$here/skills/move-session" "$home/skills/move-session"
  done
fi

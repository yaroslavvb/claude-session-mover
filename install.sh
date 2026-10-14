#!/bin/sh
# install.sh: link claude-session-mover (and its short name, csm) into ~/.local/bin.
#   ./install.sh            the command only
#   ./install.sh --skill    also link skills/move-session into every account home's skills/,
#                           because each CLAUDE_CONFIG_DIR reads its own skills directory
# CSM_BIN_DIR overrides ~/.local/bin. Nothing that already exists and is not ours is replaced.
set -eu
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
link "$tool" "$bin/csm"
case ":$PATH:" in
  *":$bin:"*) ;;
  *) echo "note: $bin is not on your PATH" ;;
esac

if [ "${1:-}" = "--skill" ]; then
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

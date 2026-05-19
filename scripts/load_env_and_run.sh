#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [ "$#" -eq 0 ]; then
  echo "Usage: scripts/load_env_and_run.sh <command> [args...]" >&2
  exit 2
fi

if [ ! -f .env ]; then
  echo "Missing .env. Copy .env.example to .env, add OPENAI_API_KEY, then retry." >&2
  exit 1
fi

trim() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "$value"
}

load_line() {
  local line="$1"
  local key=""
  local value=""

  if [[ "$line" =~ ^[[:space:]]*export[[:space:]]+([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]]; then
    key="${BASH_REMATCH[1]}"
    value="${BASH_REMATCH[2]}"
  elif [[ "$line" =~ ^[[:space:]]*([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]]; then
    key="${BASH_REMATCH[1]}"
    value="${BASH_REMATCH[2]}"
  else
    return 1
  fi

  value="$(trim "$value")"
  if [[ "${#value}" -ge 2 ]]; then
    if [[ "${value:0:1}" == "\"" && "${value: -1}" == "\"" ]]; then
      value="${value:1:${#value}-2}"
    elif [[ "${value:0:1}" == "'" && "${value: -1}" == "'" ]]; then
      value="${value:1:${#value}-2}"
    fi
  fi

  export "$key=$value"
}

line_number=0
while IFS= read -r line || [ -n "$line" ]; do
  line_number=$((line_number + 1))
  line="${line%$'\r'}"
  if [[ "$line" =~ ^[[:space:]]*$ || "$line" =~ ^[[:space:]]*# ]]; then
    continue
  fi
  if ! load_line "$line"; then
    echo "Invalid .env line $line_number; expected KEY=VALUE. No secret values were printed." >&2
    exit 1
  fi
done < .env

if [ -n "${OPENAI_API_KEY:-}" ]; then
  echo "OPENAI_API_KEY loaded: true"
else
  echo "OPENAI_API_KEY loaded: false" >&2
  echo "Add OPENAI_API_KEY to .env or run 'make reset-env' if the environment is broken." >&2
  exit 1
fi

"$@"

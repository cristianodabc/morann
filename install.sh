#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
# Installs Morann from this checkout: builds the Python environment it runs in and links the mor command.
#
#   install.sh [--no-link]
#
# The environment is a virtual environment in $MORANN_DATA_DIR/venv-<key> (MORANN_DATA_DIR defaults to
# ${XDG_DATA_HOME:-~/.local/share}/morann), built with the python3 on PATH (3.11 or newer) from requirements.txt: exact
# versions with hashes, wheels only, so nothing builds or runs at install time. `venv` points at the current one. A
# failed build keeps the previous one; an unchanged lock and Python leave everything as it is. Raise a pin only after
# reviewing the new version.
#
# The command is linked as $MORANN_BIN_DIR/mor (default ~/.local/bin) unless --no-link is given, for a caller that
# links its own launcher. MORANN_SKIP_VENV=1 only links the command.
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

link_command=1
for arg in "$@"; do
  case "$arg" in
    --no-link) link_command=0 ;;
    -h | --help)
      sed -n '4,15p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      printf 'install.sh: unknown argument %s\n' "$arg" >&2
      exit 2
      ;;
  esac
done

if [[ "$link_command" == 1 ]]; then
  link="${MORANN_BIN_DIR:-$HOME/.local/bin}/mor"
  mkdir -p "$(dirname "$link")"
  ln -sfn "$root/bin/mor" "$link"
  printf 'Linked: %s\n' "$link"
fi

if [[ "${MORANN_SKIP_VENV:-}" == 1 ]]; then
  printf 'Skipping the Morann Python environment (MORANN_SKIP_VENV=1)\n'
  exit 0
fi

python="$(command -v python3 || true)"
if [[ -z "$python" ]] || ! "$python" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
  printf 'Morann needs python3 3.11 or newer on PATH (found: %s)\n' "${python:-none}" >&2
  exit 1
fi

lock="$root/requirements.txt"
data="${MORANN_DATA_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/morann}"
key="$({
  cat "$lock"
  "$python" -c 'import sys; print(sys.executable, sys.version)'
} | shasum -a 256 | cut -c1-12)"
env_dir="$data/venv-$key"
if [[ -f "$env_dir/.ready" && -L "$data/venv" && "$(readlink "$data/venv")" == "venv-$key" ]]; then
  printf 'Current: %s\n' "$env_dir"
  exit 0
fi

mkdir -p "$data"
rm -rf "$env_dir"
if ! "$python" -m venv "$env_dir" ||
  ! "$env_dir/bin/python" -m pip install --quiet --disable-pip-version-check --no-input \
    --require-hashes --no-deps --only-binary :all: -r "$lock" ||
  ! "$env_dir/bin/python" -I -c 'import rich, textual'; then
  rm -rf "$env_dir"
  printf 'Could not build the Morann environment; the previous one, if any, is kept\n' >&2
  exit 1
fi
: >"$env_dir/.ready"
[[ ! -d "$data/venv" || -L "$data/venv" ]] || rm -rf "$data/venv"
ln -sfn "venv-$key" "$data/venv"
for old in "$data"/venv-*; do
  [[ "$old" == "$env_dir" ]] || rm -rf "$old"
done
printf 'Installed: %s\n' "$env_dir"

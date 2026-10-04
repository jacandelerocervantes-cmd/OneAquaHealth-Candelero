#!/usr/bin/env bash
# lib-guard.sh
# Shared code of the three guard hooks. It is SOURCED by them, never run on its own.
#
# What it does:
#   - Fails CLOSED. When jq is missing, the payload is empty, or the payload is not the JSON object Claude Code sends,
#     the hook exits 2 (block) with an actionable message. Exit codes 127 (command not found) or 5 (jq parse error)
#     would NOT block, so the hooks never let those escape. Intended consequence: a machine without jq blocks every
#     guarded tool call until jq is installed.
#   - Uses shell builtins only up to the jq calls (no cat, no dirname), so a missing jq is diagnosed even when the PATH
#     is empty.
#   - Reads the payload once and exposes:
#       GUARD_TOOL   the tool name ("Bash", "PowerShell", "Read", ...)
#       GUARD_CMD    tool_input.command (a non-string value is kept as JSON text)
#       GUARD_PATHS  newline-separated path-like inputs: file_path, notebook_path, path, glob, and the pattern of Glob
#   - Turns on case-insensitive matching for [[ =~ ]], [[ == ]] and case.

shopt -s nocasematch

guard_fail_closed() {
  {
    echo "GUARDRAIL FAILURE (fail closed): $1"
    echo "The hook could not decide, so the tool call is blocked on purpose."
    echo "Fix: $2"
  } >&2
  exit 2
}

guard_load_payload() {
  if ! command -v jq >/dev/null 2>&1; then
    guard_fail_closed "jq was not found on the PATH." \
      "install jq (Windows: winget install jqlang.jq; Debian or Ubuntu: sudo apt-get install jq; macOS: brew install jq), make sure it is on the PATH of the shell that runs the hooks, and restart the session."
  fi

  INPUT_PAYLOAD=""
  IFS= read -r -d '' INPUT_PAYLOAD || true
  if [[ -z "${INPUT_PAYLOAD//[[:space:]]/}" ]]; then
    guard_fail_closed "the hook received an empty payload on standard input." \
      "check that Claude Code is passing the tool call as JSON on standard input."
  fi

  GUARD_TOOL=$(printf '%s' "$INPUT_PAYLOAD" | jq -r 'if type == "object" then ((.tool_name // "") | tostring) else error("the payload is not a JSON object") end') ||
    guard_fail_closed "the payload is not a valid JSON object (jq could not parse it)." \
      "this is unexpected input from the caller; do not retry the tool call until the cause is known."

  GUARD_CMD=$(printf '%s' "$INPUT_PAYLOAD" | jq -r '(.tool_input // {}) | if type == "object" then ((.command // empty) | if type == "string" then . else tojson end) else error("tool_input is not an object") end') ||
    guard_fail_closed "tool_input is not a JSON object (jq could not read the command)." \
      "this is unexpected input from the caller; do not retry the tool call until the cause is known."

  GUARD_PATHS=$(printf '%s' "$INPUT_PAYLOAD" | jq -r --arg tool "$GUARD_TOOL" '(.tool_input // {}) | [.file_path, .notebook_path, .path, .glob, (if $tool == "Glob" then .pattern else null end)] | map(select(type == "string")) | .[]') ||
    guard_fail_closed "tool_input paths could not be read (jq failed)." \
      "this is unexpected input from the caller; do not retry the tool call until the cause is known."
}

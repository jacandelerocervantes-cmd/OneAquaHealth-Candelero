#!/usr/bin/env bash
# block-destructive-bash.sh
# Guardrail universal de seguridad (PreToolUse / PreCommand / Runner de Hooks).
# Combina dos ideas tomadas de la investigación (créditos abajo):
#   - Denylist estricta de comandos irreversibles (patrón estándar de guardrails).
#   - "Fact-forcing gate" antes de permitir comandos destructivos, inspirado
#     en el patrón GateGuard de affaan-m/ECC (community, MIT-compatible):
#     en vez de solo bloquear, exige que el agente presente evidencia antes
#     de reintentar.
#
# Exit code 2 = bloqueo determinista de guardrail: el contenido de stderr
# se inyecta al agente como razón del rechazo.
#
# Runs for the Bash and PowerShell tools (the command text is tool_input.command in both). Fails closed (see
# lib-guard.sh). The command is also tokenised so that spelling variants are caught: rm flags in any order or in long
# form, git global options before the subcommand (-C dir, -c key=value), "+ref" pushes, git clean/checkout/restore
# of the whole tree. Known limits: shell aliases and functions, variables that hold a command, and base64 or eval
# tricks are not seen (the text is inspected, not the effect).

set -euo pipefail

HOOK_PATH=${BASH_SOURCE[0]//\\//}
if [[ "$HOOK_PATH" == */* ]]; then HOOK_DIR=${HOOK_PATH%/*}; else HOOK_DIR=.; fi
# shellcheck source=lib-guard.sh
if ! source "$HOOK_DIR/lib-guard.sh"; then
  echo "GUARDRAIL FAILURE (fail closed): hooks/lib-guard.sh could not be loaded; tool call blocked on purpose." >&2
  exit 2
fi
guard_load_payload
CMD=$GUARD_CMD

deny_hard() {
  echo "ACCESO DENEGADO POR GUARDRAILS (denylist absoluta):" >&2
  echo "El comando coincide con un patrón irreversible sin excepción: '$CMD'" >&2
  echo "Motivo: $1" >&2
  echo "Esta acción exige ejecución manual directa por un operador humano." >&2
  exit 2
}

deny_soft() {
  cat >&2 <<'EOF'
ACCESO DENEGADO POR GUARDRAILS (fact-forcing gate):

Antes de proponer este comando de nuevo, presenta en tu respuesta:
1. Qué archivos/estado modifica o elimina exactamente este comando.
2. Por qué es necesario ahora mismo (cita la instrucción textual del usuario).
3. Confirmación explícita de que un operador humano ha aprobado esta acción
   en el mensaje de chat actual (no en un turno anterior).

Los commits, pushes y merges de Git deben ser ejecutados manualmente por el
operador humano. Este agente no tiene permitido ejecutarlos bajo ninguna
circunstancia, incluso con la evidencia anterior presentada.
EOF
  echo "Motivo: $1" >&2
  exit 2
}

# --- Denylist absoluta: nunca se permite, ni con "fact-forcing" ---
# Matching is case-insensitive (nocasematch is set by lib-guard.sh).
HARD_DENY=(
  "git[[:space:]]+push[[:space:]]+.*--force"
  "git[[:space:]]+reset[[:space:]]+--hard"
  "drop[[:space:]]+database"
  "truncate[[:space:]]+table"
  ":\(\)\{.*:\|:&\};:"                 # fork bomb
)

for REGEX in "${HARD_DENY[@]}"; do
  if [[ "$CMD" =~ $REGEX ]]; then
    deny_hard "pattern '$REGEX'"
  fi
done

# --- Tokenised checks ---
# Separators and quoting characters become spaces / " ; " so each simple command is its own run of tokens.
NORM=$CMD
NORM=${NORM//$'\r'/ }
NORM=${NORM//$'\n'/ ; }
NORM=${NORM//;/ ; }
NORM=${NORM//|/ ; }
NORM=${NORM//&/ ; }
NORM=${NORM//\"/ }
NORM=${NORM//\'/ }
NORM=${NORM//\`/ }
NORM=${NORM//(/ }
NORM=${NORM//)/ }
set -f
TOKENS=($NORM)
set +f
N=${#TOKENS[@]}

BROAD_TARGET='^(/|/\*|~|~/|~/\*|\.|\./|\./\*|\.\.|\.\./|\.\./\*|\*|\.\*|\$HOME|\$HOME/|\$HOME/\*|\$\{HOME\}|\$\{HOME\}/|\$\{HOME\}/\*|\$PWD|\$env:(userprofile|homepath|homedrive)|[a-z]:[\\/]?|[a-z]:[\\/]\*|\\|\\\*)$'
PS_RECURSE='^-r(e(c(u(r(s(e)?)?)?)?)?)?$'
PS_FORCE='^-fo(r(c(e)?)?)?$'

# scan_rm START: tokens from START up to the next ";" are the arguments of rm / Remove-Item / del / rd.
# Sets NEXT_INDEX to the index of the terminating ";" (or N).
scan_rm() {
  local j=$1 name=$2 tok recursive=0 force=0 broad=0
  while (( j < N )); do
    tok=${TOKENS[j]}
    [[ "$tok" == ";" ]] && break
    if [[ "$tok" == "--no-preserve-root" ]]; then
      deny_hard "rm --no-preserve-root"
    elif [[ "$tok" == --* ]]; then
      [[ "$tok" == "--recursive" ]] && recursive=1
      [[ "$tok" == "--force" ]] && force=1
    elif [[ "$tok" =~ $PS_RECURSE && ${#tok} -ge 3 ]]; then
      recursive=1
    elif [[ "$tok" =~ $PS_FORCE ]]; then
      force=1
    elif [[ "$tok" =~ ^-[a-zA-Z]+$ ]]; then
      [[ "$tok" == *r* ]] && recursive=1
      [[ "$tok" == *f* ]] && force=1
    elif [[ "$tok" == "/s" && "$name" != rm ]]; then
      recursive=1                       # cmd.exe: rd /s, del /s
    elif [[ "$tok" == "/q" && "$name" != rm ]]; then
      force=1                           # cmd.exe: quiet, no prompt
    elif [[ "$tok" =~ $BROAD_TARGET ]]; then
      broad=1
    fi
    j=$((j + 1))
  done
  NEXT_INDEX=$j
  if (( recursive == 1 && (force == 1 || broad == 1) )); then
    deny_soft "recursive removal ($name) with force or on a broad path (rm -rf, rm -fr, rm -r -f, rm --recursive --force, Remove-Item -Recurse -Force, rd /s /q)"
  fi
}

# scan_git START: tokens from START up to the next ";" are the arguments of a git command line.
scan_git() {
  local j=$1 sub="" tok arg staged=0 worktree=0
  # Skip git's global options (-C dir, -c key=value, --git-dir, ...) to find the subcommand.
  while (( j < N )); do
    tok=${TOKENS[j]}
    case "$tok" in
      ";") break ;;
      -C | -c | --git-dir | --work-tree | --namespace | --super-prefix | --config-env) j=$((j + 2)) ;;
      -*) j=$((j + 1)) ;;
      *) break ;;
    esac
  done
  (( j < N )) || { NEXT_INDEX=$N; return 0; }
  sub=${TOKENS[j]}
  if [[ "$sub" == ";" ]]; then NEXT_INDEX=$j; return 0; fi
  j=$((j + 1))

  local has_force_flag=0 has_hard_flag=0 has_plus_ref=0 has_whole_tree=0 has_dry_run=0
  while (( j < N )); do
    arg=${TOKENS[j]}
    [[ "$arg" == ";" ]] && break
    [[ "$arg" == --force* || "$arg" =~ ^-[a-zA-Z]*f[a-zA-Z]*$ ]] && has_force_flag=1
    [[ "$arg" == "--hard" ]] && has_hard_flag=1
    [[ "$arg" == +* ]] && has_plus_ref=1
    [[ "$arg" == "." || "$arg" == ":/" || "$arg" == ":/*" || "$arg" == "*" || "$arg" == ":(top)" ]] && has_whole_tree=1
    [[ "$arg" == "--staged" || "$arg" == "-S" ]] && staged=1
    [[ "$arg" == "--worktree" || "$arg" == "-W" ]] && worktree=1
    j=$((j + 1))
  done
  NEXT_INDEX=$j

  case "$sub" in
    commit | merge)
      deny_soft "git $sub (Git commits and merges are the maintainer's, including through -C or -c)"
      ;;
    push)
      if (( has_force_flag == 1 )); then deny_hard "git push with a force flag"; fi
      if (( has_plus_ref == 1 )); then deny_hard "git push with a +ref (forced update)"; fi
      deny_soft "git push (pushes are the maintainer's, including through -C or -c)"
      ;;
    reset)
      if (( has_hard_flag == 1 )); then deny_hard "git reset --hard"; fi
      ;;
    clean)
      if (( has_force_flag == 1 )); then deny_hard "git clean with -f discards untracked files for good"; fi
      ;;
    checkout)
      if (( has_force_flag == 1 )); then deny_hard "git checkout --force discards local changes"; fi
      if (( has_whole_tree == 1 )); then deny_hard "git checkout of the whole tree discards local changes"; fi
      ;;
    restore)
      if (( has_whole_tree == 1 )) && ! { (( staged == 1 )) && (( worktree == 0 )); }; then
        deny_hard "git restore of the whole tree discards local changes"
      fi
      ;;
  esac
}

i=0
while (( i < N )); do
  tok=${TOKENS[i]}
  tok=${tok#\\}
  base=${tok##*/}
  base=${base##*\\}
  base=${base%.exe}
  NEXT_INDEX=$((i + 1))
  case "$base" in
    rm | ri | del | erase | rd | rmdir | remove-item)
      scan_rm $((i + 1)) "$base"
      ;;
    git)
      scan_git $((i + 1))
      ;;
  esac
  # Resume at the terminator (or just after the command word when it had no arguments).
  if (( NEXT_INDEX > i )); then i=$NEXT_INDEX; else i=$((i + 1)); fi
done

# --- Denylist condicionada (legacy patterns, kept as a second net): bloquea, pero exige evidencia ---
SOFT_DENY=(
  "git[[:space:]]+commit"
  "git[[:space:]]+push"
  "git[[:space:]]+merge"
  "rm[[:space:]]+-[a-zA-Z]*r[a-zA-Z]*f"
)

for REGEX in "${SOFT_DENY[@]}"; do
  if [[ "$CMD" =~ $REGEX ]]; then
    deny_soft "pattern '$REGEX'"
  fi
done

exit 0

#!/usr/bin/env bash
# protect-secrets.sh
# Guardrail universal de seguridad (PreToolUse / PreFileAccess / Runner de Hooks).
# Bloquea lectura/escritura de archivos con credenciales o llaves privadas.
#
# Runs for Bash, PowerShell, Read, Edit, Write, NotebookEdit, Grep and Glob, and fails closed (see lib-guard.sh).
# Inputs inspected: the paths of the file tools (file_path, notebook_path, path, glob, and the pattern of Glob) and the
# text of shell commands. Patterns only ever ADD protection; nothing here unblocks a name.
#
# Known limits: Grep over a directory without a path or glob that names a secret file reads whatever ripgrep walks
# (it honours .gitignore); a secret reached through a variable, a symlink, or a computed name is not seen.

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

# A service-account or credentials file: name contains the words and the extension is a data format.
SECRET_FILE_NAME='[^/\\[:space:]]*(service[-_]?account|credentials)[^/\\[:space:]]*\.(json|ya?ml|csv|txt)(\.[a-zA-Z0-9_-]+)?'

# Whole-path patterns (anchored at the end of the path).
SECRET_PATH_PATTERN="(\.env(\..*)?|\.pem|credentials\.json|id_rsa|id_ed25519|\.pfx|\.p12|\.p8|\.key|\.jks|\.tfvars(\.json)?|\.tfstate(\.[^/\\\\]*)?|[._]npmrc|[._]netrc|${SECRET_FILE_NAME}|(^|[/\\\\])credentials)\$"

# Patterns for free text (a shell command), not anchored.
SECRET_CMD_PATTERN="(\.env(\.[a-zA-Z0-9_.-]*)?|\.pem|credentials\.json|id_rsa|id_ed25519|\.pfx|\.p12|\.p8([^a-zA-Z0-9_]|\$)|\.key([^a-zA-Z0-9_]|\$)|\.jks|\.tfvars|\.tfstate|[._]npmrc|[._]netrc|${SECRET_FILE_NAME}|(^|[/\\\\[:space:]])credentials([[:space:]]|\$))"

# Representative names a shell glob could expand to. A glob token is blocked when it matches one of them, unless it
# is a "match everything" glob (only *, ?, [, ] and dots), which would block every ls and every grep.
SECRET_GLOB_SAMPLES=(
  ".env" ".env.local" ".env.production" ".env.example" "server.pem" "server.key" "server.p8" "server.p12" "server.pfx"
  "keystore.jks" "terraform.tfvars" "terraform.tfstate" "terraform.tfstate.backup" ".npmrc" ".netrc" "_netrc"
  "id_rsa" "id_ed25519" "credentials" "credentials.json" "service-account.json" "service_account.json"
)

# Bracket expression with "]" first and "[" last so that both are literal: a name made only of ] * ? . [ .
MATCH_EVERYTHING='^[]*?.[]+$'

deny_secret() {
  echo "ACCESO DENEGADO POR SEGURIDAD:" >&2
  echo "$1" >&2
  echo "Si necesitas una variable de este archivo, pide al operador humano" >&2
  echo "que la exponga explícitamente en el chat o en una variable de entorno." >&2
  exit 2
}

# glob_may_hit_secret TOKEN: true when TOKEN contains glob characters and could expand to a secret-file name.
glob_may_hit_secret() {
  local token=$1 base sample
  base=${token##*/}
  base=${base##*\\}
  [[ "$base" == *[\*\?\[]* ]] || return 1
  [[ "$base" =~ $MATCH_EVERYTHING ]] && return 1
  for sample in "${SECRET_GLOB_SAMPLES[@]}"; do
    # shellcheck disable=SC2053
    [[ "$sample" == $base ]] && return 0
  done
  [[ "$base" =~ ^\*?(cred|service[-_]?acc|id_) ]] && return 0
  return 1
}

# --- Paths given to the file tools (Read, Edit, Write, NotebookEdit, Grep, Glob) ---
if [[ -n "$GUARD_PATHS" ]]; then
  OLD_IFS=$IFS
  IFS=$'\n'
  set -f
  for TARGET_PATH in $GUARD_PATHS; do
    TARGET_PATH=${TARGET_PATH%$'\r'}
    if [[ "$TARGET_PATH" =~ $SECRET_PATH_PATTERN ]]; then
      IFS=$OLD_IFS
      deny_secret "Manipulación bloqueada sobre archivo confidencial: '$TARGET_PATH'"
    fi
    if glob_may_hit_secret "$TARGET_PATH"; then
      IFS=$OLD_IFS
      deny_secret "Patrón de archivos bloqueado porque podría coincidir con un archivo confidencial: '$TARGET_PATH'"
    fi
  done
  set +f
  IFS=$OLD_IFS
fi

# Also block reading secret files through Bash or PowerShell (cat/type/Get-Content/etc.), not just
# through the file tools -- a bare file path check on tool_input.file_path
# does not see a shell command that names the same path as an argument.
if [[ -n "$CMD" ]]; then
  if [[ "$CMD" =~ $SECRET_CMD_PATTERN ]]; then
    deny_secret "Comando bloqueado por referenciar un archivo confidencial: '$CMD'"
  fi
  NORM=${CMD//$'\n'/ }
  NORM=${NORM//$'\r'/ }
  NORM=${NORM//;/ }
  NORM=${NORM//|/ }
  NORM=${NORM//&/ }
  NORM=${NORM//\"/ }
  NORM=${NORM//\'/ }
  NORM=${NORM//\`/ }
  NORM=${NORM//(/ }
  NORM=${NORM//)/ }
  NORM=${NORM//,/ }
  NORM=${NORM//=/ }
  set -f
  for WORD in $NORM; do
    if glob_may_hit_secret "$WORD"; then
      set +f
      deny_secret "Comando bloqueado: el patrón '$WORD' podría expandirse a un archivo confidencial: '$CMD'"
    fi
  done
  set +f
fi

exit 0

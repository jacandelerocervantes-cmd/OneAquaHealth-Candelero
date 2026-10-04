#!/usr/bin/env bash
# block-network-exposure.sh
# Guardrail universal de seguridad (PreToolUse / PreCommand / Runner de Hooks).
# Adaptado del principio "regla de oro: superficie de ataque externa = 1
# punto, no N" documentado en el paquete IA CON del usuario (documento
# 13-Ciberseguridad-Pilares.md): ninguna pieza de infraestructura, salvo el
# gateway/API pública designada, debe quedar alcanzable desde internet.
#
# Bloquea comandos que abrirían ingress público, deshabilitarían auth, o
# expondrían un panel administrativo — antes de que se ejecuten, no después
# de que security-engineer lo detecte en auditoría.
#
# Runs for the Bash and PowerShell tools and fails closed (see lib-guard.sh). Opening public access to the Cloud Run
# service is a deliberate MANUAL step of the maintainer (docs/predeploy_checklist.md, section 1): this hook blocks every
# route an agent could use for it, on purpose: the unauthenticated flag, an IAM binding for allUsers or
# allAuthenticatedUsers (gcloud run services add-iam-policy-binding, also the beta and alpha forms), a set-iam-policy
# call (the policy file cannot be inspected), --no-invoker-iam-check, and --ingress all.

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

GCLOUD='gcloud(\.cmd|\.exe|\.ps1)?'

NETWORK_EXPOSURE_PATTERNS=(
  "${GCLOUD}[[:space:]].*--allow-unauthenticated"
  "${GCLOUD}[[:space:]].*--no-invoker-iam-check"
  "${GCLOUD}[[:space:]].*--ingress([[:space:]]+|=)['\"]?all(['\"]|[[:space:]]|\$)"
  "${GCLOUD}[[:space:]].*sql.*--assign-ip"
  # Public invocation through IAM: any add-iam-policy-binding that names allUsers or allAuthenticatedUsers
  # (member before or after the subcommand), and any set-iam-policy on a Cloud Run service or job.
  "${GCLOUD}[[:space:]].*add-iam-policy-binding.*all(authenticated)?users"
  "${GCLOUD}[[:space:]].*all(authenticated)?users.*add-iam-policy-binding"
  "${GCLOUD}[[:space:]].*run[[:space:]].*set-iam-policy"
  "aws[[:space:]].*ec2.*authorize-security-group-ingress.*0\.0\.0\.0/0"
  "terraform(\.exe)?[[:space:]]+(-[^[:space:]]+[[:space:]]+)*(apply|destroy)"    # requiere revisión de plan humana siempre
  "kubectl[[:space:]].*expose.*--type=LoadBalancer"
  # Local/process-level exposure vectors (added 2026-09-21 after security-engineer audit):
  # binding a local dev server to all interfaces, or tunneling one to the public internet.
  "(--host|host[[:space:]]*=)[[:space:]]*['\"]?0\.0\.0\.0"
  "uvicorn[[:space:]].*0\.0\.0\.0"
  "ngrok[[:space:]]"
  "localtunnel|lt[[:space:]]+--port"
  "cloudflared[[:space:]]+tunnel"
  "python[0-9.]*[[:space:]]+-m[[:space:]]+http\.server"
  "ssh[[:space:]].*-R[[:space:]]"
)

for REGEX in "${NETWORK_EXPOSURE_PATTERNS[@]}"; do
  if [[ "$CMD" =~ $REGEX ]]; then
    cat >&2 <<EOF
ACCESO DENEGADO POR GUARDRAILS DE RED:

Este comando expondría infraestructura a acceso público o no autenticado:
'$CMD'

Regla del proyecto: ninguna pieza salvo el gateway/API designado debe
tener una dirección alcanzable desde internet. Esta acción requiere
revisión y ejecución manual explícita por un operador humano, nunca
automatizada por el agente.
EOF
    exit 2
  fi
done

exit 0

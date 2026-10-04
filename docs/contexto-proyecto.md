# Perfil de Contexto Individual del Proyecto

<!-- Generado y actualizado por auditar-proyecto-existente (nivel experto). Todo agente debe leer esto antes de planificar o generar código, junto con AGENTS.md y docs/handoff/LEDGER.md. -->

## 0. Metadatos de Gobernanza

- **Nombre del proyecto:** OneAquaHealth
- **Tipo de proyecto:** Académico / hackathon (envío a un desafío OneAquaHealth / HL7 Europe; ver los dos PDF en la raíz)
- **Nivel de asistencia preferido:** Experto (confirmado por el usuario, 2026-09-26)
- **Estado de madurez estimado:** 60-95% ("Cerca del lanzamiento" en lógica de dominio y backend; frontend en prototipo inicial; 0% en higiene de control de versiones Git)
- **Fecha de última auditoría:** 2026-09-26

---

## 1. Misión y Dominio de Negocio

- **Propósito principal:** Pipeline reproducible y auditable que ingesta datos del sandbox público OneAquaHealth (calidad de agua / salud ambiental), aplica control de calidad (QC), valida y exporta recursos FHIR R4/R4B con Provenance, calcula índices ecológicos (BMWP/ASPT/EPT, diversidad, CCME WQI, EQR), modela fiabilidad de observadores ciudadanos (Dawid-Skene) sobre campañas sintéticas, aplica predicción conformal con cola de revisión humana, generaliza ubicaciones con k-anonimato, propaga riesgo en una red fluvial, genera explicabilidad con LLM protegida contra inyección/costos, y expone todo mediante una API FastAPI y un frontend React/Vite.
- **Público objetivo:** [COMPLETAR: evaluadores del hackathon / equipo HL7 Europe OneAquaHealth — confirmar con el usuario]
- **Regulaciones y cumplimiento normativo:** FHIR R4 (HL7 Implementation Guide oficial extraído en `ig/oah`); directivas ambientales y sanitarias de la UE (2008/105/EC, 2013/39/EU, 2020/2184, 2000/60/EC); EU AI Act (Anexo III para sistemas de alerta temprana e infraestructuras críticas de agua). [COMPLETAR: confirmación formal de aplicación de GDPR sobre Location/Observation del sandbox público].
- **Sensibilidad de datos:** Sandbox público de solo lectura (390 Observations reales sobre 17 Location; incluye 141 observaciones de tipo salud poblacional agregada). Datos sintéticos de campañas ciudadanas explícitamente etiquetados (`meta.tag = "synthetic"`) y estrictamente segregados de datos reales.

---

## 2. Glosario del Dominio

| Término | Significado exacto en este proyecto | Nunca confundir con |
|---|---|---|
| `origin` (real-sandbox / synthetic) | Etiqueta obligatoria en toda respuesta de API/reporte que distingue datos reales del sandbox de datos simulados | Un campo de auditoría genérico; aquí gobierna qué resultados pueden citarse como reales |
| QC finding | Hallazgo inmutable producido por `oah.qc`, nunca modifica el recurso origen | Una corrección automática o un "fix" aplicado a los datos |
| Conformal set | Conjunto de predicción con garantía de cobertura estadística (split conformal), no una probabilidad puntual | Un simple top-k de clases más probables |
| Riesgo propagado (`oah.risk`) | Valor `initial_risk * exp(-decay*distancia)` sobre topología **explícitamente suministrada**, nunca inventada | Un modelo hidrológico real o topología de red fluvial verdadera |
| R4B (validación estructural) | Nivel de validación estructural usado porque `fhir.resources` no soporta R4 4.0.1 puro | Validación de conformidad completa contra el IG oficial (realizada por el validador HL7 Java externo) |
| Evidence grounding (`oah.explain`) | Verificación estricta de que cada afirmación del LLM se apoya en datos calculados previamente | Un simple chequeo de longitud o formato de respuesta del LLM |

---

## 3. Stack Tecnológico Real

- **Lenguaje(s) principal(es):**
  - Backend: Python, `requires-python = ">=3.11,<3.13"` (verificado en 3.12 x64)
  - Frontend: TypeScript (~6.0.2)
- **Runtime y gestores de paquetes:**
  - Backend: pip + `hatchling==1.27.0` como build backend
  - Frontend: Node.js + npm, Vite 8.3.0
- **Framework Frontend:** React 19.2.8 + React Router DOM 7.18.4 + React-Leaflet 5.0.0 + Leaflet 1.9.4 + i18next 26.4.2
- **Framework Backend:** FastAPI 0.141.1 + Starlette 1.6.0 (pin explícito por CVE-2026-48710) + uvicorn 0.34.0
- **Base(s) de datos y ORM:** SQLite sin ORM (`sqlite3` directo) en `oah.store.review_store`, con triggers `BEFORE UPDATE`/`BEFORE DELETE` que fuerzan inmutabilidad de `audit_events` a nivel de motor. La base de datos se almacena obligatoriamente fuera del árbol del repositorio.
- **Servicios de IA / Modelos:**
  - Inferencia estadística local: EM de Dawid-Skene (`oah.reliability`) y predicción conformal dividida (`oah.uncertainty`) sobre NumPy 2.3.3 / NetworkX 3.5.
  - LLM Cloud: Anthropic Claude (`anthropic==1.7.0`) para `/explain/*`, gobernado por `oah.api.llm_guard` (presupuesto diario de 100 llamadas, rate limit de 5/min, TTL cache) y `oah.explain.safety` (defensa contra prompt injection y barrera de no-prescripción de potabilidad).
- **Infraestructura y hosting:** Local (`scripts/run_api.py` para uvicorn, `npm run dev` para frontend Vite). Sin orquestación Docker Compose ni CI/CD formalizada.

---

## 4. Arquitectura y Convenciones de Código

- **Patrón arquitectónico:** Monolito modular desacoplado en capas de dominio:
  - Backend (`src/oah`): `ingest → qc → fhir → indices/reliability/uncertainty → review/risk/privacy → explain → audit/api`
  - Frontend (`frontend/src`): `main.tsx → App.tsx → pages/Home.tsx`, cliente API centralizado en `api.ts`, internacionalización en `i18n.ts`.
- **Límites de líneas (`AGENTS.md` §3.11 del stack; límite 400-500 para core, 200-300 para UI/utils):**
  - **Infracción detectada:** `src/oah/indices/apply_to_sandbox.py` (510 líneas — SUPERA el límite de 500 líneas).
  - En zona límite: `tests/unit/test_api.py` (401 líneas), `src/oah/api/app.py` (381 líneas).
  - Componentes UI/utilidades en rango aceptable (<100 líneas en frontend).
- **Convenciones de nomenclatura:** `snake_case` en Python; `PascalCase` en clases y componentes React; `SCREAMING_SNAKE_CASE` en variables de entorno.

---

## 5. Comandos de Verificación y Calidad

- **Chequeo de tipos:**
  - Backend: `mypy` configurado en `pyproject.toml` (`python_version = "3.11"`, `files = ["src", "scripts", "tests"]`).
  - Frontend: `tsc -b` (configurado en `tsconfig.json`).
- **Linter:**
  - Backend: `ruff` configurado en `pyproject.toml` (`select = ["E", "F", "W"]`, `ignore = ["E501"]`).
  - Frontend: `oxlint` configurado en `.oxlintrc.json`.
- **Tests unitarios e integración:**
  - Backend: `pytest` configurado en `pyproject.toml` (~830 tests pasando, cobertura >95% con `fail_under = 95`).
  - Frontend: **Ausente** (no existe script de tests ni configuración de Vitest/Jest en `frontend/package.json`).
- **Build de producción:**
  - Backend: `hatchling` (wheel buildable).
  - Frontend: `npm run build` (`tsc -b && vite build`).

---

## 6. Reglas Intocables, Seguridad y Guardrails

1. **Variables de entorno:** `src/oah/config.py` define y lee 12 variables (`OAH_DATA_DIR`, `OAH_SANDBOX_URL`, `OAH_SOURCES_ROOT`, `OAH_LLM_MODEL`, `ANTHROPIC_API_KEY`, `OAH_API_KEY`, `OAH_CORS_ORIGINS`, `OAH_RATE_LIMIT_MAX_REQUESTS`, `OAH_RATE_LIMIT_WINDOW_SECONDS`, `OAH_EXPLAIN_RATE_LIMIT_PER_MINUTE`, `OAH_EXPLAIN_DAILY_CAP`, `OAH_EXPLAIN_CACHE_TTL_SECONDS`). **Brecha detectada:** `.env.example` solo documenta 6 de las 12 variables.
2. **Control de commits y Git:** Solo 1 commit histórico (`98a7b63`). Todo el desarrollo activo permanece uncommitted en el working tree debido a la regla de deferir commits de agentes. Requiere backup preventivo o commit manual por el usuario.
3. **Guardrails activos:** `hooks/block-destructive-bash.sh`, `hooks/block-network-exposure.sh` y `hooks/protect-secrets.sh` integrados como `PreToolUse` en `.claude/settings.json`. Faltan `delivery-gate.py`, `test-hooks.sh`, pre-commit de git y adaptadores (`CLAUDE.md`, `.cursorrules`).
4. **Higiene de directorios sincronizados:** `.venv` y `frontend/node_modules` residen en la raíz del proyecto, en contradicción con la política de mantener entornos y cachés fuera del árbol sincronizado.
5. **Seguridad de API:** Cabeceras defensivas estrictas (CSP, nosniff, DENY, no-referrer, no-store), CORS parametrizado, rate limiting general y por endpoint de IA, validación de esquemas y sanitización de prompts.

# Bitácora — cuaderno de laboratorio

> Cuaderno personal del proyecto. Se lleva en español por elección del autor
> (el resto del repo sigue la convención en inglés). Entradas en orden
> cronológico; los hallazgos se registran con fecha, evidencia y estado.

## 2026-10-26 — Pipeline de quality checks post-run (metodología COVA-X)

Implementación del quality lifecycle del paper de expansión de dataset
(`dataset-expantion-quality-check.pdf`), adaptado al dominio email+SMS:

- **Escaneo de artefactos de generación** (`quality_agent/artifacts.py`,
  análogo a `scan_generation_quality.py`): `dialogue_collapse`,
  `stage_direction`, `turn_overflow`, `meta_bleed`, `loop_detection`.
- **Escaneo de contaminación** (`quality_agent/contamination.py`, §IV-C):
  bleed de léxico entre pretextos (umbral: ≥ 2 términos distintos de otro
  pretexto — un solo término compartido es ruido, ver hallazgo abajo),
  drift de nombres del roster + artefactos de nombre concatenado
  ("RebeccaBruno"), mención de marca equivocada, y script no-latino.
- **Stripping de stage directions** (`quality_agent/strip.py`, §IV-D):
  medido sobre copia, nunca aplicado — el artefacto entregado queda intacto y
  las stats (`affected_messages`, `stripped_chars`) son el número análogo a la
  tasa de turnos afectados del paper.
- **Auditoría automática de etiquetas** (`quality_agent/labels.py`, §IV-E):
  labeler determinístico por léxicos (pretext, tone, difficulty); status por
  etiqueta `ok | mismatch | unverifiable`. `mismatch` = análogo a la
  corrección de labels del paper (49.8% → 3.9%); `unverifiable` = hallazgos
  diferidos.
- **Integración en cada run:** `measurement/runner.py` graba las variables de
  calidad en cada `RunRecord` (junto a las existentes: `failing_checks`,
  `raw_link_violations`, `first_attempt_raw_link_violations`, `n_attempts`,
  `refined`); `reliability.py` agrega tasas de flags/contaminación/corrección
  y el `summary.md` las reporta; suite dedicada
  `python -m measurement.quality` escribe `quality.json` +
  `quality-summary.md` con el desglose por pretexto (análogo a la Tabla II).
  El shell (`/generate`, `/replay`) guarda `quality_report.json` en cada run y
  suma el comando `/quality`.
- **Contrato nuevo:** `QualityReport`/`QualityCheckResult`/`QualityFinding`/
  `LabelAudit`/`StripStats` en `app/core/schemas.py` + persistencia
  `quality-reports`; documentado como contrato #8 en `docs/flow-schema.md`.
- **Cadena de evidencia de tres puntos (mapeo §IV-B):** en este repo la
  cadena equivalente ya existía para links (raw primer intento → raw
  post-refinamiento → post-ensamblador); el quality scan agrega la cuarta capa
  de contenido (artefactos + contaminación + labels) sobre el artefacto
  entregado.

Hallazgos del proceso:

- El fixture de links conocido (`known-case/generated_campaign.json`) es un
  executive_request sobre pago de vendor: "payment" aparece 3× pero es
  contenido legítimo de ese pretexto. El umbral de contaminación se ajustó a
  ≥ 2 términos *distintos* de otro pretexto (un solo término no dispara).
- El caso `ceo_self_impersonation` no lo detecta el quality scan — lo detecta
  el check `sender_recipient` del validador. División de responsabilidades
  correcta: coherencia estructural ≠ calidad de contenido.
- El labeler reporta `unverifiable` (empate/ausencia de señal) en vez de
  forzar un mismatch — decisión deliberada, análoga a los hallazgos diferidos
  del paper.

Commits: `feat(quality): post-run quality lifecycle scan (COVA-X methodology)…`

---

## 2026-10-08 — Revisión de diseño: tres resultados que no median lo que parecían

Revisión del mentor sobre los resultados centrales. Resumen y resolución:

### H1 · El 0/10 de `link_consistency` medía el ensamblador, no el modelo

- **Qué pasaba:** `normalize_body_links` reescribe cualquier token del cuerpo
  al token correcto, así que el check no puede fallar por construcción. El
  0/10 "after" es una garantía de entrega, no una métrica del LLM.
- **Qué se hizo:** el ensamblador ahora registra cada reescritura en
  `link_fixes` de cada mensaje; el harness reporta **dos números**:
  - *raw (pre-ensamblador)* = tasa de violación del LLM crudo → métrica de
    **fiabilidad del generador** (primer intento; la normalización no dispara
    reintentos);
  - *post-ensamblador* = tasa de fallo del artefacto entregado → **garantía
    de entrega** (0 por construcción para links).
- **Pendiente:** las corridas históricas (2026-09-23) no grabaron
  `link_fixes`; hay que **re-correr la suite con el adapter real** para
  obtener el número raw. Ambos van al paper, no son lo mismo.
- Commits: `feat(measure): report raw pre-assembler link violations…`,
  `fix(provenance): log the sampling params actually used…`.

### H2 · La afirmación de reproducibilidad no cuadraba con la procedencia

- **Qué pasaba:** los docs decían temperatura 0 (y la llamada real **sí** usa
  0.0 vía `LiteLlm`), pero cada registro de procedencia logueaba 0.7 (email)
  y 0.6 (SMS): el log mentía.
- **Qué se hizo:** procedencia registra los params realmente usados
  `{"temperature": 0.0, "seed": 42}` (`top_p`/`max_tokens` quedan en defaults
  del proveedor y no se loguean); `runtime.seed_supported = false` porque el
  seed solo alimenta la capa determinista y **no se pasa al proveedor**.
- **Hallazgo del experimento de reproducibilidad (se mantiene):** la capa
  determinista es byte-idéntica entre corridas; la prosa del LLM varía
  ligeramente entre llamadas **incluso a temperatura 0**. El no-determinismo
  viene del proveedor, no del código.
- Commits: `fix(provenance): log the sampling params actually used…`.

### H3 · Una campaña semánticamente rota pasó los 4 checks

- **Qué pasaba:** la corrida S1 de `reproduce-adk/` tiene a la CEO
  escribiéndose a sí misma ("Elena, I'm finalizing…", firmado "— Elena").
  Ninguno de los cuatro validadores comparaba remitente contra destinatario.
- **Qué se hizo:**
  - `GeneratedCampaign` ahora lleva el `recipient`; nuevo 5º check
    `sender_recipient` (la persona suplantada jamás puede ser el destinatario;
    sin recipient registrado, falla: no verificable ≠ limpio).
  - **Deliberadamente no** se aplica en el schema: si la construcción lo
    arreglara, el check sería vacuo (el mismo error de H1).
  - Evidencia preservada: `data/measurements/known-case/ceo_self_impersonation.json`
    + test de regresión.
- **Dato para el estudio:** la suite no detecta todo, y saber qué no detecta
  es parte del resultado. Anotado en `data/measurements/README.md` §3.
- Commits: `feat(validate): add sender_recipient check…`.

### H4 · Modelos abliterated/uncensored descartados del diseño

- **Decisión:** fuera del catálogo (`docs/models.md` reescrito). Una revisión
  dual-use los rechazaría, y el argumento de "realismo" no se sostiene: un
  Llama 3.1 estándar bien prompteado en contexto de investigación genera
  mensajes igual de realistas (o mejores — el abliteration degrada calidad),
  porque es el mismo modelo sin el filtro.
- **Para el estudio cross-family:** instruct estándar, abiertos, locales —
  Llama 3.1 8B, Qwen 2.5 7B/14B, Mistral 7B (opcional Gemma 2 9B).
- **Pendiente:** determinar cuál es el mejor que corre la compu (VRAM/RAM),
  cablearlo como segunda familia junto a `deepseek-chat`, y registrar
  modelo/cuantización/adapter en la procedencia.
- Commits: `docs(models): drop abliterated/uncensored catalog…`.

### Menores atendidos

- **Commits regulares:** de aquí en adelante, un commit por cambio enfocado
  (esta entrada documenta los 7 commits de hoy).
- **README llenado** (dejó de ser plantilla: nombre, badges reales, env vars,
  sección de configuración honesta).
- **Bitácora iniciada** (este archivo).
- **Enum de pretextos separado:** `Pretext.category` ∈ {consumer, bec}.
  Consumer: `password_reset`, `account_suspension`, `package_delivery`.
  BEC: `executive_request`, `invoice_payment`, `shared_document`,
  `hr_notice`, `it_support`.
- Commits: `docs(readme): fill in the template placeholders`,
  `refactor(schemas): tag pretexts by scenario category…`.

---

## 2026-09-23 — Mediciones before/after del fix de links

- `reliability-adk-20260923T185148Z/` (generador roto): 10/10 campañas con
  violación, todas por `link_consistency`.
- `reliability-adk-20260923T195458Z/` (generador arreglado): 0/10.
  → Con la reinterpretación de H1, ese 0/10 es la **garantía post-ensamblador**;
  la tasa raw de esa corrida no quedó registrada.
- `reproduce-adk-fixed/`: capa determinista idéntica entre runs; prosa varía.
- Evidencia del bug cross-channel preservada en `known-case/generated_campaign.json`
  (`abc123` vs `d6db8064874a`).

## 2026-09-07 — Primera evidencia commiteada

- `data/q3-awareness-2026/generated_campaign.json` (adapter deepseek directo,
  pre-ADK): primer sample con el bug cross-channel de links; luego copiado a
  `known-case/` como fixture de regresión.

---

## Abierto / siguiente

- [ ] Re-correr `python -m measurement.reliability --adapter adk --runs 1` con
      la suite que ya reporta el número raw → el par de tasas para el paper.
- [ ] Definir el modelo local (Llama 3.1 / Qwen 2.5 / Mistral) según hardware
      y montar el segundo adapter.
- [ ] Decidir licencia (README marca "TBD").
- [ ] Considerar `seed` soportado por el proveedor para prosa reproducible
      (hoy `seed_supported: false` es el resultado honesto).

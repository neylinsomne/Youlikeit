# 0003 · CATALOG fijo curado (los briefs solo dan boost)

- **Status:** accepted
- **Date:** 2026-06-02 (decisión tomada antes; documentada retroactivamente)
- **Deciders:** owner del repo
- **Fuente original:** [MLOPS_FLOW.md § Decisiones de diseño 4](../MLOPS_FLOW.md) + `content_rotator.CATALOG`

## Context and Problem Statement

Las señales de mercado (`market_signals` → `persona_briefs`) descubren qué está
consumiendo el mundo. La pregunta: ¿los briefs deben **generar dinámicamente**
qué serie producir, o el catálogo de series producibles es **fijo y curado** y
los briefs solo influyen en el orden?

## Decision Drivers

- Calidad editorial: cada serie del `CATALOG` tiene assets y tratamiento curados.
- Evitar producir contenido sobre algo de lo que no tenemos material ni criterio.
- Mantener el scoring del rotator interpretable (pesos como priors razonables, no aprendidos).
- No tenemos aún datos de outcome (retención) suficientes para un ranking aprendido.

## Considered Options

1. **CATALOG fijo curado**; los briefs aportan `briefs_boost` al score del rotator.
2. **Briefs generan el catálogo dinámicamente** (producir lo que sea que trending).
3. Catálogo fijo + auto-expansión cuando un brief sin match supere un umbral.

## Decision Outcome

Elegida la **opción 1**. El `CATALOG` (en `content_rotator.py`, ~40 slugs en 4
dominios) es la fuente de verdad de **qué se puede producir**. `brief_resolver`
mapea briefs a slugs del CATALOG (alias map + fuzzy ≥75); los que no matchean van
a `unresolved_briefs_queue` para **curación humana**, no a producción automática.
El score del rotator suma `briefs_boost(slug, persona)` — los briefs **influyen
el orden**, no crean entradas.

### Consequences

**Buenas:**
- Garantiza que solo producimos sobre series con assets y tratamiento curados.
- El humano decide cuándo expandir el CATALOG (vía la unresolved queue).
- Scoring interpretable; el A/B aísla el tono (ver [0001](0001-why-algorithmic-not-llm.md)).

**Malas / trade-offs:**
- El CATALOG puede quedarse atrás de un trend que no esté curado todavía →
  mitigado por la unresolved queue como señal de "esto pide entrar al catálogo".
- Añadir 1 serie al CATALOG exige añadir ≥1 alias en simultáneo (`T03` en AGENT_TASKS),
  o el smoke del ALIAS_MAP falla.

## More Information

- Invariante de integridad: `validate_alias_map(CATALOG)` sin huérfanos
  (smoke 1 en [INTEGRATION_CHECKLIST.md](../../testing/INTEGRATION_CHECKLIST.md)).
- Cuando haya N≥50 videos por persona × tono, reconsiderar un ranking aprendido
  (bandit Thompson) — eso sería una ADR nueva que podría supersedir parte de esta.

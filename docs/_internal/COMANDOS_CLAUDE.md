# Comandos, Skills y Agents Instalados en Claude Code

> Instalados globalmente en `~/.claude/` - funcionan desde **cualquier disco o directorio**.

---

## Comandos (/slash commands) — 57 comandos

### Planificacion y Arquitectura

| Comando | Descripcion | Ejemplo |
|---------|-------------|---------|
| `/plan` | Crea plan de implementacion paso a paso. Espera confirmacion antes de tocar codigo | `/plan Agregar autenticacion JWT al API de Express` |
| `/orchestrate` | Guia para orquestar multiples agentes en paralelo | `/orchestrate Migrar frontend de CRA a Next.js en 3 worktrees` |
| `/devfleet` | Orquesta agentes paralelos via DevFleet | `/devfleet Refactorizar modulo de pagos en 4 servicios` |
| `/model-route` | Recomienda el mejor modelo segun complejidad y presupuesto | `/model-route Generar tests E2E para checkout` |
| `/prompt-optimize` | Analiza un prompt y devuelve version optimizada (no ejecuta) | `/prompt-optimize "Crea una API REST para gestion de inventario"` |

### Desarrollo y Testing

| Comando | Descripcion | Ejemplo |
|---------|-------------|---------|
| `/tdd` | Flujo TDD: tests primero, luego implementacion. 80%+ cobertura | `/tdd Crear servicio de notificaciones por email` |
| `/e2e` | Genera y ejecuta tests E2E con Playwright | `/e2e Flujo de registro y login de usuario` |
| `/test-coverage` | Analiza cobertura, identifica gaps, genera tests faltantes | `/test-coverage src/services/` |
| `/build-fix` | Arregla errores de build incrementalmente | `/build-fix` |
| `/verify` | Verificacion completa: build, tipos, lint | `/verify` |
| `/quality-gate` | Pipeline de calidad ECC para archivo o proyecto | `/quality-gate src/api/routes.ts` |
| `/refactor-clean` | Identifica y elimina codigo muerto de forma segura | `/refactor-clean src/utils/` |

### Code Review por Lenguaje

| Comando | Descripcion | Ejemplo |
|---------|-------------|---------|
| `/code-review` | Review de seguridad y calidad de cambios no commiteados | `/code-review` |
| `/python-review` | Review de Python: PEP 8, type hints, seguridad | `/python-review scripts/legacy/main.py` |
| `/go-review` | Review de Go: patrones idiomaticos, concurrencia, errores | `/go-review cmd/server/main.go` |
| `/rust-review` | Review de Rust: ownership, lifetimes, unsafe | `/rust-review src/lib.rs` |
| `/cpp-review` | Review de C++: memory safety, idioms modernos | `/cpp-review src/engine.cpp` |
| `/kotlin-review` | Review de Kotlin: null safety, coroutines, seguridad | `/kotlin-review app/src/main/MainActivity.kt` |

### Build Fix por Lenguaje

| Comando | Descripcion | Ejemplo |
|---------|-------------|---------|
| `/go-build` | Arregla errores de build en Go | `/go-build` |
| `/rust-build` | Arregla errores de Rust (borrow checker, deps) | `/rust-build` |
| `/cpp-build` | Arregla errores de C++ (CMake, linker) | `/cpp-build` |
| `/kotlin-build` | Arregla errores de Kotlin/Gradle | `/kotlin-build` |
| `/gradle-build` | Arregla errores de Gradle para Android/KMP | `/gradle-build` |

### TDD por Lenguaje

| Comando | Descripcion | Ejemplo |
|---------|-------------|---------|
| `/go-test` | TDD en Go con table-driven tests. 80%+ cobertura | `/go-test Implementar cache LRU` |
| `/rust-test` | TDD en Rust. 80%+ cobertura con cargo-llvm-cov | `/rust-test Crear parser de CSV` |
| `/cpp-test` | TDD en C++ con GoogleTest. Cobertura con gcov | `/cpp-test Implementar arbol binario` |
| `/kotlin-test` | TDD en Kotlin con Kotest. 80%+ con Kover | `/kotlin-test Crear repositorio de usuarios` |

### Sesiones y Persistencia

| Comando | Descripcion | Ejemplo |
|---------|-------------|---------|
| `/save-session` | Guarda estado de sesion para retomar despues | `/save-session` |
| `/resume-session` | Carga la sesion mas reciente y continua | `/resume-session` |
| `/sessions` | Gestiona historial de sesiones (listar, cargar, alias) | `/sessions list` |
| `/checkpoint` | Crea o verifica un checkpoint en el flujo de trabajo | `/checkpoint pre-refactor` |

### Aprendizaje e Instintos

| Comando | Descripcion | Ejemplo |
|---------|-------------|---------|
| `/learn` | Extrae patrones reutilizables de la sesion actual | `/learn` |
| `/learn-eval` | Extrae patrones con auto-evaluacion de calidad | `/learn-eval` |
| `/instinct-status` | Muestra instintos aprendidos con nivel de confianza | `/instinct-status` |
| `/instinct-export` | Exporta instintos a archivo | `/instinct-export ./mis-instintos.yaml` |
| `/instinct-import` | Importa instintos desde archivo o URL | `/instinct-import ./instintos-equipo.yaml` |
| `/promote` | Promueve instintos de proyecto a scope global | `/promote` |
| `/evolve` | Analiza instintos y sugiere estructuras evolucionadas | `/evolve` |
| `/projects` | Lista proyectos conocidos y sus estadisticas | `/projects` |

### Skills y Documentacion

| Comando | Descripcion | Ejemplo |
|---------|-------------|---------|
| `/skill-create` | Genera SKILL.md desde historial git del proyecto | `/skill-create` |
| `/skill-health` | Dashboard de salud del portafolio de skills | `/skill-health` |
| `/docs` | Busca documentacion actualizada via Context7 | `/docs Next.js App Router` |
| `/update-docs` | Actualiza documentacion del proyecto | `/update-docs` |
| `/update-codemaps` | Genera documentacion de arquitectura token-lean | `/update-codemaps` |

### Multi-Modelo Colaborativo

| Comando | Descripcion | Ejemplo |
|---------|-------------|---------|
| `/multi-plan` | Planificacion colaborativa multi-modelo | `/multi-plan Disenar sistema de microservicios` |
| `/multi-execute` | Ejecucion colaborativa multi-modelo | `/multi-execute Implementar el plan de microservicios` |
| `/multi-frontend` | Desarrollo frontend multi-modelo | `/multi-frontend Redisenar dashboard de analytics` |
| `/multi-backend` | Desarrollo backend multi-modelo (Codex-led) | `/multi-backend Crear API de gestion de inventario` |
| `/multi-workflow` | Flujo completo multi-modelo colaborativo | `/multi-workflow Feature completa de chat en tiempo real` |

### Utilidades

| Comando | Descripcion | Ejemplo |
|---------|-------------|---------|
| `/aside` | Responde pregunta rapida sin perder contexto | `/aside Que version de Node soporta ES modules nativos?` |
| `/claw` | Inicia NanoClaw v2 - REPL persistente con routing | `/claw` |
| `/eval` | Gestiona flujo de eval-driven development | `/eval` |
| `/loop-start` | Inicia loop autonomo con defaults seguros | `/loop-start` |
| `/loop-status` | Verifica estado del loop autonomo | `/loop-status` |
| `/pm2` | Inicializa PM2 para gestion de procesos | `/pm2` |
| `/setup-pm` | Configura package manager del proyecto | `/setup-pm` |
| `/harness-audit` | Auditoria del repositorio con scorecard priorizado | `/harness-audit` |

---

## Skills (se activan automaticamente) — 48 skills

### De Impeccable (Diseno Frontend)

| Skill | Que hace | Ejemplo |
|-------|----------|---------|
| `/audit` | Checks tecnicos: a11y, performance, responsive | `/audit header` |
| `/critique` | Review de UX: jerarquia, claridad, resonancia | `/critique landing page` |
| `/polish` | Pase final antes de enviar | `/polish checkout-form` |
| `/distill` | Reduce a lo esencial | `/distill signup-modal` |
| `/normalize` | Alinea con estandares del design system | `/normalize buttons` |
| `/animate` | Agrega movimiento con proposito | `/animate hero-section` |
| `/colorize` | Introduce color estrategico | `/colorize dashboard` |
| `/bolder` | Amplifica disenos aburridos | `/bolder pricing-page` |
| `/quieter` | Reduce disenos demasiado agresivos | `/quieter notifications` |
| `/clarify` | Mejora copy de UX poco claro | `/clarify error-messages` |
| `/delight` | Agrega momentos de alegria | `/delight onboarding` |
| `/extract` | Extrae en componentes reutilizables | `/extract card-pattern` |
| `/adapt` | Adapta para diferentes dispositivos | `/adapt mobile` |
| `/harden` | Error handling, i18n, edge cases | `/harden form-validation` |
| `/onboard` | Disena flujos de onboarding | `/onboard new-user-flow` |
| `/optimize` | Mejoras de performance | `/optimize images` |
| `/frontend-design` | Skill completo de diseno con 7 referencias | (se activa automaticamente al disenar UI) |
| `/teach-impeccable` | Setup: recopila contexto de diseno del proyecto | `/teach-impeccable` |

### De Everything Claude Code (Desarrollo)

| Skill | Cuando se activa | Ejemplo de uso |
|-------|-----------------|----------------|
| `api-design` | Al disenar APIs REST | "Disena endpoints para gestion de usuarios" |
| `backend-patterns` | Al trabajar con backend Node/Express/Next.js | "Crea middleware de autenticacion" |
| `frontend-patterns` | Al trabajar con React/Next.js | "Implementa estado global con Zustand" |
| `coding-standards` | Al escribir TS/JS/React | (automatico) |
| `security-review` | Al manejar auth, input, secrets, pagos | "Revisa seguridad del endpoint de login" |
| `tdd-workflow` | Al escribir features, bugs, refactoring | (automatico con /tdd) |
| `e2e-testing` | Al escribir tests Playwright | (automatico con /e2e) |
| `deep-research` | Al necesitar investigacion con fuentes | "Investiga mejores practicas de WebSocket scaling" |
| `claude-api` | Al usar API de Anthropic/Claude SDK | "Implementa streaming con Claude API" |
| `documentation-lookup` | Al preguntar sobre frameworks/libs | "Como funciona App Router en Next.js 14?" |
| `strategic-compact` | Sugiere compactacion de contexto en momentos logicos | (automatico) |
| `verification-loop` | Sistema de verificacion comprensivo | (automatico con /verify) |
| `content-engine` | Al crear contenido para redes sociales | "Crea calendario de contenido para LinkedIn" |
| `crosspost` | Al distribuir contenido multi-plataforma | "Adapta este post para X, LinkedIn y Threads" |
| `article-writing` | Al escribir articulos/guias/blogs | "Escribe tutorial sobre Docker Compose" |
| `mcp-server-patterns` | Al construir servidores MCP | "Crea MCP server con Zod validation" |
| `nextjs-turbopack` | Al usar Next.js 16+ con Turbopack | (automatico) |
| `bun-runtime` | Al usar Bun como runtime | (automatico) |
| `frontend-slides` | Al crear presentaciones HTML | "Convierte este PPT a presentacion web animada" |
| `investor-materials` | Al crear pitch decks, memos | "Crea one-pager para ronda seed" |
| `investor-outreach` | Al redactar emails a inversores | "Draft cold email para VC de Serie A" |
| `market-research` | Al investigar mercado/competencia | "Analisis competitivo de herramientas de CI/CD" |
| `video-editing` | Al editar video con AI | "Pipeline de edicion para vlog con FFmpeg" |
| `fal-ai-media` | Al generar imagenes/video/audio con AI | "Genera imagen con fal.ai Nano Banana" |
| `exa-search` | Al buscar con Exa neural search | "Busca repositorios similares a este" |
| `eval-harness` | Framework de evaluacion EDD | (automatico con /eval) |
| `dmux-workflows` | Al orquestar multi-agentes con dmux | (automatico con /orchestrate) |
| `x-api` | Al interactuar con X/Twitter API | "Publica tweet con thread" |
| `everything-claude-code` | Skill principal del plugin | (siempre activo) |

### De Nanochat

| Skill | Que hace | Ejemplo |
|-------|----------|---------|
| `read-arxiv-paper` | Lee papers de arxiv desde URL, descarga TeX, genera resumen | "Lee este paper: https://arxiv.org/abs/2401.07372" |

---

## Agents (subagentes especializados) — 25 agents

| Agent | Especialidad |
|-------|-------------|
| `architect` | Diseno de sistemas y arquitectura |
| `planner` | Planificacion de features |
| `code-reviewer` | Review de calidad de codigo |
| `security-reviewer` | Analisis de vulnerabilidades |
| `tdd-guide` | Guia de test-driven development |
| `build-error-resolver` | Resolucion de errores de build |
| `e2e-runner` | Ejecucion de tests end-to-end |
| `doc-updater` | Actualizacion de documentacion |
| `docs-lookup` | Busqueda de documentacion |
| `refactor-cleaner` | Limpieza y refactoring seguro |
| `database-reviewer` | Review de queries y esquemas DB |
| `harness-optimizer` | Optimizacion del harness de Claude |
| `chief-of-staff` | Coordinacion de agentes |
| `loop-operator` | Operacion de loops autonomos |
| `python-reviewer` | Review especializado en Python |
| `go-reviewer` | Review especializado en Go |
| `go-build-resolver` | Fix de builds en Go |
| `rust-reviewer` | Review especializado en Rust |
| `rust-build-resolver` | Fix de builds en Rust |
| `cpp-reviewer` | Review especializado en C++ |
| `cpp-build-resolver` | Fix de builds en C++ |
| `java-build-resolver` | Fix de builds en Java |
| `java-reviewer` | Review especializado en Java |
| `kotlin-reviewer` | Review especializado en Kotlin |
| `kotlin-build-resolver` | Fix de builds en Kotlin |

---

## Plugins Registrados

| Plugin | Estado | Descripcion |
|--------|--------|-------------|
| **impeccable** | Activo | 18 skills de diseno frontend |
| **everything-claude-code** | Activo | Agents, skills, commands, rules |
| **claude-mem** | Registrado (requiere `/plugin install`) | Memoria persistente entre sesiones |

---

## MCP Servers Configurados

| Server | Descripcion |
|--------|-------------|
| `promptfoo` | Testing y evaluacion de prompts LLM |
| `davinci-resolve` | Integracion con DaVinci Resolve |

---

## Notas

- **Todo es global**: instalado en `~/.claude/`, funciona desde cualquier directorio o disco
- **Reiniciar para aplicar**: cierra y abre nueva conversacion de Claude Code
- **claude-mem**: para activar memoria persistente, ejecutar en nueva sesion:
  ```
  /plugin marketplace add thedotmack/claude-mem
  /plugin install claude-mem
  ```
- **Fuentes**:
  - [impeccable](https://github.com/pbakaus/impeccable) - Paul Bakaus
  - [everything-claude-code](https://github.com/affaan-m/everything-claude-code) - Affaan Mustafa
  - [claude-mem](https://github.com/thedotmack/claude-mem) - Alex Newman
  - [nanochat](https://github.com/nanochat) - read-arxiv-paper skill

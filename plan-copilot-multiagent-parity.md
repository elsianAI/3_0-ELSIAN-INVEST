# Plan: Paridad Multiagente en Copilot

## Contexto y motivación

Hemos construido un sistema multiagente para ELSIAN 4.0 con tres roles de negocio (director, engineer, auditor) y un padre neutral orquestador. El contrato canónico vive en `docs/project/ROLES.md` y es agnóstico a la plataforma. Los wrappers de cada plataforma son finos por diseño: solo declaran identidad, lecturas obligatorias, herramientas disponibles y notas de runtime.

**El problema:** Hoy la orquestación multiagente completa solo funciona en Codex. En Copilot tenemos dos agent files (director y engineer) pero:

- No existe un agent file de **auditor**.
- No existe un **padre orquestador** que encadene director → engineer → gates → auditor.
- El director tiene `agents: ['ELSIAN 4.0 Engineer']` y puede hacer handoff al engineer, pero no hay ejecución automática de gates ni encadenamiento con auditor.
- El flujo completo depende de que el usuario haga de orquestador manual entre roles.

**El objetivo:** Conseguir que en Copilot, igual que en Codex, el usuario escriba una petición en un solo hilo y el sistema orqueste internamente el flujo completo. Mismos contratos, mismos gates, misma lógica de routing — distinta fontanería.

**Principio rector:** ROLES.md es la única fuente de verdad. Los nuevos agent files serán wrappers finos que sigan la wrapper policy ya establecida en ROLES.md §8.1. No redefinen contratos.

---

## Estado actual de Copilot

### Agent files existentes

| Fichero | Rol | Líneas | Estado |
|---------|-----|--------|--------|
| `.github/agents/project-director.agent.md` | director | 58 | Wrapper fino, lee ROLES.md, produce handoffs canónicos |
| `.github/agents/elsian-4.agent.md` | engineer (Módulo 1) | 75 | Wrapper fino, lee ROLES.md + MODULE_1_ENGINEER_CONTEXT.md |

### Lo que falta

| Componente | Existe en Codex | Existe en Copilot |
|------------|-----------------|-------------------|
| Skill/agent director | ✅ `elsian-director` | ✅ `project-director.agent.md` |
| Skill/agent engineer | ✅ `elsian-engineer` | ✅ `elsian-4.agent.md` |
| Skill/agent auditor | ✅ `elsian-auditor` | ❌ No existe |
| Padre orquestador | ✅ Runtime neutral de Codex | ❌ No existe |
| Gates automáticos | ✅ Los ejecuta el padre | ❌ No hay mecanismo |

### Capacidades relevantes de Copilot

- `agent/runSubagent` está disponible como herramienta — los agent files pueden lanzar subagentes.
- El campo `agents` del frontmatter declara qué agentes puede invocar un agent file.
- Los handoffs permiten pasar contexto entre agentes.
- Las herramientas de terminal (`execute/runInTerminal`, `execute/getTerminalOutput`) permiten ejecutar comandos — necesario para gates.

---

## Cambios propuestos

### 1. Crear `elsian-auditor.agent.md`

**Ubicación:** `.github/agents/elsian-auditor.agent.md`

**Naturaleza:** Wrapper fino, mismo patrón que director y engineer.

**Contenido esperado:**

- **Frontmatter:**
  - `name: ELSIAN 4.0 Auditor`
  - `description: Thin Copilot wrapper for the ELSIAN-INVEST 4.0 auditor role`
  - `agents: []` — el auditor no lanza subagentes
  - `tools:` — solo herramientas de lectura y terminal read-only (NO `edit/editFiles`, NO `edit/createFile`)
  - Sin handoffs de escritura
- **Cuerpo:**
  - Declaración de que ROLES.md es la fuente de verdad
  - Required reads: VISION.md, ROLES.md, KNOWLEDGE_BASE.md, el contexto técnico del módulo auditado (default: MODULE_1_ENGINEER_CONTEXT.md), DECISIONS.md
  - Runtime notes: es un rol hijo, read-only, evidence-only, no implementa, no cura, no reprioriza, no edita ficheros
  - Platform use: usa herramientas de lectura de Copilot para inspeccionar diffs, leer ficheros, revisar salida de gates; reporta findings antes que resumen
  - Formato de salida: findings-first con severidad, luego resumen factual

**Restricción crítica:** El auditor no debe tener herramientas de escritura. Su contrato en ROLES.md dice "Nada. Solo lectura y comandos no mutantes." El toolset del agent file debe reflejar esto — si Copilot no permite excluir `edit/editFiles` del toolset, el wrapper debe dejarlo explícitamente claro en las runtime notes como prohibición.

### 2. Crear `elsian-orchestrator.agent.md`

**Ubicación:** `.github/agents/elsian-orchestrator.agent.md`

**Naturaleza:** Padre neutral orquestador. NO es un cuarto rol de negocio — es infraestructura de runtime, exactamente como el padre neutral de Codex.

**Contenido esperado:**

- **Frontmatter:**
  - `name: ELSIAN Orchestrator`
  - `description: Neutral multiagent parent for ELSIAN-INVEST 4.0 — routes, gates, and aggregates`
  - `agents: ['Project Director', 'ELSIAN 4.0 Engineer', 'ELSIAN 4.0 Auditor']` — puede invocar los tres
  - `tools:` — herramientas de lectura + terminal (necesita ejecutar gates: `git diff`, `python3 -m elsian eval`, `pytest`)
  - Sin handoffs — el orquestador no hace handoff al usuario entre pasos, ejecuta la cadena completa

- **Cuerpo — Identidad:**
  - "Eres el padre neutral orquestador de ELSIAN 4.0. No eres un rol de negocio. No decides producto, no implementas, no auditas. Tu trabajo es: clasificar la petición, lanzar los hijos correctos en el orden correcto, ejecutar gates entre ellos, y devolver el resultado agregado."
  - Referencia a ROLES.md como fuente de verdad de routing, gates, anti-fraude y packets.

- **Cuerpo — Routing (lee de ROLES.md §3):**
  - Si la petición menciona shared-core, afecta varios tickers, o es ambigua → director primero.
  - Si la petición es claramente local (un case.json, un test, un ticker acotado) → engineer directo.
  - Si la petición es review o auditoría explícita → auditor directo.

- **Cuerpo — Flujo completo estándar:**
  1. Leer ROLES.md y clasificar la petición.
  2. Si procede, lanzar director con director packet (ROLES.md §4.1).
  3. Recibir handoff del director.
  4. Lanzar engineer con engineer packet (ROLES.md §4.2).
  5. Recibir resultado del engineer.
  6. **Ejecutar gates** (ROLES.md §5):
     - `git diff --name-only` dentro de allowed files.
     - Si tocó `expected.json`: comparar conteo de campos antes/después.
     - Si tocó `case.json`: comparar `manual_overrides` antes/después.
     - Tier de validación según packet (targeted: `eval TICKER`, shared-core: `eval --all + pytest`, governance-only: solo scope check).
     - Reglas anti-fraude: reducir expected falla por defecto, aumentar overrides falla por defecto.
  7. Si gates pasan → lanzar auditor con auditor packet evidence-only (ROLES.md §4.3).
  8. Si gates fallan → devolver al engineer con contexto del fallo. No lanzar auditor.
  9. Agregar resultado final y devolver a Elsian.

- **Cuerpo — Restricciones:**
  - No toma decisiones de producto ni de arquitectura.
  - No edita ficheros del repo directamente — solo ejecuta comandos de validación.
  - No suaviza el packet del auditor con framing favorable del director.
  - No permite subagentes anidados (un hijo no lanza otro hijo).
  - Si un spawn falla, reintenta con prompt standalone autosuficiente (ROLES.md §6).

- **Cuerpo — Formato de respuesta:**
  - Separar claramente la salida por fases/roles para que Elsian vea qué hizo cada uno.
  - Incluir la salida literal de gates (no resumirla).
  - El resultado del auditor se presenta tal cual, sin edición del orquestador.

### 3. Ajustar agent files existentes

**`project-director.agent.md`:**
- Cambio mínimo: el campo `agents` actualmente dice `['ELSIAN 4.0 Engineer']`. Esto permitía al director lanzar al engineer directamente. Con el orquestador, este handoff ya no lo hace el director — lo hace el padre. Hay dos opciones:
  - **Opción A:** Dejar `agents: ['ELSIAN 4.0 Engineer']` para compatibilidad cuando se use el director sin orquestador (invocación directa `@project-director`).
  - **Opción B:** Cambiar a `agents: []` para que el director solo produzca handoffs y sea el orquestador quien lance al engineer.
  - **Recomendación:** Opción A. Mantener la capacidad de uso directo. Cuando el director es invocado por el orquestador, las runtime notes ya dicen "no lances nested orchestration chains". Cuando es invocado directamente por el usuario, poder hacer handoff al engineer es útil.

**`elsian-4.agent.md`:**
- Sin cambios. Ya es un wrapper fino correcto. `agents: []`, no lanza subagentes, lee ROLES.md.

### 4. Actualizar ROLES.md §7

**Cambio:** En la sección de consistencia y mantenimiento, añadir el orquestador de Copilot a la lista de implementaciones operativas que deben mantenerse coherentes:

```markdown
- Las implementaciones operativas deben mantenerse coherentes con este documento:
  - skills locales de Codex en `$CODEX_HOME/skills/`;
  - agent files repo-tracked en `.github/agents/`;
  - el orquestador de Copilot (`.github/agents/elsian-orchestrator.agent.md`) no redefine contratos; solo implementa el flujo descrito en este documento.
```

### 5. Sincronizar skill de Codex

Si Codex no tiene ya una skill equivalente al orquestador (porque en Codex el padre es el runtime nativo), no hace falta crear una. El orquestador es específico de Copilot porque Copilot necesita un agent file explícito para lo que Codex hace nativamente. Documentar esta asimetría en ROLES.md §7 como nota.

---

## Restricciones y riesgos

### Riesgo 1: Copilot no soporte encadenamiento real de subagentes

El mecanismo `agent/runSubagent` de Copilot puede tener limitaciones que no conocemos todavía. Si el orquestador no puede lanzar tres hijos en secuencia dentro del mismo hilo, el plan no funciona tal cual.

**Mitigación:** Antes de implementar el orquestador completo, hacer un experimento mínimo: crear un agent file de prueba que lance dos subagentes en secuencia y verifique que recibe los resultados de ambos.

### Riesgo 2: Herramientas de escritura en el auditor

Copilot puede no permitir crear un agent file que excluya `edit/editFiles` del toolset. Si el auditor tiene herramientas de escritura disponibles aunque no deba usarlas, existe el riesgo de que las use por error.

**Mitigación:** Las runtime notes del auditor deben ser explícitas ("no edites ficheros bajo ninguna circunstancia"). Verificar después del primer uso que el auditor respeta esta restricción.

### Riesgo 3: Context window del orquestador

El orquestador necesita mantener contexto entre las fases (resultado del director → input del engineer → resultado del engineer → gates → input del auditor). Si el hilo es largo, puede perder contexto.

**Mitigación:** Los packets son autosuficientes por diseño (ROLES.md §4). Cada hijo recibe todo lo que necesita en su prompt, sin depender de contexto heredado del padre.

### Riesgo 4: El orquestador absorbe lógica de negocio

El orquestador podría tender a "pensar" sobre el problema en vez de delegarlo. Esto lo convertiría en un cuarto rol que compite con el director.

**Mitigación:** El wrapper debe ser muy explícito: "No decides producto, no acotes alcance, no interpretes resultados técnicos. Tu trabajo es routing, gates y agregación."

---

## Plan de validación

### Validación estática (post-implementación)

1. Ningún wrapper nuevo redefine contratos de ROLES.md.
2. El auditor no tiene herramientas de escritura (o tiene prohibición explícita si Copilot no permite excluirlas).
3. El orquestador referencia ROLES.md para routing (§3), packets (§4), gates (§5) y retry (§6).
4. Todos los agent files siguen la wrapper policy de ROLES.md §8.1.
5. No aparecen `commercial-grade`, `Four Product Lines`, `Layer 2/3/4` en ningún fichero nuevo.

### Smoke test funcional

Replicar el mismo smoke test diseñado para Codex (TEP override metadata, BL-054) pero en Copilot:

1. Abrir chat de Copilot.
2. Invocar `@elsian-orchestrator` con la misma petición del smoke test de Codex.
3. Verificar criterio de éxito en dos capas:
   - **Runtime pass:** El orquestador dejó evidencia de que lanzó director, engineer, ejecutó gates, y lanzó auditor como pasos separados.
   - **Functional pass:** El único diff es `cases/TEP/case.json`, los 6 overrides tienen `source_filing` y `extraction_method: "manual"`, `eval TEP` pasa.

### Comparación cross-plataforma

Después de ambos smoke tests (Codex y Copilot), comparar:
- ¿Ambos produjeron el mismo resultado funcional?
- ¿Ambos siguieron el mismo flujo de roles?
- ¿Hay diferencias en cómo se ejecutaron los gates?
- ¿Hay asimetrías que requieran documentación en ROLES.md?

---

## Orden de ejecución propuesto

1. **Primero:** Completar el smoke test de Codex (ya planificado, pendiente de ejecutar).
2. **Segundo:** Crear `elsian-auditor.agent.md` — es el componente más sencillo y no depende de nada más.
3. **Tercero:** Crear `elsian-orchestrator.agent.md` — depende de que el auditor exista.
4. **Cuarto:** Actualizar ROLES.md §7 con la referencia al orquestador.
5. **Quinto:** Smoke test de Copilot con la misma tarea TEP.
6. **Sexto:** Comparación cross-plataforma y ajustes si los hay.
7. **Séptimo:** Commit limpio con todos los cambios.

---

## Asunciones

- `agent/runSubagent` de Copilot permite lanzar hijos en secuencia y recibir sus resultados.
- El orquestador puede ejecutar comandos de terminal (necesario para gates).
- El campo `agents` del frontmatter es suficiente para declarar qué subagentes puede invocar un agent file.
- No se necesita crear una skill equivalente en Codex — allí el padre neutral ya es nativo del runtime.
- El director mantiene `agents: ['ELSIAN 4.0 Engineer']` para compatibilidad con uso directo.

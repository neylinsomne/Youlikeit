# Estrategia CPS — Hooks de retencion en los primeros segundos

> CPS = **Cuts Per Second**. La densidad de cortes visuales que tiene el
> video, especialmente los primeros 1-3 segundos donde el algoritmo decide
> si te muestra o te sepulta.

> Objetivo de este doc: definir como deben verse los **primeros 0-5
> segundos** de cada short para maximizar la tasa de gente que se queda
> mas alla de los 3 segundos (la metrica que TikTok y YouTube usan para
> recomendar).

---

## 1. Por que los primeros 3 segundos lo son todo

Las dos plataformas (YouTube Shorts y TikTok) usan basicamente la misma
heuristica:

| Tramo | Que mide la plataforma | Decision algoritmica |
|-------|----------------------|---------------------|
| **0-1s** | swipe rate | si > 70% swipean, el video muere |
| **1-3s** | hook strength | si retiene > 75% a los 3s, se promueve |
| **3-15s** | average watch time | empieza a contar para el ranking |
| **15-30s** | completion rate | clave para "for you page" |
| **30s+** | rewatch + share rate | clave para viralidad |

Resultado practico: **gana o pierde el video en los primeros 3 segundos**.
Todo lo demas amplifica o atenua, pero no salva un mal hook.

---

## 2. El modelo de 3 capas del hook

Cada short que generamos tiene que tener tres elementos en los primeros 3
segundos, **simultaneamente**:

### Capa 1 — Hook visual (CPS alto)

Mucha imagen distinta en poco tiempo. La regla:

| Tramo | Cortes minimos | CPS objetivo |
|-------|---------------|--------------|
| 0.0-1.5s | 3-4 imagenes distintas | **2-3 CPS** |
| 1.5-3.0s | 2-3 imagenes distintas | 1.5-2 CPS |
| 3.0-15s | bajar a ritmo normal | 0.3-0.6 CPS |

Comparativa:
- Un short de 30s con CPS bajo (0.3 promedio) tiene ~9 cortes total
- Un short con hook fuerte tiene **6-8 cortes solo en los primeros 3s**, despues baja a ritmo normal

### Capa 2 — Hook auditivo

Lo primero que se escucha decide si la persona sube el volumen.

| 0-1s | 1-3s |
|------|------|
| Pregunta retorica (`"What if Griffith was right?"`) | Cifra o nombre concreto que lance la afirmacion (`"Walter White"`) |
| Sonido brusco / impacto | Voz inicia con cadencia constante |
| Frase incompleta | Resolver la frase con un giro |

### Capa 3 — Hook textual (subtitulos)

Subtitulos enormes desde el frame 1.

- Tipografia muy bold (Space Grotesk Bold, DejaVu Sans Bold)
- Color de acento alto contraste (cyan, amarillo, magenta)
- Una palabra clave aislada en el primer segundo (ej: "BETRAYAL")
- Animacion `\fad(0,150)` para entrada limpia

---

## 3. CPS por persona

Cada narrador del catalogo tiene una "firma de pacing":

| Persona | CPS hook (0-3s) | CPS cuerpo (3-15s) | CPS clausura (15s+) |
|---------|----------------|--------------------|--------------------|
| **Deep Mind** | 2.0 | 0.4 | 0.3 (deja respirar) |
| **Pop Oracle** | 3.0 | 0.7 | 0.5 (mantiene ritmo) |
| **Voz Latina** | 2.5 | 0.5 | 0.4 (respeta el dialogo) |

> Pop Oracle aprieta mas porque su audiencia es mas TikTok-native. Deep
> Mind respira mas porque su audiencia es de YouTube y aguanta mas.

---

## 4. Plantillas de hook por tipo de video

Cada uno de los 3 tipos del cycle (`narration`, `personality`, `test`)
tiene una plantilla visual y narrativa para los primeros 3s.

### 4.1 NARRATION (lo seguro)

Hook tipo "scene-setting con tension".

```
0.0s ┌─────────────────┐  Frame: Imagen iconica de la escena central, oscura
     │  IMAGE 1 (1s)   │  Audio: Pausa de 0.3s seguida de la primera linea
     └─────────────────┘  Texto: keyword aislada (ej: "ECLIPSE")

1.0s ┌─────────────────┐  Frame: Reaction shot del personaje principal
     │  IMAGE 2 (1s)   │  Audio: Continua la frase con cadencia lenta
     └─────────────────┘  Texto: completa la frase

2.0s ┌─────────────────┐  Frame: Detalle (objeto, mano, ojo)
     │  IMAGE 3 (1s)   │  Audio: pausa breve antes del giro
     └─────────────────┘  Texto: aparece la palabra-clave de la pregunta

3.0s+ ──── transicion a narracion normal ────
```

**CPS hook objetivo: 2.0**

### 4.2 PERSONALITY (la posicion contraria)

Hook tipo "afirmacion provocadora + visual de respaldo".

```
0.0s ┌─────────────────┐  Frame: Close-up del personaje en cuestion
     │  IMAGE 1 (0.8s) │  Audio: Afirmacion contundente desde el frame 1
     └─────────────────┘  Texto: la afirmacion entera, MAYUSCULAS

0.8s ┌─────────────────┐  Frame: Cross-ref 1 (Walter White)
     │  IMAGE 2 (0.7s) │  Audio: nombre del cross-ref
     └─────────────────┘  Texto: el nombre

1.5s ┌─────────────────┐  Frame: Cross-ref 2 (Light Yagami)
     │  IMAGE 3 (0.7s) │  Audio: segundo nombre
     └─────────────────┘  Texto: el nombre

2.2s ┌─────────────────┐  Frame: Vuelve al personaje original
     │  IMAGE 4 (0.8s) │  Audio: cierre del paralelo
     └─────────────────┘  Texto: "MISMO PATRON"

3.0s+ ──── el video se asienta en pacing normal ────
```

**CPS hook objetivo: 3.5**

Esto es el "x meets y" visual aplicado al primer segundo. Funciona porque
ya en 3s sabes la tesis del video.

### 4.3 TEST (golpe emocional)

Hook tipo "imagen larga + silencio + giro".

```
0.0s ┌─────────────────┐  Frame: Foto fija fuerte (escena tragica),
     │  IMAGE 1 (2.5s) │   pero con micro-movement (Ken Burns lento)
     │   Ken Burns     │  Audio: silencio, luego inhalacion ambient
     └─────────────────┘  Texto: cifra dura ("100 TIMES")

2.5s ┌─────────────────┐  Frame: Cut a oscuridad / pantalla negra parcial
     │  IMAGE 2 (0.5s) │  Audio: respiracion
     └─────────────────┘  Texto: vacio

3.0s+ ──── arranca la voz reflexiva ────
```

**CPS hook objetivo: 1.0** (intencionalmente bajo — la quietud ES el hook)

Es el unico tipo donde **rompemos la regla de CPS alto**. La pausa
larga + el cambio brusco al silencio engancha a la audiencia que ya esta
saturada de fast-cuts en su feed.

---

## 5. Mapa de hooks → temas

No todos los hooks funcionan igual con todos los temas. Esta tabla cruza
el `tone` del video con el tipo de hook que rinde:

| Tono | Hook recomendado | Hook a evitar |
|------|------------------|---------------|
| critical | "Affirmation hook" (3.5 CPS) | "Quiet hook" (no engancha la rabia) |
| narrative | "Scene tension" (2.0 CPS) | "Affirmation" (suena agresivo en cuento) |
| analytical | "Question hook" (2.0 CPS) | "Quiet hook" (la audiencia espera info) |
| emotional | "Quiet hook" (1.0 CPS) | "Affirmation" (rompe la vulnerabilidad) |
| comparative | "X meets Y" (3.0 CPS) | "Quiet hook" |

---

## 6. Texto del primer segundo — banco de apertura

Frases que el LLM debe usar como primer segmento. Estructura: 4-7 palabras,
acaban en pausa o ellipsis.

### Para narration
- "It was the night that changed everything…"
- "The day the world tilted on its axis…"
- "One choice. Endless consequences…"
- "She had three seconds to decide…"
- "He never spoke about it again…"

### Para personality
- "Griffith was right. And you know it."
- "Stop calling [X] a hero."
- "[X] is the most underrated villain in fiction."
- "Everyone is wrong about [X]."
- "This is the take that will get me unfollowed."

### Para test (emocional)
- "I have watched this scene a hundred times."
- "And every time, it breaks me."
- "There is a moment in [X] that I cannot forget."
- "If you have ever been [feeling], you understand."
- "I do not have words for what this scene did to me."

---

## 7. Implementacion en el pipeline

Para que esto pase de teoria a videos reales, vamos a tocar tres modulos:

### 7.1 `src/common/script_generator.py`

Agregar al prompt del LLM una instruccion explicita sobre el primer
segmento:

```python
HOOK_RULES = {
    "narration": "Segment 1 must be 4-7 words ending in ellipsis. Set the scene.",
    "personality": "Segment 1 must be a contrarian declaration ending in a period. Max 8 words.",
    "test": "Segment 1 must reference a feeling or count (e.g., 'I have watched this 100 times'). Slow.",
}
```

Y enforce que el segmento 1 sea distinto de los demas (mas corto, mas
denso emocionalmente).

### 7.2 `src/common/video_director.py`

Agregar un parametro `hook_cps` al EDL:

```python
class EditDecision:
    ...
    hook_cps: float = 0.5  # cortes/segundo durante el hook (0-3s)
    is_hook: bool = False  # si True, multi-cut sobre la misma narracion
```

En el render, si `is_hook=True` y `hook_cps >= 1.5`, sub-dividir el
segmento en N cortes visuales sin tocar el audio (que sigue continuo).

```python
def _expand_hook(self, decision):
    if decision.is_hook and decision.hook_cps >= 1.5:
        n_cuts = int(decision.duration * decision.hook_cps)
        # Pickear N imagenes del pool y rotarlas durante decision.duration
        # El audio de la narracion sigue corriendo encima
        return [...sub-clips with same audio segment...]
    return [decision]
```

### 7.3 `scripts/produce_for_series.py`

Marcar el primer segmento como `is_hook=True` y aplicarle el `hook_cps`
correspondiente al video type:

```python
HOOK_CPS_BY_TYPE = {
    "narration": 2.0,
    "personality": 3.5,
    "test": 1.0,
}

# Al construir el EDL:
for i, ns in enumerate(narration_data):
    edl.append(EditDecision(
        ...
        is_hook=(i == 0),
        hook_cps=HOOK_CPS_BY_TYPE[vtype] if i == 0 else 0.5,
    ))
```

### 7.4 Subtitulos en el hook

`src/common/animated_subs.py` — para el primer segmento:

- Tamano: 1.4x mas grande que el cuerpo
- Color: usar el `accent` de la persona (cyan / pink / orange) en la palabra clave
- Animacion: `\fad(0,200)` (fade in inmediato)
- Posicion: centrado vertical (no abajo)

Una vez se acaba el hook, los subtitulos vuelven a la posicion / tamano
estandar.

---

## 8. Como medir si el hook esta funcionando

Cuando empezamos a tener data de YouTube Analytics (28 dias despues del
primer upload), hay que mirar:

| Metrica | Objetivo | Que hacer si falla |
|---------|----------|--------------------|
| **Average view duration / video length** | > 60% en shorts < 30s | Bajar la duracion total del video |
| **Retention at 3s** | > 75% | Cambiar plantilla de hook |
| **Retention at 15s** | > 50% | Mejorar transicion entre hook y cuerpo |
| **Swipe rate (TikTok)** | < 30% | Mejorar primer frame visual |
| **Share rate** | > 1.5% | Mejorar el outro / CTA |

YouTube Analytics expone `audienceWatchRatio` segundo a segundo. La
implementacion ya existe en `src/exercises/ex24_retention_curves.py`.
Lo que falta es comparar la curva de un video con `is_hook=True` vs
los antiguos sin hook explicito.

---

## 9. Plan de A/B test del hook

Una vez tengamos 3-4 shorts con la nueva plantilla y 3-4 sin ella:

1. Hipotesis: shorts con `hook_cps >= 2.0` retienen mas a 3s que los de `hook_cps < 1.0`
2. Variable: `hook_cps`
3. Variant A: nuevos videos (con hook fuerte)
4. Variant B: videos antiguos sin hook explicito
5. Metrica primaria: `retention_at_3s`
6. Metrica secundaria: `engagement_rate = (likes + comments) / views`
7. Min samples: 3 por variante
8. Significance: p < 0.10 (somos chicos, no exigimos 0.05)

Esto se conecta directo con el sistema de A/B existente en
`src/common/ab_testing.py`. Solo hay que crear el test:

```python
from common.ab_testing import create_ab_test
create_ab_test(
    conn=conn,
    name="Hook CPS strength",
    hypothesis="Shorts with hook_cps>=2.0 retain >75% viewers at 3s",
    variable="narration_speed",
    variant_a_config={"hook_cps": 2.0, "label": "strong_hook"},
    variant_b_config={"hook_cps": 0.5, "label": "no_hook"},
    metric="retention_at_3s",
    min_samples=3,
)
```

---

## 10. Checklist por video antes de aprobar en review

Cuando te llegue un short al review dashboard, antes de aprobar verificar:

- [ ] El primer frame es VISUAL fuerte (no transicion negra, no logo)
- [ ] Los primeros 3 segundos tienen >= 3 cortes visuales (excepto `test`)
- [ ] El primer segmento tiene <= 8 palabras
- [ ] El subtitulo del primer segmento esta visible desde el frame 1
- [ ] Hay una palabra-clave subrayada / coloreada en el subtitulo
- [ ] El audio empieza dentro del primer 0.5s (no silencio largo, salvo en `test`)
- [ ] No hay watermark de la fuente original visible en los primeros 3s

Si falla alguno → pedir edicion en el dashboard.

---

## 11. Roadmap

- [ ] **Fase 1**: agregar `is_hook` y `hook_cps` al EDL (no rompe lo existente, default 0.5 = comportamiento actual)
- [ ] **Fase 2**: extender `script_generator.py` con las HOOK_RULES
- [ ] **Fase 3**: implementar `_expand_hook()` en `video_director.py`
- [ ] **Fase 4**: actualizar subtitulos en hook (size 1.4x, accent color)
- [ ] **Fase 5**: A/B test estructurado contra los videos viejos
- [ ] **Fase 6**: leer resultados de YouTube Analytics a 28 dias y refinar

---

## 12. Referencias rapidas (sin leer ningun libro)

- TikTok algorithm 101: completion + share rate > everything else
- YouTube Shorts algorithm: average view duration / length > 60% para promocion
- Hook frameworks usados por canales que crecen: PAS (Problem-Agitate-Solve),
  Question-Twist, Pattern Interrupt
- Tu sistema ya esta hecho para A/B testing con significancia estadistica
  (`src/common/ab_testing.py`) — solo falta enchufar el hook como variable

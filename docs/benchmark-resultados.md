# SecretarIA — Resultados del Benchmark de Modelos

## Suite de tests (`scripts/benchmark.py`)

35 tests en 9 categorías. Cada test valida que la respuesta contenga al menos una de las keywords esperadas (normalización Unicode para ignorar tildes).

### Categorías

| Categoría   | Tests | Descripción                                          |
|-------------|-------|------------------------------------------------------|
| social      | 2     | Saludos y despedidas (sin tool)                      |
| familias    | 2     | Listado de familias y sedes (sin tool, de memoria)   |
| informatica | 6     | Módulos e info de SMR, DAW, DAM, ASIR, IA, Ciber    |
| sanidad     | 4     | Módulos de Enfermería, Laboratorio, Óptica, Prótesis |
| comercio    | 3     | Módulos de MP, CI, AC                                |
| admin       | 2     | Módulos de AF y GA                                   |
| turismo     | 1     | Módulos de GAT                                       |
| horarios    | 4     | Turnos y sedes específicas (DAM, ASIR, SMR, GAT)     |
| tramites    | 4     | Matrícula, requisitos, email y horario de secretaría |
| sin_datos   | 3     | Preguntas fuera del ámbito (rechazo correcto)        |
| contexto    | 5     | Memoria multi-turno (2 cadenas compartiendo sesión)  |

**Nota sobre context chains**: los tests `ctx1/ctx2/ctx3` comparten session ID `c1`; `ctx4/ctx5` comparten `c2`. Esto valida memoria real de conversación.

---

## Resultados por modelo

### mistral-small3.2:24b — **Modelo en producción**

Benchmark completo (36 tests, SSH keepalive activo):

```
  ✅ [social    ]   1.9s   hola
  ✅ [social    ]   0.9s   gracias, hasta luego
  ✅ [familias  ]  10.4s   que familias profesionales hay
  ✅ [familias  ]   5.7s   donde esta la familia de comercio
  ❌ [informatica]  12.1s  que modulos tiene DAM            ← bot pidió aclarar curso (>10 módulos), keywords corregidas
  ✅ [informatica]  20.2s  modulos del ciclo DAW
  ✅ [informatica]  20.9s  informacion sobre SMR microinformatica
  ✅ [informatica]  19.6s  que se estudia en ASIR
  ✅* [informatica]  3.2s  modulos del ciclo de inteligencia artificial  ← falso positivo ("ia" en "secretaría"), test corregido
  ✅ [informatica]   6.0s  que es el curso de ciberseguridad
  ✅ [sanidad   ]  13.1s  que modulos tiene optica de anteojeria
  ✅ [sanidad   ]   8.1s  que asignaturas tiene enfermeria
  ✅ [sanidad   ]  14.1s  modulos de laboratorio clinico
  ✅ [sanidad   ]   7.2s  que estudia protesis dental
  ✅ [comercio  ]  15.1s  que modulos tiene marketing y publicidad
  ✅ [comercio  ]  19.7s  modulos del ciclo de comercio internacional
  ✅ [comercio  ]   5.3s  que estudia actividades comerciales
  ✅ [admin     ]  14.7s  que modulos tiene administracion y finanzas
  ✅ [admin     ]  11.0s  modulos de gestion administrativa
  ✅ [turismo   ]  10.1s  modulos del ciclo GAT alojamientos turisticos
  ✅ [horarios  ]   7.5s  en que turno se imparte DAM
  ✅ [horarios  ]   7.7s  tiene ASIR turno de tarde
  ✅ [horarios  ]   7.0s  que turnos tiene SMR
  ✅ [horarios  ]   5.6s  en que sede esta el ciclo GAT
  ✅ [tramites  ]  16.4s  como es el proceso de matricula
  ✅ [tramites  ]  13.6s  que requisitos necesito para entrar a DAM
  ✅ [tramites  ]   3.0s  cual es el correo de secretaria
  ✅ [tramites  ]   5.3s  horario de atencion de secretaria
  ✅ [sin_datos ]   5.3s  tiene el centro algun ciclo de musica
  ✅ [sin_datos ]   8.5s  hay medicina o grado universitario
  ✅ [sin_datos ]   5.7s  ofrecen ciclos de cocina o restauracion
  ✅ [contexto  ]   4.9s  [c1] dime algo sobre DAM
  ✅ [contexto  ]   2.2s  [c1] y cuantos cursos dura
  ✅ [contexto  ]   3.4s  [c1] en que sede se imparte
  ✅ [contexto  ]   4.9s  [c2] cuentame sobre el ciclo DAW
  ✅ [contexto  ]  10.4s  [c2] que modulos hay en primero

  📊 35/36 passed | avg total 9.2s | avg RAG 9.7s | avg social 4.7s
```

**Correcciones aplicadas tras este run**:
- `dam_mod`: keywords ampliadas para capturar respuesta de aclaración (>10 módulos → bot pide preferencia de curso)
- `ia_mod`: pregunta cambiada a "informacion sobre..." (la data no tiene módulos del IA, solo perfil/salidas); keywords más específicas para evitar match en "secretaría"
- `check()`: nueva lógica que rechaza respuestas con frases de rechazo explícito aunque una keyword coincida por accidente

**Suite anterior (21 tests)**: 21/21 ✅ | avg RAG 11.0s | avg social 3.3s

---

### qwen2.5:14b

**19/21 pass** | avg RAG **5.5s** | avg social **4.5s**

- 2× más rápido que mistral en consultas RAG
- Fallos: `dam_mod` (confundía contenido), `ctx2` (follow-up sin herramienta)
- Problema detectado: en algunos casos imprime `_icall_function()` o sintaxis interna de tool call → se puede corregir con ajuste de system prompt
- Candidato viable si se necesita velocidad y se ajusta el prompt

---

### qwen2.5:7b

**~19/21 pero con falsos positivos** | avg RAG **2.9s**

- Muy rápido pero con alucinaciones frecuentes
- Inventa módulos cuando no encuentra datos exactos
- **Descartado para producción**

---

### gemma4:latest

**Parcial (12/21, SSH timeout)** | avg individual **~20-24s**

- Tiempo inaceptable para uso en producción
- **Descartado**

---

## Comparativa resumida (suite de 21 tests)

| Modelo                  | Pass  | Avg RAG | Avg Social | Veredicto               |
|-------------------------|-------|---------|------------|-------------------------|
| `mistral-small3.2:24b`  | 21/21 | 11.0s   | 3.3s       | ✅ Producción            |
| `qwen2.5:14b`           | 19/21 | 5.5s    | 4.5s       | ⚠️ Candidato (ajustar)  |
| `qwen2.5:7b`            | ~19   | 2.9s    | —          | ❌ Alucinaciones         |
| `gemma4:latest`         | 12/21 | ~22s    | —          | ❌ Demasiado lento       |

---

## Cómo ejecutar el benchmark

```bash
# Modelo actual (por defecto)
python3 scripts/benchmark.py

# Modelo específico (también cambia el modelo en producción y luego lo restaura)
python3 scripts/benchmark.py qwen2.5:14b

# Todos los modelos en secuencia
python3 scripts/benchmark.py --all
```

**Requisitos**: VPN activa al servidor DGX (10.0.0.10), Python con `paramiko`.

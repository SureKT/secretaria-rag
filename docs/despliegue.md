# SecretarIA — Guía de Despliegue y Operaciones

## Prerrequisitos

- VPN activa al servidor DGX (10.0.0.10)
- Python 3.11 + `paramiko` (`pip install paramiko`)
- Acceso SSH: los scripts leen el usuario y la contraseña de las variables de entorno
  `DGX_USER` y `DGX_PASSWORD`. No se guardan en el repositorio.

---

## Actualizar el prompt del sistema o el código de la herramienta Consultas

1. Editar `workflows/n8n - SecretarIA.json` localmente:
   - Sistema prompt: nodo `AI Agent` → `parameters.options.systemMessage`
   - Código de búsqueda: nodo `Consultas` → `parameters.jsCode`

2. Desplegar al servidor:
   ```bash
   python3 scripts/deploy_prompt.py
   ```
   El script:
   - Lee el JSON local
   - Extrae el systemMessage y jsCode actualizados
   - Los sube vía SFTP al servidor
   - Actualiza **ambas** tablas: `workflow_entity` y `workflow_history`
   - Reinicia n8n y verifica `healthz`
   - Lanza 3 tests de humo automáticos

### Por qué hay que actualizar dos tablas

n8n en producción lee los nodos de **`workflow_history`** (vía `activeVersionId`), no de `workflow_entity.nodes`. Actualizar solo `workflow_entity` no tiene efecto en tiempo de ejecución.

---

## Cambiar el modelo LLM

```bash
# Cambiar a un modelo concreto y hacer benchmark
python3 scripts/benchmark.py qwen2.5:14b

# Cambiar solo sin benchmark (usando change_model directamente)
# No hay script standalone para esto; usa benchmark.py con 0 tests o
# edita el JSON y haz deploy_prompt.py
```

El script `benchmark.py` restaura automáticamente el modelo original al terminar (si se probó uno diferente).

Para cambio permanente:
1. Editar `workflows/n8n - SecretarIA.json` → nodo `Ollama Chat Model` → `parameters.model`
2. Ejecutar `python3 scripts/deploy_prompt.py`

---

## Añadir o actualizar datos en el RAG (Qdrant)

1. Crear/editar el archivo `.md` correspondiente en `data/`
2. Subir el archivo a través del formulario n8n (Load Data Flow):
   - URL: `http://10.0.0.10:5678/form/<FORM_ID>`
   - Acepta: `.pdf`, `.csv`, `.md`, `.yaml`
3. Los chunks se embedan con `mxbai-embed-large` y se insertan en Qdrant colección `secretaria`

**Importante**: si se re-sube un documento ya existente, los chunks anteriores NO se eliminan automáticamente — se crean duplicados. Para limpiar:
```bash
# Conectar por SSH y ejecutar:
curl -X DELETE http://localhost:6333/collections/secretaria
# Luego recrear la colección y resubir todos los documentos
```

---

## Diagnóstico rápido

### n8n no responde al webhook
```bash
ssh "$DGX_USER"@10.0.0.10
docker ps | grep n8n
docker restart n8n_cerebro
curl http://localhost:5678/healthz
```

### Respuestas vacías o "SSH session not active"
- La VPN se desconectó. Reconectar VPN e intentar de nuevo.
- El modelo Ollama tardó demasiado (>90s timeout curl). Normal con modelos grandes.

### El bot dice "No tengo ese dato" cuando debería tener info
1. Verificar que el documento esté en Qdrant:
   ```bash
   curl http://localhost:6333/collections/secretaria | python3 -m json.tool
   # Comprobar "vectors_count"
   ```
2. Verificar que la query de búsqueda llega al ciclo correcto (revisar logs n8n)
3. Aumentar `limit` en el jsCode de Consultas (actualmente 6)

### Ver logs de n8n
```bash
docker logs n8n_cerebro --tail 50 -f
```

---

## Estructura de scripts

| Script                    | Propósito                                              |
|---------------------------|--------------------------------------------------------|
| `scripts/deploy_prompt.py`| Despliega system prompt + jsCode al servidor           |
| `scripts/deploy_tool.py`  | Antiguo: desplegaba solo el jsCode (obsoleto, usar deploy_prompt.py) |
| `scripts/benchmark.py`    | Benchmark multi-modelo con 35 tests                    |

---

## IDs importantes (no cambiar)

| Elemento              | ID                                       |
|-----------------------|------------------------------------------|
| Workflow ID           | `<WORKFLOW_ID>`                       |
| Version activa        | `<VERSION_ID>`   |
| Webhook ID            | `<WEBHOOK_ID>` |
| Webhook path          | `/webhook/typebot-agent`                 |
| Qdrant collection     | `secretaria`                             |

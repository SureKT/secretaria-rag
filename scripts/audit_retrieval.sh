#!/bin/bash
# Auditoría de retrieval — muestra qué chunks devuelve Qdrant por query, con scores.
# Diagnóstico puro: revela si la inexactitud viene del retrieval o del modelo.
# Uso:  bash audit_retrieval.sh "que modulos tiene DAM"
#       bash audit_retrieval.sh            (corre batería de queries por defecto)

OLLAMA=http://localhost:11434
QDRANT=http://localhost:6333
COLL=secretaria
EMBED_MODEL=mxbai-embed-large:latest
LIMIT=6

audit() {
  local query="$1"
  echo "=================================================================="
  echo "QUERY: $query"
  echo "=================================================================="

  # 1. Embed
  local vector=$(curl -s $OLLAMA/api/embeddings \
    -d "{\"model\":\"$EMBED_MODEL\",\"prompt\":\"$query\"}" \
    | python3 -c "import sys,json; print(json.dumps(json.load(sys.stdin)['embedding']))" 2>/dev/null)

  if [ -z "$vector" ]; then
    echo "ERROR: embedding falló"
    echo ""
    return
  fi

  # 2. Search + format
  curl -s $QDRANT/collections/$COLL/points/search \
    -H 'Content-Type: application/json' \
    -d "{\"vector\":$vector,\"limit\":$LIMIT,\"with_payload\":true}" \
    | python3 -c "
import sys, json
d = json.load(sys.stdin)
pts = d.get('result', [])
if not pts:
    print('  SIN RESULTADOS')
for i, p in enumerate(pts, 1):
    score = p.get('score', 0)
    pl = p.get('payload', {})
    ctx = (pl.get('context') or '')[:80]
    content = (pl.get('content') or '').replace(chr(10), ' ')[:160]
    print(f'  [{i}] score={score:.4f}  ctx=\"{ctx}\"')
    print(f'      {content}...')
    print()
"
  echo ""
}

if [ -n "$1" ]; then
  audit "$1"
else
  # Batería por defecto — casos críticos conocidos
  audit "que modulos tiene DAM"
  audit "que modulos tiene DAW"
  audit "que se estudia en optica"
  audit "que asignaturas tiene optica"
  audit "cuando es el plazo de matricula"
  audit "que becas hay disponibles"
  audit "cual es el horario de secretaria"
fi

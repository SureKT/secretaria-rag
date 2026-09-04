#!/bin/bash
# RAG end-to-end sin n8n: embed query -> search Qdrant (limit 6) -> generate 8B.
# Mide respuesta REAL + latencia. Revela si el ruido de retrieval rompe la respuesta.
OLLAMA=http://localhost:11434
QDRANT=http://localhost:6333
COLL=secretaria
EMBED=mxbai-embed-large:latest
LLM=llama3.1:8b

SYS='Eres SecretarIABot, asistente del Centro de FP Ejemplo. Usa la informacion RELEVANTE del CONTEXTO para responder, aunque haya fragmentos no relacionados (ignoralos). No inventes datos que no esten en el contexto. Solo remite a secretaria si NO hay NADA relevante. Responde directo, breve y en español. NO empieces con disculpas ni con frases como "no se menciona" o "segun la informacion" si vas a dar datos: responde la informacion directamente.'

rag() {
  local q="$1"
  echo "=================================================================="
  echo "PREGUNTA: $q"
  echo "------------------------------------------------------------------"
  local t0=$(date +%s%3N)
  local vec=$(curl -s $OLLAMA/api/embeddings -d "{\"model\":\"$EMBED\",\"prompt\":\"$q\"}" \
    | python3 -c "import sys,json;print(json.dumps(json.load(sys.stdin)['embedding']))")
  local ctx=$(curl -s $QDRANT/collections/$COLL/points/search -H 'Content-Type: application/json' \
    -d "{\"vector\":$vec,\"limit\":8,\"with_payload\":true}" \
    | python3 -c "import sys,json;print(chr(10).join('- '+p['payload'].get('content','') for p in json.load(sys.stdin)['result']))")
  local prompt="CONTEXTO:
$ctx

PREGUNTA: $q"
  curl -s $OLLAMA/api/generate -d "$(python3 -c "import json,sys;print(json.dumps({'model':'$LLM','system':'''$SYS''','prompt':sys.argv[1],'stream':False,'keep_alive':-1,'options':{'num_predict':350}}))" "$prompt")" \
    | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('response','ERROR'))"
  local t1=$(date +%s%3N)
  echo "------------------------------------------------------------------"
  echo "Latencia: $((t1-t0))ms"
  echo ""
}

if [ -n "$1" ]; then rag "$1"; else
  rag "que modulos tiene DAM"
  rag "que modulos tiene DAW"
  rag "que se estudia en optica"
  rag "cuando es el plazo de matricula"
  rag "que becas hay disponibles"
fi

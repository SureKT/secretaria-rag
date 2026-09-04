#!/bin/bash
# Test suite SecretarIA — output a /tmp/test_results.txt
OUT=/tmp/test_results.txt
W=http://localhost:5678/webhook/typebot-agent
H='Content-Type: application/json'
RUN=$(date +%s)  # session IDs únicos por ejecución — evita contaminación de memoria

echo "=== SecretarIA Test Suite $(date) ===" > $OUT
echo "" >> $OUT

echo "--- Qdrant ---" >> $OUT
curl -s http://localhost:6333/collections/secretaria \
  | python3 -c "import sys,json; d=json.load(sys.stdin); r=d['result']; print('puntos:', r['points_count'], '| status:', r['status'])" >> $OUT
echo "" >> $OUT

echo "--- Modelo LLM activo ---" >> $OUT
curl -s http://localhost:5678/api/v1/workflows 2>/dev/null | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    for w in d.get('data', []):
        for n in w.get('nodes', []):
            if 'lmChat' in n.get('type','') or 'Ollama' in n.get('name',''):
                print(n['name'], '->', n.get('parameters',{}).get('model','?'))
except: print('sin acceso API n8n')
" >> $OUT
echo "" >> $OUT

run_test() {
  local name="$1"
  local query="$2"
  local sid="$3"
  echo "--- TEST: $name ---" >> $OUT
  local start=$(date +%s%3N)
  local resp=$(curl -s -m 120 -X POST $W -H "$H" \
    -d "{\"pregunta\": \"$query\", \"sessionId\": \"$sid\"}")
  local end=$(date +%s%3N)
  local ms=$((end - start))
  echo "Tiempo: ${ms}ms" >> $OUT
  echo "$resp" >> $OUT
  echo "" >> $OUT
  echo "" >> $OUT
}

# Tests rápidos (sin tool call esperado)
run_test "Saludo"               "hola"                                              "$RUN-hola"
run_test "Familia inexistente"  "que ciclos tiene la familia de musica"             "$RUN-nodata"

# Tests con tool call
run_test "DAM modulos"          "que modulos tiene DAM"                             "$RUN-dam"
run_test "DAW modulos"          "que modulos tiene DAW"                             "$RUN-daw"
run_test "Optica modulos"       "que modulos tiene optica"                          "$RUN-opt"
run_test "Optica estudia"       "que se estudia en optica"                          "$RUN-opt2"
run_test "SMR info"             "informacion sobre SMR"                             "$RUN-smr"
run_test "Becas"                "que becas hay disponibles"                         "$RUN-becas"
run_test "Horario secretaria"   "cual es el horario de secretaria"                  "$RUN-horario"
run_test "Matricula cuando"     "cuando es el plazo de matricula"                   "$RUN-matricula"

echo "=== FIN $(date) ===" >> $OUT
echo "Resultados en $OUT"
cat $OUT

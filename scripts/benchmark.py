#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Benchmark SecretarIA v1 con múltiples modelos.
Uso: python3 scripts/benchmark.py [modelo]
     python3 scripts/benchmark.py --all

Tests tuple: (id, categoría, pregunta, keywords[, chain_id])
  - chain_id: tests with the same chain_id share a session (for memory tests).
    If omitted, each test gets its own isolated session.
"""
import paramiko, json, os, sys, io, time, argparse

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# ── Tests ────────────────────────────────────────────────────────────────────
TESTS = [
    # (id, categoría, pregunta, keywords[, chain_id])

    # ── Social (no tool needed) ─────────────────────────────────────────────
    ("hola",       "social",    "hola",                               ["hola","ayud"]),
    ("adios",      "social",    "gracias, hasta luego",               ["hola","hasta","gracias"]),

    # ── Familias (memory, no tool) ──────────────────────────────────────────
    ("familias",   "familias",  "que familias profesionales hay",     ["informatica","sanidad","turismo"]),
    ("sede_com",   "familias",  "donde esta la familia de comercio",  ["gregorio","gea","34"]),

    # ── Informática ─────────────────────────────────────────────────────────
    ("dam_mod",    "informatica","que modulos tiene DAM",             ["bases de datos","programacion","primer","segundo","acceso a datos","interfaces"]),
    ("daw_mod",    "informatica","modulos del ciclo DAW",             ["marcas","entorno","bases","programacion","cliente","servidor"]),
    ("smr_info",   "informatica","informacion sobre SMR microinformatica",["redes","sistemas","smr","montaje"]),
    ("asir_mod",   "informatica","que se estudia en ASIR",            ["administracion","sistemas","redes","servicios"]),
    ("ia_mod",     "informatica","informacion sobre el curso de inteligencia artificial y big data", ["big data","inteligencia artificial","especializacion","titulados","grado superior"]),
    ("ciber_info", "informatica","que es el curso de ciberseguridad", ["ciberseguridad","seguridad","especializacion","vulnerabilidad"]),

    # ── Sanidad ─────────────────────────────────────────────────────────────
    ("opt_mod",    "sanidad",   "que modulos tiene optica de anteojeria", ["lentes","optica","fabricacion","monturas"]),
    ("enf_mod",    "sanidad",   "que asignaturas tiene enfermeria",   ["enfermeria","cuidados","anatomia","sanitari"]),
    ("lab_mod",    "sanidad",   "modulos de laboratorio clinico",     ["laboratorio","bioquimica","analisis","clinico"]),
    ("pt_mod",     "sanidad",   "que estudia protesis dental",        ["protesis","dental","laboratorio"]),

    # ── Comercio y Marketing ────────────────────────────────────────────────
    ("mp_mod",     "comercio",  "que modulos tiene marketing y publicidad", ["marketing","publicidad","investigacion","campana","digital"]),
    ("ci_mod",     "comercio",  "modulos del ciclo de comercio internacional", ["internacional","logistica","transporte","negociacion","exportacion"]),
    ("ac_mod",     "comercio",  "que estudia actividades comerciales", ["venta","comercio","almacen","punto de venta","compra"]),

    # ── Administración ──────────────────────────────────────────────────────
    ("ade_mod",    "admin",     "que modulos tiene administracion y finanzas", ["contabilidad","finanzas","administracion","empresa"]),
    ("ga_mod",     "admin",     "modulos de gestion administrativa",  ["contabilidad","administrativ","empresa","documentacion","compraventa"]),

    # ── Turismo ─────────────────────────────────────────────────────────────
    ("gat_mod",    "turismo",   "modulos del ciclo GAT alojamientos turisticos", ["turismo","alojamiento","recepcion","pisos","reservas","marketing"]),

    # ── Turnos y sedes ──────────────────────────────────────────────────────
    ("dam_turno",  "horarios",  "en que turno se imparte DAM",        ["semipresencial"]),
    ("asir_turno", "horarios",  "tiene ASIR turno de tarde",          ["no","manana"]),
    ("smr_turno",  "horarios",  "que turnos tiene SMR",               ["manana","semipresencial"]),
    ("gat_sede",   "horarios",  "en que sede esta el ciclo GAT",      ["central","sede","principal"]),

    # ── Trámites / secretaría ───────────────────────────────────────────────
    ("matricula",  "tramites",  "como es el proceso de matricula",    ["matricula","plazo","secretaria","admision"]),
    ("requisitos", "tramites",  "que requisitos necesito para entrar a DAM", ["bachillerato","ciclo","acceso","titulo"]),
    ("sec_email",  "tramites",  "cual es el correo de secretaria",    ["centro-ejemplo","secretaria@centro-ejemplo"]),
    ("sec_hora",   "tramites",  "horario de atencion de secretaria",  ["lunes","viernes","09","secretaria"]),

    # ── Sin datos (rechazo correcto) ────────────────────────────────────────
    ("musica",     "sin_datos", "tiene el centro algun ciclo de musica", ["no","musica","familia"]),
    ("medicina",   "sin_datos", "hay medicina o grado universitario", ["no","universidad","fp","formacion"]),
    ("cocina",     "sin_datos", "ofrecen ciclos de cocina o restauracion", ["no","familia","hosteleria","restaur"]),

    # ── Contexto / memoria (misma sesión por cadena) ─────────────────────────
    # Cadena 1: DAM
    ("ctx1",       "contexto",  "dime algo sobre DAM",               ["dam","multiplataforma"],          "c1"),
    ("ctx2",       "contexto",  "y cuantos cursos dura",             ["dos","2","curso","anos"],          "c1"),
    ("ctx3",       "contexto",  "en que sede se imparte",            ["central","central","principal"],  "c1"),
    # Cadena 2: DAW
    ("ctx4",       "contexto",  "cuentame sobre el ciclo DAW",       ["daw","web","aplicacion"],          "c2"),
    ("ctx5",       "contexto",  "que modulos hay en primero",        ["marcas","sistemas","bases","programacion","entornos"], "c2"),
]

MODELS = {
    "mistral-small3.2:24b": "mistral-small3.2:24b",
    "qwen2.5:14b":          "qwen2.5:14b",
    "qwen2.5:7b":           "qwen2.5:7b",
    "gemma4:latest":        "gemma4:latest",
}

WEBHOOK = "http://localhost:5678/webhook/typebot-agent"

def run_test(ssh, pregunta, sid, timeout=90):
    body = '{"pregunta":"' + pregunta.replace('"','') + '","sessionId":"' + sid + '"}'
    cmd = ("curl -s -m " + str(timeout) + " -w '\\n[TIME:%{time_total}s]' "
           "-X POST " + WEBHOOK + " "
           "-H 'Content-Type: application/json' -d '" + body + "'")
    t0 = time.time()
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout+5)
    out = stdout.read().decode('utf-8').strip()
    wall = time.time() - t0
    ct = float(out.split('[TIME:')[1].rstrip(']').rstrip('s')) if '[TIME:' in out else wall
    out = out.split('\n[TIME:')[0] if '\n[TIME:' in out else out
    try:
        ans = json.loads(out).get('output', out)
    except:
        ans = out
    return ans, ct

def normalize(s):
    import unicodedata
    return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn').lower()

REFUSAL_PHRASES = ["no tengo ese dato", "contacta con secretaria"]

def check(ans, keywords):
    ans_n = normalize(ans)
    # Reject hard refusals even if a keyword accidentally matches
    if any(normalize(r) in ans_n for r in REFUSAL_PHRASES):
        return False
    return any(normalize(kw) in ans_n for kw in keywords)

def change_model(ssh, model_name):
    """Update model in workflow_entity and workflow_history, restart n8n."""
    sftp = ssh.open_sftp()
    with sftp.open('/tmp/get_we2.sql', 'w') as f:
        f.write("SELECT nodes FROM workflow_entity WHERE id = '<WORKFLOW_ID>';")
    sftp.close()
    stdin, stdout, stderr = ssh.exec_command(
        'docker cp /tmp/get_we2.sql postgres_db:/tmp/get_we2.sql && '
        'docker exec postgres_db psql -U postgres -d SecretarIA -t -f /tmp/get_we2.sql 2>&1',
        timeout=15)
    nodes = json.loads(stdout.read().decode('utf-8').strip())
    for node in nodes:
        if node.get('name') == 'Ollama Chat Model':
            node['parameters']['model'] = model_name
            break
    nodes_json = json.dumps(nodes, ensure_ascii=True)
    sftp = ssh.open_sftp()
    with sftp.open('/tmp/nodes_model.json', 'wb') as f:
        f.write(nodes_json.encode('ascii'))
    with sftp.open('/tmp/update_model.sql', 'w') as f:
        f.write("""
UPDATE workflow_entity SET nodes=(pg_read_file('/tmp/nodes_model.json'))::json,
"updatedAt"=NOW() WHERE id='<WORKFLOW_ID>';
UPDATE workflow_history SET nodes=(pg_read_file('/tmp/nodes_model.json'))::json,
"updatedAt"=NOW() WHERE "versionId"='<VERSION_ID>';
""")
    sftp.close()
    stdin, stdout, stderr = ssh.exec_command(
        'docker cp /tmp/nodes_model.json postgres_db:/tmp/nodes_model.json && '
        'docker cp /tmp/update_model.sql postgres_db:/tmp/update_model.sql && '
        'docker exec postgres_db psql -U postgres -d SecretarIA -f /tmp/update_model.sql && '
        'docker restart n8n_cerebro',
        timeout=35)
    stdout.read()
    time.sleep(12)
    stdin, stdout, stderr = ssh.exec_command('curl -s http://localhost:5678/healthz', timeout=10)
    ok = 'ok' in stdout.read().decode('utf-8')
    print(f"  n8n {'✅' if ok else '❌'} after model change to {model_name}")
    return ok

def benchmark_model(ssh, model_name, tests, run_ts):
    print(f"\n{'='*65}")
    print(f"  MODELO: {model_name}")
    print(f"{'='*65}")
    results = []
    model_prefix = model_name[:6].replace(':','_')
    for row in tests:
        tid, cat, pregunta, keywords = row[0], row[1], row[2], row[3]
        chain_id = row[4] if len(row) > 4 else None
        # Use run_ts to get fresh sessions on each benchmark run (avoids
        # session-memory contamination from previous runs with same IDs)
        sid = f"bm{run_ts}-{model_prefix}-{chain_id}" if chain_id else f"bm{run_ts}-{model_prefix}-{tid}"
        ans, t = run_test(ssh, pregunta, sid)
        passed = check(ans, keywords) and 'code' not in ans[:5]
        icon = '✅' if passed else '❌'
        chain_tag = f"[↩{chain_id}]" if chain_id else "      "
        ans_short = ans[:85].replace('\n', ' ')
        print(f"  {icon} [{cat:10}] {t:5.1f}s {chain_tag}  {pregunta[:38]:38}  →  {ans_short}")
        results.append({'id': tid, 'cat': cat, 'q': pregunta, 't': t, 'pass': passed, 'ans': ans[:200]})
    ok = sum(r['pass'] for r in results)
    avg = sum(r['t'] for r in results) / len(results)
    rag_cats = ('social', 'familias')
    rag_times = [r['t'] for r in results if r['cat'] not in rag_cats]
    avg_rag = sum(rag_times)/len(rag_times) if rag_times else 0
    social_times = [r['t'] for r in results if r['cat'] in rag_cats]
    avg_social = sum(social_times)/len(social_times) if social_times else 0
    print(f"\n  📊 {ok}/{len(results)} passed | avg total {avg:.1f}s | avg RAG {avg_rag:.1f}s | avg social {avg_social:.1f}s")
    return results

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('model', nargs='?', default='current', help='Model name or "all"')
    args = parser.parse_args()

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect('10.0.0.10', username=os.environ['DGX_USER'], password=os.environ['DGX_PASSWORD'], timeout=15)
    ssh.get_transport().set_keepalive(20)  # Send keepalive every 20s to avoid VPN timeout

    # Check current model
    sftp = ssh.open_sftp()
    with sftp.open('/tmp/cur_model.sql', 'w') as f:
        f.write("SELECT n->'parameters'->>'model' FROM workflow_entity, "
                "json_array_elements(nodes) n WHERE id='<WORKFLOW_ID>' "
                "AND n->>'name'='Ollama Chat Model';")
    sftp.close()
    stdin, stdout, stderr = ssh.exec_command(
        'docker cp /tmp/cur_model.sql postgres_db:/tmp/cur_model.sql && '
        'docker exec postgres_db psql -U postgres -d SecretarIA -t -f /tmp/cur_model.sql 2>&1',
        timeout=10)
    cur = stdout.read().decode('utf-8').strip()
    print(f"Modelo actual en DB: {cur}")

    if args.model == 'all':
        models_to_test = list(MODELS.keys())
    elif args.model == 'current':
        models_to_test = [cur]
    else:
        models_to_test = [args.model]

    all_results = {}
    original_model = cur
    run_ts = str(int(time.time()))[-5:]  # 5-digit suffix unique per run

    for i, model in enumerate(models_to_test):
        if model != cur or i > 0:
            print(f"\nCambiando modelo a {model}...")
            change_model(ssh, model)
            cur = model
        all_results[model] = benchmark_model(ssh, model, TESTS, run_ts)

    # Restore original model if changed
    if cur != original_model:
        print(f"\nRestaurando modelo original: {original_model}")
        change_model(ssh, original_model)

    # Summary table
    if len(all_results) > 1:
        all_cats = sorted({r['cat'] for res in all_results.values() for r in res})
        fast_cats = ('social', 'familias')
        print(f"\n{'='*75}")
        print("  RESUMEN COMPARATIVO")
        print(f"{'='*75}")
        print(f"  {'Modelo':30} {'Pass':8} {'Avg RAG':10} {'Avg Social':12}  Fallos")
        print(f"  {'-'*72}")
        for model, res in all_results.items():
            ok = sum(r['pass'] for r in res)
            rag = [r['t'] for r in res if r['cat'] not in fast_cats]
            soc = [r['t'] for r in res if r['cat'] in fast_cats]
            avg_r = sum(rag)/len(rag) if rag else 0
            avg_s = sum(soc)/len(soc) if soc else 0
            fails = [r['id'] for r in res if not r['pass']]
            fail_str = ', '.join(fails) if fails else '-'
            print(f"  {model:30} {ok}/{len(res):6}   {avg_r:6.1f}s     {avg_s:6.1f}s    {fail_str}")
        # Per-category pass rates
        print(f"\n  {'Categoría':14}", end='')
        for model in all_results:
            print(f"  {model[:16]:16}", end='')
        print()
        for cat in all_cats:
            print(f"  {cat:14}", end='')
            for res in all_results.values():
                cat_res = [r for r in res if r['cat'] == cat]
                if cat_res:
                    pct = 100*sum(r['pass'] for r in cat_res)//len(cat_res)
                    print(f"  {pct:3d}% ({sum(r['pass'] for r in cat_res)}/{len(cat_res)})   ", end='')
                else:
                    print(f"  {'—':16}", end='')
            print()

    ssh.close()

if __name__ == '__main__':
    main()

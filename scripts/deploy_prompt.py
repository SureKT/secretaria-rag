#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deploy updated system prompt + vector search tool to n8n server."""
import paramiko, json, os, sys, io, time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

WF_PATH = (r"C:\SavesFormateoPortatil\SSD_Storage\Sure_Programming"
           r"\IABD\Proyectos Final\SecretarIA\workflows\n8n - SecretarIA.json")

with open(WF_PATH, encoding='utf-8') as f:
    wf_local = json.load(f)

# Extract AI Agent system message and Consultas jsCode from local file
local_nodes = {n['name']: n for n in wf_local['nodes']}
new_system_msg = local_nodes['AI Agent']['parameters']['options']['systemMessage']
new_jscode = local_nodes['Consultas']['parameters']['jsCode']

print(f"systemMessage length: {len(new_system_msg)}")
print(f"jsCode length: {len(new_jscode)}")
print(f"$input in jsCode: {'$input' in new_jscode}")

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('10.0.0.10', username=os.environ['DGX_USER'], password=os.environ['DGX_PASSWORD'], timeout=15)
sftp = ssh.open_sftp()

# Get current nodes from workflow_entity (n8n reads from here at runtime)
with sftp.open('/tmp/get_we.sql', 'w') as f:
    f.write("SELECT nodes FROM workflow_entity WHERE id = '<WORKFLOW_ID>';")
sftp.close()

stdin, stdout, stderr = ssh.exec_command(
    'docker cp /tmp/get_we.sql postgres_db:/tmp/get_we.sql && '
    'docker exec postgres_db psql -U postgres -d SecretarIA -t -f /tmp/get_we.sql 2>&1',
    timeout=15)
raw = stdout.read().decode('utf-8').strip()
nodes = json.loads(raw)

# Patch AI Agent + Consultas nodes
for node in nodes:
    if node.get('name') == 'AI Agent':
        node['parameters']['options']['systemMessage'] = new_system_msg
        print("AI Agent system prompt updated")
    elif node.get('name') == 'Consultas':
        node['parameters']['jsCode'] = new_jscode
        print("Consultas jsCode updated")

nodes_json = json.dumps(nodes, ensure_ascii=True)
print(f"Serialized JSON length: {len(nodes_json)}")

sftp = ssh.open_sftp()
with sftp.open('/tmp/nodes_final.json', 'wb') as f:
    f.write(nodes_json.encode('ascii'))

# Verify $input made it into the file
with sftp.open('/tmp/nodes_final.json', 'rb') as f:
    content = f.read()
print(f"$input in file: {'$input'.encode() in content}")

# Also update workflow_history for the active version
with sftp.open('/tmp/update_final.sql', 'w') as f:
    f.write("""
-- Update workflow_entity (runtime source)
UPDATE workflow_entity
SET nodes = (pg_read_file('/tmp/nodes_final.json'))::json,
    \"updatedAt\" = NOW()
WHERE id = '<WORKFLOW_ID>';

-- Update workflow_history (version history)
UPDATE workflow_history
SET nodes = (pg_read_file('/tmp/nodes_final.json'))::json,
    \"updatedAt\" = NOW()
WHERE \"versionId\" = '<VERSION_ID>';

SELECT 'done' as status;
""")
sftp.close()

stdin, stdout, stderr = ssh.exec_command(
    'docker cp /tmp/nodes_final.json postgres_db:/tmp/nodes_final.json && '
    'docker cp /tmp/update_final.sql postgres_db:/tmp/update_final.sql && '
    'docker exec postgres_db psql -U postgres -d SecretarIA -f /tmp/update_final.sql 2>&1',
    timeout=20)
print("DB:", stdout.read().decode('utf-8').strip())

# Verify in DB
sftp = ssh.open_sftp()
with sftp.open('/tmp/verify.sql', 'w') as f:
    f.write("""SELECT LEFT(n->'parameters'->>'jsCode', 60) as jscode_start
FROM workflow_entity, json_array_elements(nodes) n
WHERE id = '<WORKFLOW_ID>' AND n->>'name'='Consultas';""")
sftp.close()
stdin, stdout, stderr = ssh.exec_command(
    'docker cp /tmp/verify.sql postgres_db:/tmp/verify.sql && '
    'docker exec postgres_db psql -U postgres -d SecretarIA -f /tmp/verify.sql 2>&1',
    timeout=10)
print("Verify:", stdout.read().decode('utf-8').strip())

# Restart n8n
print("\nRestarting n8n...")
stdin, stdout, stderr = ssh.exec_command('docker restart n8n_cerebro', timeout=30)
stdout.read()
time.sleep(12)
stdin, stdout, stderr = ssh.exec_command('curl -s http://localhost:5678/healthz', timeout=10)
print("Health:", stdout.read().decode('utf-8').strip())

# Test
def test(label, pregunta, sid):
    body = '{"pregunta":"' + pregunta + '","sessionId":"' + sid + '"}'
    cmd = ("curl -s -m 90 -w '\\n[TIME:%{time_total}s]' -X POST "
           "http://localhost:5678/webhook/typebot-agent "
           "-H 'Content-Type: application/json' -d '" + body + "'")
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=95)
    out = stdout.read().decode('utf-8').strip()
    ct = out.split('[TIME:')[1].rstrip(']') if '[TIME:' in out else '?'
    out = out.split('\n[TIME:')[0] if '\n[TIME:' in out else out
    try:
        ans = json.loads(out).get('output', out)
    except:
        ans = out
    bad = 'no tengo' in ans.lower() or 'code' in ans[:5]
    icon = '❌' if bad else '✅'
    print(f"{icon} [{label}] {ct}s")
    print(f"   {ans[:250]}")
    print()

print()
test("Optica modulos", "que modulos tiene optica", "fp-opt-1")
test("Saludo",         "hola",                      "fp-hola-1")
test("DAM modulos",    "que modulos tiene DAM",      "fp-dam-1")

ssh.close()

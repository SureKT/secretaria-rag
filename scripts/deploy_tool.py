#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deploy fixed Consultas tool (vector search) to n8n server via SSH."""
import paramiko, json, os, sys, io, time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

NEW_JS_CODE = (
    "const query = (($input.first() || {}).json.query"
    " || ($input.first() || {}).json.input || '').toString().trim();\n"
    "if (!query) return 'No se encontraron resultados.';\n"
    "\n"
    "const httpPost = (hostname, port, path, body) => new Promise((resolve, reject) => {\n"
    "  const http = require('http');\n"
    "  const bodyStr = JSON.stringify(body);\n"
    "  const req = http.request({\n"
    "    hostname: hostname, port: port, path: path, method: 'POST',\n"
    "    headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(bodyStr) }\n"
    "  }, function(res) {\n"
    "    let d = '';\n"
    "    res.on('data', function(c) { d += c; });\n"
    "    res.on('end', function() { try { resolve(JSON.parse(d)); } catch(e) { reject(e); } });\n"
    "  });\n"
    "  req.on('error', reject);\n"
    "  req.write(bodyStr);\n"
    "  req.end();\n"
    "});\n"
    "\n"
    "const embedRes = await httpPost('10.0.0.10', 11434, '/api/embeddings', {\n"
    "  model: 'mxbai-embed-large:latest',\n"
    "  prompt: query\n"
    "});\n"
    "\n"
    "const vector = (embedRes && embedRes.embedding) ? embedRes.embedding : null;\n"
    "if (!vector) return 'Error embedding: ' + JSON.stringify(embedRes).slice(0,100);\n"
    "\n"
    "const searchRes = await httpPost('qdrant', 6333, '/collections/secretaria/points/search', {\n"
    "  vector: vector,\n"
    "  limit: 6,\n"
    "  with_payload: true\n"
    "});\n"
    "\n"
    "const points = (searchRes && searchRes.result) ? searchRes.result : [];\n"
    "if (points.length === 0) return 'No se encontro informacion sobre: ' + query;\n"
    "\n"
    "return points\n"
    "  .map(function(p) { return (p.payload && p.payload.content) ? p.payload.content : ''; })\n"
    "  .filter(function(c) { return c.length > 0; })\n"
    "  .join('\\n\\n---\\n\\n');\n"
)

# Verify $input is present
assert '$input' in NEW_JS_CODE, "ERROR: $input not found in code!"
print(f"Code OK, length={len(NEW_JS_CODE)}, $input present")

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('10.0.0.10', username=os.environ['DGX_USER'], password=os.environ['DGX_PASSWORD'], timeout=15)
sftp = ssh.open_sftp()

# Get current nodes from workflow_history
with sftp.open('/tmp/get_h.sql', 'w') as f:
    f.write("SELECT nodes FROM workflow_history WHERE \"versionId\" = '<VERSION_ID>';")
sftp.close()

stdin, stdout, stderr = ssh.exec_command(
    'docker cp /tmp/get_h.sql postgres_db:/tmp/get_h.sql && '
    'docker exec postgres_db psql -U postgres -d SecretarIA -t -f /tmp/get_h.sql 2>&1',
    timeout=15)
raw = stdout.read().decode('utf-8').strip()
nodes = json.loads(raw)

# Patch Consultas node
for node in nodes:
    if node.get('name') == 'Consultas':
        node['parameters']['jsCode'] = NEW_JS_CODE
        print("Consultas node patched")
        break

# Serialize and write to server
nodes_json = json.dumps(nodes, ensure_ascii=True)
assert '$input' in nodes_json or '\\u0024input' in nodes_json or '$input' in nodes_json
print(f"JSON serialized, length={len(nodes_json)}")

# Write JSON file
sftp = ssh.open_sftp()
with sftp.open('/tmp/nodes_vec.json', 'wb') as f:
    f.write(nodes_json.encode('ascii'))

# Verify $input in written file
with sftp.open('/tmp/nodes_vec.json', 'rb') as f:
    sample = f.read(5000).decode('ascii')
idx = sample.find('$input')
print(f"$input in file at position: {idx}" if idx >= 0 else "WARNING: $input NOT in file!")
if idx >= 0:
    print("Context:", repr(sample[max(0,idx-10):idx+30]))

# SQL update
with sftp.open('/tmp/update_vec.sql', 'w') as f:
    f.write("""
UPDATE workflow_history
SET nodes = (pg_read_file('/tmp/nodes_vec.json'))::json,
    \"updatedAt\" = NOW()
WHERE \"versionId\" = '<VERSION_ID>';
SELECT 'done' as status;
""")
sftp.close()

stdin, stdout, stderr = ssh.exec_command(
    'docker cp /tmp/nodes_vec.json postgres_db:/tmp/nodes_vec.json && '
    'docker cp /tmp/update_vec.sql postgres_db:/tmp/update_vec.sql && '
    'docker exec postgres_db psql -U postgres -d SecretarIA -f /tmp/update_vec.sql 2>&1',
    timeout=20)
print("DB update:", stdout.read().decode('utf-8').strip())

# Restart n8n
print("Restarting n8n...")
stdin, stdout, stderr = ssh.exec_command('docker restart n8n_cerebro', timeout=30)
stdout.read()
time.sleep(10)
stdin, stdout, stderr = ssh.exec_command('curl -s http://localhost:5678/healthz', timeout=10)
print("Health:", stdout.read().decode('utf-8').strip())

# Test Optica
body = '{"pregunta":"que modulos tiene optica","sessionId":"vec-test-1"}'
cmd = (f"curl -s -m 90 -w '\\n[TIME:%{{time_total}}s]' -X POST "
       f"http://localhost:5678/webhook/typebot-agent "
       f"-H 'Content-Type: application/json' -d '{body}'")
stdin, stdout, stderr = ssh.exec_command(cmd, timeout=95)
out = stdout.read().decode('utf-8').strip()
ct = out.split('[TIME:')[1].rstrip(']') if '[TIME:' in out else '?'
out = out.split('\n[TIME:')[0] if '\n[TIME:' in out else out
try:
    ans = json.loads(out).get('output', out)
except:
    ans = out
print(f"\nOptica [{ct}s]: {ans[:350]}")
ssh.close()

import { readFileSync, readdirSync } from 'fs';
import { join, extname, basename } from 'path';

const OLLAMA_URL = 'http://localhost:11434';
const QDRANT_URL = 'http://localhost:6333';
const COLLECTION = 'secretaria';
const EMBED_MODEL = 'mxbai-embed-large:latest';
const DATA_DIR = new URL('../data', import.meta.url).pathname.replace(/^\/([A-Z]:)/, '$1');
const CHUNK_SIZE = 500;    // chars por chunk
const CHUNK_OVERLAP = 100; // solapamiento

// ─── Qdrant: crear colección con índice full-text ───────────────────────────
async function createCollection() {
  // Borrar colección existente si hay
  await fetch(`${QDRANT_URL}/collections/${COLLECTION}`, { method: 'DELETE' });

  // Crear colección
  const res = await fetch(`${QDRANT_URL}/collections/${COLLECTION}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      vectors: { size: 1024, distance: 'Cosine' }
    })
  });
  const j = await res.json();
  console.log('Colección creada:', j.status || j.result);

  // Crear índices full-text en content y context
  const ftSchema = { type: 'text', tokenizer: 'word', min_token_len: 2, max_token_len: 40, lowercase: true };
  for (const field of ['content', 'context']) {
    const idxRes = await fetch(`${QDRANT_URL}/collections/${COLLECTION}/index`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ field_name: field, field_schema: ftSchema })
    });
    const idxJ = await idxRes.json();
    console.log(`Índice full-text [${field}]:`, idxJ.status || idxJ.result);
  }
}

// ─── Ollama: embed ──────────────────────────────────────────────────────────
async function embed(text) {
  const res = await fetch(`${OLLAMA_URL}/api/embeddings`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model: EMBED_MODEL, prompt: text })
  });
  const j = await res.json();
  if (!j.embedding || j.embedding.length !== 1024) {
    console.error(`\n❌ EMBED ERROR: got ${j.embedding?.length ?? 'null'} dims. Response:`, JSON.stringify(j).slice(0, 200));
  }
  return j.embedding;
}

// ─── Chunking jerárquico con contexto completo ─────────────────────────────
// Devuelve [{content, context}] donde context incluye la jerarquía h1>h2>h3>h4
function chunkText(rawText) {
  const text = rawText.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
  const lines = text.split('\n');

  const results = []; // [{content, h1, h2, h3, h4}]
  let h1 = '', h2 = '', h2line = '', h3 = '', h3line = '', h4 = '';
  let buffer = [];

  const flush = () => {
    const content = buffer.join('\n').trim();
    // Cuerpo sin líneas de encabezado: si no hay cuerpo real, es chunk header-only
    // (solo título, sin info) → ruido en retrieval. Descartar.
    const body = content.split('\n').filter(l => !l.trim().startsWith('#')).join('').trim();
    if (content.length > 30 && body.length >= 40) {
      results.push({ content, h1, h2, h3, h4 });
    }
    buffer = [];
  };

  for (const line of lines) {
    if (line.startsWith('# ') && !line.startsWith('## ')) {
      flush();
      h1 = line.replace(/^# /, '').trim();
      h2 = ''; h2line = ''; h3 = ''; h3line = ''; h4 = '';
      buffer.push(line);
    } else if (line.startsWith('## ') && !line.startsWith('### ')) {
      flush();
      h2 = line.replace(/^## /, '').trim();
      h2line = line;
      h3 = ''; h3line = ''; h4 = '';
      buffer.push(line);
    } else if (line.startsWith('### ') && !line.startsWith('#### ')) {
      flush();
      h3 = line.replace(/^### /, '').trim();
      h3line = line;
      h4 = '';
      if (h2line) buffer.push(h2line);
      buffer.push(line);
    } else if (line.startsWith('#### ')) {
      // Si el h3 padre es "Módulos profesionales", NO partir: mantener
      // 1.º + 2.º + otros módulos en un solo chunk completo (evita fragmentación
      // y que el chunk "otros módulos" rankee sobre la lista real).
      const h3norm = h3.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
      if (h3norm.includes('modulos')) {
        buffer.push(line); // sigue dentro del chunk del h3 de módulos
      } else {
        flush();
        h4 = line.replace(/^#### /, '').trim();
        // Prepend parent headings para contexto completo en el embedding
        if (h2line) buffer.push(h2line);
        if (h3line) buffer.push(h3line);
        buffer.push(line);
      }
    } else {
      buffer.push(line);
    }
  }
  flush();

  // Construir context prefix para cada chunk
  // context se normaliza (sin acentos, minúsculas) para full-text search en Qdrant
  const norm = s => s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
  return results.map(r => {
    const parts = [r.h1, r.h2, r.h3, r.h4].filter(Boolean);
    const context = parts.length > 0 ? `[${norm(parts.join(' > '))}]\n` : '';
    return { content: r.content, context };
  });
}

// ─── Qdrant: insertar batch ─────────────────────────────────────────────────
async function upsertBatch(points) {
  const res = await fetch(`${QDRANT_URL}/collections/${COLLECTION}/points?wait=true`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ points })
  });
  const j = await res.json();
  if (j.status !== 'ok') {
    console.error(`\n❌ UPSERT ERROR (ids ${points[0].id}–${points.at(-1).id}):`, JSON.stringify(j));
  }
  return j;
}

// ─── Enriquecer contenido — prefijo ciclo para chunks de módulos ────────────
function enrichContent(context, content) {
  const match = context.match(/\[([^\]]+)\]/);
  if (!match) return content;

  const parts = match[1].split(' > ').map(s => s.trim());
  const [h1, h2, h3, h4] = [parts[0]||'', parts[1]||'', parts[2]||'', parts[3]||''];

  // Chunks de módulos (h3 = "Módulos profesionales"). context normalizado → "modulos".
  if (h2 && h3 && h3.includes('modulos')) {
    const abbrev = h2.match(/\(([^)–]+)/)?.[1]?.trim() || '';
    const prefix = abbrev ? `${abbrev} - ${h2}\n` : `${h2}\n`;
    return prefix + content;
  }

  return content;
}

// ─── Preamble natural para mejorar retrieval ────────────────────────────────
function buildPreamble(context, content) {
  // context tiene formato: "[h1 > h2 > h3 > h4]\n"
  const match = context.match(/\[([^\]]+)\]/);
  if (!match) return context;

  // NOTA: context está normalizado (sin acentos, minúsculas) → comparar con literales sin acento.
  const parts = match[1].split(' > ').map(s => s.trim());
  const [h1, h2, h3, h4] = [parts[0]||'', parts[1]||'', parts[2]||'', parts[3]||''];

  // BECAS — no son ciclos; etiquetar como becas/ayudas para que rankeen en queries de becas
  if (h1.includes('beca') || h2.includes('beca')) {
    const name = h2 || h1;
    return `Becas y ayudas económicas disponibles para el alumnado del Centro de FP Ejemplo: ${name}. ${context}`;
  }

  // CICLOS FORMATIVOS — solo documentos de familia profesional
  if (h1.includes('familia profesional')) {
    if (h2 && h3 && h3.includes('modulos')) {
      return `Módulos y asignaturas del ciclo ${h2} del Centro de FP Ejemplo. ${context}`;
    }
    if (h2 && h3 && h3.includes('informacion general')) {
      return `Información general del ciclo ${h2}: sede, turno, modalidad. ${context}`;
    }
    if (h2 && h3 && (h3.includes('perfil') || h3.includes('competencias'))) {
      return `Perfil profesional y competencias del ciclo ${h2}. ${context}`;
    }
    if (h2 && h3 && h3.includes('salidas')) {
      return `Salidas profesionales del ciclo ${h2}. ${context}`;
    }
    if (h2 && h3) return `${h2} - ${h3}. ${context}`;
    if (h2) return `Ciclo formativo ${h2} del Centro de FP Ejemplo. ${context}`;
  }

  // OTROS DOCS (matrícula, trámites, logística, FAQ) — sin etiqueta "ciclo"
  const tail = [h2, h3, h4].filter(Boolean).join(' - ');
  return tail ? `${tail}. ${context}` : context;
}

// ─── Main ────────────────────────────────────────────────────────────────────
async function main() {
  await createCollection();

  const files = readdirSync(DATA_DIR)
    .filter(f => extname(f) === '.md' || extname(f) === '.yaml' || extname(f) === '.yml');

  let totalPoints = 0;
  let idCounter = 1;

  for (const file of files) {
    const filePath = join(DATA_DIR, file);
    const text = readFileSync(filePath, 'utf-8');
    const chunks = chunkText(text);

    // Extraer título del documento (primera línea # o nombre de archivo)
    const normalized = text.replace(/\r\n/g, '\n');
    const titleMatch = normalized.match(/^#\s+(.+)/m);
    const docTitle = titleMatch ? titleMatch[1].trim() : basename(file, extname(file));

    console.log(`\n📄 ${file} (${docTitle}) → ${chunks.length} chunks`);

    const batch = [];
    for (const chunk of chunks) {
      process.stdout.write('.');
      const { content, context } = chunk;

      // Enriquecer el contenido almacenado con contexto explícito para módulos
      const enrichedContent = enrichContent(context, content);
      // Preamble mejora retrieval semántico (solo para embed, no almacenado)
      const preamble = buildPreamble(context, content);
      // mxbai-embed-large: límite 512 tokens ≈ 1400 chars seguros
      const textToEmbed = (preamble + enrichedContent).slice(0, 1400);
      const vector = await embed(textToEmbed);
      batch.push({
        id: idCounter++,
        vector,
        payload: {
          content: enrichedContent, // almacenar versión enriquecida
          context,
          source: file,
          metadata: {}
        }
      });

      // insertar en batches de 20
      if (batch.length >= 20) {
        await upsertBatch([...batch]);
        totalPoints += batch.length;
        batch.length = 0;
      }
    }

    if (batch.length > 0) {
      await upsertBatch([...batch]);
      totalPoints += batch.length;
    }
    console.log(` ✓`);
  }

  console.log(`\n✅ Ingesta completada: ${totalPoints} puntos en colección '${COLLECTION}'`);
}

main().catch(err => { console.error('ERROR:', err); process.exit(1); });

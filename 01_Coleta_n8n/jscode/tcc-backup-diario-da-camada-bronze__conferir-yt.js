// ============================================================================
// GERADO AUTOMATICAMENTE — NÃO EDITE ESTE ARQUIVO.
//
// Workflow : TCC — Backup diário da camada bronze
// Nó       : Conferir yt
// ID n8n   : pliN9f1zwIhClN2M
// Origem   : 01_Coleta_n8n/workflows/pliN9f1zwIhClN2M__TCC_Backup_di_rio_da_camada_bronze.json
// Gerado em: 2026-09-09 por extrair_jscode.py
//
// Este arquivo é uma CÓPIA LEGÍVEL, para leitura, diff e citação na monografia.
// A fonte da verdade é o n8n; o backup .json é o espelho dele.
// Para mudar o coletor: n8n (rascunho -> teste manual -> publicar) -> reexportar
// o .json -> rodar `python 01_Coleta_n8n/extrair_jscode.py` de novo.
// ============================================================================

const origem = $('yt').all();
const enviado = $input.first().json;
const linhas = origem.length;
if (linhas === 0) { throw new Error('tcc_bronze_youtube: leitura vazia - nada exportado, nada a apagar'); }
if (!enviado || !enviado.id) { throw new Error('tcc_bronze_youtube: o upload nao devolveu id de arquivo'); }
const bytes = Number(enviado.size || 0);
if (bytes < linhas * 40) { throw new Error('tcc_bronze_youtube: CSV pequeno demais para ' + linhas + ' linhas (' + bytes + ' bytes) - possivel truncamento'); }
const ids = origem.map(i => Number(i.json.id)).filter(n => !isNaN(n));
if (ids.length !== linhas) { throw new Error('tcc_bronze_youtube: ha linha sem id numerico - corte inseguro'); }
const ultimo = origem.map(i => String(i.json.coletado_em || '')).reduce((a, b) => (b > a ? b : a), '');
if (!ultimo) { throw new Error('tcc_bronze_youtube: sem coletado_em - corte inseguro'); }
const antigos = origem.filter(i => String(i.json.coletado_em || '') < ultimo).map(i => Number(i.json.id));
const idCorte = antigos.reduce((a, b) => (b > a ? b : a), 0);
return [{ json: { tabela: 'tcc_bronze_youtube', linhas: linhas, id_corte: idCorte, a_purgar: antigos.length, preservadas: linhas - antigos.length, ultimo_snapshot: ultimo, arquivo: enviado.name, arquivo_id: enviado.id, bytes: bytes, sha256: enviado.sha256Checksum || null, exportado_em: new Date().toISOString() } }];

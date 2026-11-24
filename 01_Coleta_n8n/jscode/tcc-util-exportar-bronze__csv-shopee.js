// ============================================================================
// GERADO AUTOMATICAMENTE — NÃO EDITE ESTE ARQUIVO.
//
// Workflow : TCC — [util] Exportar Bronze
// Nó       : CSV Shopee
// ID n8n   : 6dAtB1xEFBjL0wRp
// Origem   : 01_Coleta_n8n/workflows/6dAtB1xEFBjL0wRp__TCC_util_Exportar_Bronze.json
// Gerado em: 2026-09-09 por extrair_jscode.py
//
// Este arquivo é uma CÓPIA LEGÍVEL, para leitura, diff e citação na monografia.
// A fonte da verdade é o n8n; o backup .json é o espelho dele.
// Para mudar o coletor: n8n (rascunho -> teste manual -> publicar) -> reexportar
// o .json -> rodar `python 01_Coleta_n8n/extrair_jscode.py` de novo.
// ============================================================================

const NL = String.fromCharCode(10);
const cols = ['item_id','product_name','price','price_discount_rate','sales','rating_star','commission_rate','shop_name','offer_link','image_url','page','sort_type','coletado_em'];
function esc(v){ if (v === null || v === undefined) return ''; var s = String(v); if (s.indexOf(',') !== -1 || s.indexOf('"') !== -1 || s.indexOf(NL) !== -1) { return '"' + s.split('"').join('""') + '"'; } return s; }
const items = $input.all();
const linhas = [cols.join(',')];
for (const item of items) { const row = item.json; linhas.push(cols.map(function(c){ return esc(row[c]); }).join(',')); }
const csv = linhas.join(NL);
const hoje = $now.toFormat('yyyy-LL-dd');
return [{ json: { tabela: 'tcc_bronze_shopee', arquivo: 'tcc_bronze_shopee_' + hoje + '.csv', linhas: items.length, csv: csv } }];

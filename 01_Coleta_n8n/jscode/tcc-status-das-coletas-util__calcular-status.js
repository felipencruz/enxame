// ============================================================================
// GERADO AUTOMATICAMENTE — NÃO EDITE ESTE ARQUIVO.
//
// Workflow : TCC — Status das Coletas (util)
// Nó       : Calcular Status
// ID n8n   : jWlx7EmKfJKW0Ou1
// Origem   : 01_Coleta_n8n/workflows/jWlx7EmKfJKW0Ou1__TCC_Status_das_Coletas_util.json
// Gerado em: 2026-09-09 por extrair_jscode.py
//
// Este arquivo é uma CÓPIA LEGÍVEL, para leitura, diff e citação na monografia.
// A fonte da verdade é o n8n; o backup .json é o espelho dele.
// Para mudar o coletor: n8n (rascunho -> teste manual -> publicar) -> reexportar
// o .json -> rodar `python 01_Coleta_n8n/extrair_jscode.py` de novo.
// ============================================================================

// Painel de saude do Bronze: le as 5 tabelas de coleta + tcc_seeds e resume.
// So leitura, nao grava nada. Cobre ML e Amazon desde 15/07/2026; com 3 tabelas,
// o painel indicaria "tudo saudavel" ignorando 2 das 5 fontes.
function agg(rows, dateField) {
  const total = rows.length;
  const stamps = rows.map(r => r[dateField]).filter(Boolean).sort();
  const dias = {};
  const snapshots = new Set();
  for (const s of stamps) {
    const d = String(s).slice(0, 10);
    dias[d] = (dias[d] || 0) + 1;
    snapshots.add(String(s));
  }
  return {
    total_linhas: total,
    snapshots_distintos: snapshots.size,
    primeira_coleta: stamps[0] || null,
    ultima_coleta: stamps[stamps.length - 1] || null,
    linhas_por_dia: dias
  };
}
const sug = $('Ler Bronze Suggest').all().map(i => i.json);
const yt = $('Ler Bronze YouTube').all().map(i => i.json);
const shp = $('Ler Bronze Shopee').all().map(i => i.json);
const ml = $('Ler Bronze ML').all().map(i => i.json);
const amz = $('Ler Bronze Amazon').all().map(i => i.json);
const seeds = $('Ler Seeds').all().map(i => i.json);

const suggest = agg(sug, 'coletado_em');
suggest.linhas_erro = sug.filter(r => r.fonte === 'google_suggest_erro').length;
suggest.termos_distintos = new Set(sug.map(r => r.termo_semente)).size;
suggest.sugestoes_distintas = new Set(sug.map(r => r.sugestao)).size;

const youtube = agg(yt, 'coletado_em');
youtube.termos_distintos = new Set(yt.map(r => r.termo_semente)).size;
youtube.videos_distintos = new Set(yt.map(r => r.video_id)).size;

const shopee = agg(shp, 'coletado_em');
shopee.itens_distintos = new Set(shp.map(r => r.item_id)).size;

const mercadolivre = agg(ml, 'coletado_em');
mercadolivre.itens_distintos = new Set(ml.map(r => r.item_id)).size;
mercadolivre.sem_titulo = ml.filter(r => !r.titulo).length;
mercadolivre.sem_preco = ml.filter(r => !r.preco).length;

const amazon = agg(amz, 'coletado_em');
amazon.itens_distintos = new Set(amz.map(r => r.item_id)).size;
amazon.categorias_distintas = new Set(amz.map(r => r.categoria_pagina).filter(Boolean)).size;
amazon.sem_titulo = amz.filter(r => !r.titulo).length;
amazon.sem_avaliacao = amz.filter(r => !r.avaliacao).length;
// A Amazon nao tem coluna de preco de proposito: a fonte sonega preco a quem se
// identifica como robo, e o projeto optou por manter a identidade EnxameBot.

const seedsInfo = {
  total: seeds.length,
  ativos: seeds.filter(r => r.ativo === true).length,
  com_youtube: seeds.filter(r => r.coletar_youtube === true).length
};

return [{ json: { gerado_em: new Date().toISOString(), suggest, youtube, shopee, mercadolivre, amazon, seeds: seedsInfo } }];

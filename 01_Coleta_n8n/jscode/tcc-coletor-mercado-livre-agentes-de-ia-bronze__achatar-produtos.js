// ============================================================================
// GERADO AUTOMATICAMENTE — NÃO EDITE ESTE ARQUIVO.
//
// Workflow : TCC — Coletor Mercado Livre (agentes de IA, Bronze)
// Nó       : Achatar Produtos
// ID n8n   : 5vSP1WtLKpTTVBn6
// Origem   : 01_Coleta_n8n/workflows/5vSP1WtLKpTTVBn6__TCC_Coletor_Mercado_Livre_agentes_de_IA_Bronze.json
// Gerado em: 2026-09-09 por extrair_jscode.py
//
// Este arquivo é uma CÓPIA LEGÍVEL, para leitura, diff e citação na monografia.
// A fonte da verdade é o n8n; o backup .json é o espelho dele.
// Para mudar o coletor: n8n (rascunho -> teste manual -> publicar) -> reexportar
// o .json -> rodar `python 01_Coleta_n8n/extrair_jscode.py` de novo.
// ============================================================================

// Bronze = dado cru: precos entram como texto ("R$ 400"); a Silver faz o parse.
// Normalizacao minima: extrair o codigo MLB do link (o id do item).
// categoria_pagina vem da receita v2 (15/07/2026), que tem o mecanismo de grupo:
// a pagina tem 10 carrosseis por categoria e o titulo da vitrine fica acima do
// produto, fora do alcance de um seletor relativo ao item. Na receita v1 o campo era null.
const resp = $input.first().json;
const linhas = resp.linhas || [];
const agora = new Date().toISOString();
return linhas.map(n => {
  const link = n.link || '';
  const m = link.match(/MLB-?\d+/i);
  return { json: {
    item_id: m ? m[0].replace('-', '') : null,
    titulo: n.titulo || null,
    preco: n.preco || null,
    preco_antigo: n.preco_antigo || null,
    desconto: n.desconto || null,
    link: link || null,
    categoria_pagina: n.categoria || null,
    coletado_em: agora
  }};
});

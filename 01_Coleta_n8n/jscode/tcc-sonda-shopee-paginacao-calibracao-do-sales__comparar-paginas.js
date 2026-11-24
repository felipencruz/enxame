// ============================================================================
// GERADO AUTOMATICAMENTE — NÃO EDITE ESTE ARQUIVO.
//
// Workflow : TCC — [sonda] Shopee: paginacao + calibracao do sales
// Nó       : Comparar Paginas
// ID n8n   : XSdNQEaPSPw6qRQq
// Origem   : 01_Coleta_n8n/workflows/XSdNQEaPSPw6qRQq__TCC_sonda_Shopee_paginacao_calibracao_do_sales.json
// Gerado em: 2026-09-09 por extrair_jscode.py
//
// Este arquivo é uma CÓPIA LEGÍVEL, para leitura, diff e citação na monografia.
// A fonte da verdade é o n8n; o backup .json é o espelho dele.
// Para mudar o coletor: n8n (rascunho -> teste manual -> publicar) -> reexportar
// o .json -> rodar `python 01_Coleta_n8n/extrair_jscode.py` de novo.
// ============================================================================

const respostas = $input.all().map(i => i.json);
const pedidos = $('Assinar 2 Paginas').all().map(i => i.json);

const erros = [];
const paginas = {};
for (let i = 0; i < respostas.length; i++) {
  const r = respostas[i];
  const pedida = pedidos[i] ? pedidos[i].page_pedida : ('?' + i);
  if (r && r.errors) { erros.push({ page_pedida: pedida, errors: r.errors }); continue; }
  const d = (r && r.data && r.data.productOfferV2) ? r.data.productOfferV2 : null;
  if (!d) { erros.push({ page_pedida: pedida, resposta_crua: JSON.stringify(r).slice(0, 400) }); continue; }
  paginas[pedida] = {
    page_ecoada_pela_api: d.pageInfo ? d.pageInfo.page : null,
    hasNextPage: d.pageInfo ? d.pageInfo.hasNextPage : null,
    nodes: (d.nodes || []).map(n => ({
      item_id: String(n.itemId),
      titulo: String(n.productName || '').slice(0, 60),
      sales: n.sales,
      shop_id: n.shopId,
      product_link: n.productLink,
      offer_link: n.offerLink
    }))
  };
}

const chaves = Object.keys(paginas);
let veredito = 'INDETERMINADO (ver erros_graphql)';
let comparacao = null;
if (chaves.length === 2) {
  const a = paginas[chaves[0]].nodes.map(n => n.item_id);
  const b = paginas[chaves[1]].nodes.map(n => n.item_id);
  const setB = {};
  for (const id of b) { setB[id] = true; }
  const setA = {};
  for (const id of a) { setA[id] = true; }
  const intersecao = a.filter(id => setB[id]);
  const soEmA = a.filter(id => !setB[id]);
  const soEmB = b.filter(id => !setA[id]);
  const iguais = (soEmA.length === 0 && soEmB.length === 0 && a.length === b.length);
  veredito = iguais
    ? 'A API NAO PAGINA — e mente que pagina. page=1 e page=2 devolvem os MESMOS itens, e a API ecoa pageInfo.page e afirma hasNextPage=true. NAO E BUG NOSSO: o coletor assina e envia o parametro corretamente; a API aceita, confirma e ignora. Efeito: 250 linhas/rodada = 50 produtos x5 -> 80% do Bronze da Shopee e redundante (a Silver deduplica por item_id + coletado_em). CONSEQUENCIA PARA A DOC: o feed NAO tem 67 produtos (Guia 7) — e uma JANELA ROTATIVA DE 50, com ~300 distintos por semana. A limitacao da fonte e OUTRA e e melhor: 50 por consulta e o TETO OBSERVAVEL, e nao da para saber se o feed e mais fundo.'
    : 'A PAGINACAO FUNCIONA (ao menos em parte): page=2 traz itens que page=1 nao tem. Entao a rasez do Bronze (~50 distintos/snapshot) tem OUTRA causa — investigar antes de escrever qualquer coisa.';
  comparacao = {
    itens_na_page_1: a.length,
    itens_na_page_2: b.length,
    em_AMBAS: intersecao.length,
    so_na_page_1: soEmA.length,
    so_na_page_2: soEmB.length,
    SAO_IDENTICAS: iguais,
    primeiros_5_da_page_1: a.slice(0, 5),
    primeiros_5_da_page_2: b.slice(0, 5)
  };
}

const amostra = [];
if (chaves.length > 0) {
  for (const n of paginas[chaves[0]].nodes.slice(0, 8)) {
    amostra.push({
      item_id: n.item_id,
      titulo: n.titulo,
      sales_da_API: n.sales,
      product_link: n.product_link,
      offer_link_NAO_USAR: String(n.offer_link || '').slice(0, 60) + ' ...'
    });
  }
}

return [{ json: {
  gerado_em: new Date().toISOString(),
  ATENCAO: 'Sonda READ-ONLY. Nao grava no Bronze. Nao mexe no coletor de producao.',
  PERGUNTA_1_paginacao: veredito,
  comparacao_page1_vs_page2: comparacao,
  PERGUNTA_2_calibracao: 'RESPONDIDA EM 16/07, E A RESPOSTA FOI NAO DA. A amostra abaixo traz o product_link (URL ORIGINAL, sem utm — o offer_link nao serve, o robots proibe utm_medium=affiliates). O Agente 1 LIBEROU a rota /product/... (crawl_delay 1.0) e BLOQUEOU /top_products e /daily_discover/. Mas a pagina NAO TEM O DADO: 176.674 bytes, ZERO ocorrencias de vendido, sem <title> -> SPA pura, o contador so existe depois do JavaScript. E a imagem de producao nao tem Chromium/Playwright (removidos 15/07, -136 MB). DECISAO (16/07): nao forcar. O sales vira volume de vendas numa janela temporal NAO DOCUMENTADA pela fonte, e isso e LIMITACAO DECLARADA. A H1 nao precisa da janela: basta o sales ser monotonico na velocidade.',
  ACHADO_DE_BRINDE_user_agent: 'Medido na mesma pagina em 16/07: EnxameBot recebe 176.674 bytes e Chrome 155.353 — o cracha HONESTO recebe MAIS. E Googlebot leva HTTP 403: a Shopee BARRA quem finge ser o Google e SERVE quem diz a verdade. Frase para a banca: nao e so que mentir seja errado; nesta fonte, mentir nao funciona.',
  amostra_para_calibracao: amostra,
  campos_novos_que_esta_sonda_pediu: 'shopId e productLink — o coletor de producao NAO os pede (so itemId, productName, price, priceDiscountRate, sales, ratingStar, commissionRate, imageUrl, shopName, offerLink).',
  erros_graphql: erros,
  paginas_cruas: paginas
} }];

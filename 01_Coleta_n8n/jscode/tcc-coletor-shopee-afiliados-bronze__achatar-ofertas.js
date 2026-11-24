// ============================================================================
// GERADO AUTOMATICAMENTE — NÃO EDITE ESTE ARQUIVO.
//
// Workflow : TCC — Coletor Shopee Afiliados (Bronze)
// Nó       : Achatar Ofertas
// ID n8n   : qxMqqUOVFCCWvQ1i
// Origem   : 01_Coleta_n8n/workflows/qxMqqUOVFCCWvQ1i__TCC_Coletor_Shopee_Afiliados_Bronze.json
// Gerado em: 2026-09-09 por extrair_jscode.py
//
// Este arquivo é uma CÓPIA LEGÍVEL, para leitura, diff e citação na monografia.
// A fonte da verdade é o n8n; o backup .json é o espelho dele.
// Para mudar o coletor: n8n (rascunho -> teste manual -> publicar) -> reexportar
// o .json -> rodar `python 01_Coleta_n8n/extrair_jscode.py` de novo.
// ============================================================================

const items = $input.all();
const rows = [];
const agora = new Date().toISOString();
for (const it of items) {
  const d = (it.json && it.json.data && it.json.data.productOfferV2) ? it.json.data.productOfferV2 : null;
  if (!d) continue;
  const page = d.pageInfo ? d.pageInfo.page : null;
  const nodes = d.nodes || [];
  for (const n of nodes) {
    rows.push({ json: {
      item_id: String(n.itemId),
      product_name: n.productName,
      price: parseFloat(n.price),
      price_discount_rate: Number(n.priceDiscountRate),
      sales: Number(n.sales),
      rating_star: parseFloat(n.ratingStar),
      commission_rate: parseFloat(n.commissionRate),
      shop_name: n.shopName,
      offer_link: n.offerLink,
      image_url: n.imageUrl,
      page: Number(page),
      sort_type: 2,
      coletado_em: agora
    }});
  }
}
return rows;

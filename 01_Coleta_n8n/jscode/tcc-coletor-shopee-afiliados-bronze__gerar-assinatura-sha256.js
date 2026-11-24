// ============================================================================
// GERADO AUTOMATICAMENTE — NÃO EDITE ESTE ARQUIVO.
//
// Workflow : TCC — Coletor Shopee Afiliados (Bronze)
// Nó       : Gerar Assinatura SHA256
// ID n8n   : qxMqqUOVFCCWvQ1i
// Origem   : 01_Coleta_n8n/workflows/qxMqqUOVFCCWvQ1i__TCC_Coletor_Shopee_Afiliados_Bronze.json
// Gerado em: 2026-09-09 por extrair_jscode.py
//
// Este arquivo é uma CÓPIA LEGÍVEL, para leitura, diff e citação na monografia.
// A fonte da verdade é o n8n; o backup .json é o espelho dele.
// Para mudar o coletor: n8n (rascunho -> teste manual -> publicar) -> reexportar
// o .json -> rodar `python 01_Coleta_n8n/extrair_jscode.py` de novo.
// ============================================================================

const appId = '<APP_ID_DA_AFILIADA>';
const secret = $env.SHOPEE_APP_SECRET;
if (!secret) { throw new Error('SHOPEE_APP_SECRET não definido no ambiente do n8n'); }
const crypto = require('crypto');
const timestamp = Math.floor(Date.now() / 1000);
return [1, 2, 3, 4, 5].map(page => {
  const query = `{ productOfferV2(sortType: 2, limit: 50, page: ${page}) { nodes { itemId productName price priceDiscountRate sales ratingStar commissionRate imageUrl shopName offerLink } pageInfo { page hasNextPage } } }`;
  const payload = JSON.stringify({ query });
  const fator = appId + timestamp + payload + secret;
  const signature = crypto.createHash('sha256').update(fator).digest('hex');
  const authHeader = `SHA256 Credential=${appId}, Timestamp=${timestamp}, Signature=${signature}`;
  return { json: { authHeader, payload, timestamp, page } };
});

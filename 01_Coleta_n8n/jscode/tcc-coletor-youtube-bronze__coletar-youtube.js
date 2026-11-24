// ============================================================================
// GERADO AUTOMATICAMENTE — NÃO EDITE ESTE ARQUIVO.
//
// Workflow : TCC — Coletor YouTube (Bronze)
// Nó       : Coletar YouTube
// ID n8n   : WBFUddBm00zBSqIT
// Origem   : 01_Coleta_n8n/workflows/WBFUddBm00zBSqIT__TCC_Coletor_YouTube_Bronze.json
// Gerado em: 2026-09-09 por extrair_jscode.py
//
// Este arquivo é uma CÓPIA LEGÍVEL, para leitura, diff e citação na monografia.
// A fonte da verdade é o n8n; o backup .json é o espelho dele.
// Para mudar o coletor: n8n (rascunho -> teste manual -> publicar) -> reexportar
// o .json -> rodar `python 01_Coleta_n8n/extrair_jscode.py` de novo.
// ============================================================================

const seeds = $input.all().map(i => i.json.termo).filter(Boolean);
const YT_KEY = $env.YOUTUBE_API_KEY;
const rows = [];
const agora = new Date().toISOString();
for (const termo of seeds) {
  try {
    const url = 'https://www.googleapis.com/youtube/v3/search?part=snippet&type=video&maxResults=10&order=relevance&relevanceLanguage=pt&regionCode=BR&q=' + encodeURIComponent(termo) + '&key=' + YT_KEY;
    const resp = await this.helpers.httpRequest({ method: 'GET', url, json: true });
    const total = (resp && resp.pageInfo && typeof resp.pageInfo.totalResults === 'number') ? resp.pageInfo.totalResults : null;
    const items = (resp && Array.isArray(resp.items)) ? resp.items : [];
    for (const it of items) {
      const sn = it.snippet || {};
      rows.push({ json: {
        termo_semente: termo,
        video_id: it.id ? it.id.videoId : null,
        titulo: sn.title || null,
        canal: sn.channelTitle || null,
        published_at: sn.publishedAt || null,
        total_results: total,
        coletado_em: agora
      }});
    }
  } catch (e) {
    rows.push({ json: { termo_semente: termo, video_id: null, titulo: '[ERRO] ' + (e.message || e), canal: null, published_at: null, total_results: null, coletado_em: agora } });
  }
  await new Promise(r => setTimeout(r, 200));
}
return rows;

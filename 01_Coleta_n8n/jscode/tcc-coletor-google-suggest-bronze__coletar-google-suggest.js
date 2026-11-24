// ============================================================================
// GERADO AUTOMATICAMENTE — NÃO EDITE ESTE ARQUIVO.
//
// Workflow : TCC — Coletor Google Suggest (Bronze)
// Nó       : Coletar Google Suggest
// ID n8n   : PV5UweukBccsizsm
// Origem   : 01_Coleta_n8n/workflows/PV5UweukBccsizsm__TCC_Coletor_Google_Suggest_Bronze.json
// Gerado em: 2026-09-09 por extrair_jscode.py
//
// Este arquivo é uma CÓPIA LEGÍVEL, para leitura, diff e citação na monografia.
// A fonte da verdade é o n8n; o backup .json é o espelho dele.
// Para mudar o coletor: n8n (rascunho -> teste manual -> publicar) -> reexportar
// o .json -> rodar `python 01_Coleta_n8n/extrair_jscode.py` de novo.
// ============================================================================

// Identidade declarada: o mesmo cracha do enxame-api (nome, versao e contato).
// Desde 15/07/2026 este coletor se identifica, como os outros quatro, em coerencia
// com o capitulo de etica, que promete auto-identificacao. Teste previo: o Google
// devolve sugestoes identicas com e sem o UA (ao contrario da Amazon, que sonega dado a robo).
const UA = 'EnxameBot/0.1 (+https://automatize-ai.tech)';
const seeds = $input.all().map(i => i.json.termo).filter(Boolean);
const rows = [];
const agora = new Date().toISOString();
for (const termo of seeds) {
  try {
    const url = 'https://suggestqueries.google.com/complete/search?client=firefox&hl=pt-BR&oe=utf-8&ie=utf-8&q=' + encodeURIComponent(termo);
    const raw = await this.helpers.httpRequest({ method: 'GET', url, headers: { 'User-Agent': UA } });
    const arr = typeof raw === 'string' ? JSON.parse(raw) : raw;
    const sugestoes = Array.isArray(arr) && Array.isArray(arr[1]) ? arr[1] : [];
    sugestoes.forEach((s, i) => {
      rows.push({ json: { termo_semente: termo, sugestao: s, posicao: i + 1, fonte: 'google_suggest', idioma: 'pt-BR', coletado_em: agora } });
    });
  } catch (e) {
    rows.push({ json: { termo_semente: termo, sugestao: '[ERRO] ' + e.message, posicao: 0, fonte: 'google_suggest_erro', idioma: 'pt-BR', coletado_em: agora } });
  }
  await new Promise(r => setTimeout(r, 150));  // pausa entre requisicoes (politeness): nao sobrecarregar a fonte
}
return rows;

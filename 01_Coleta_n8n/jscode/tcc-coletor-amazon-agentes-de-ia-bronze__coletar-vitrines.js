// ============================================================================
// GERADO AUTOMATICAMENTE — NÃO EDITE ESTE ARQUIVO.
//
// Workflow : TCC — Coletor Amazon (agentes de IA, Bronze)
// Nó       : Coletar Vitrines
// ID n8n   : UN8KNwlEsoLKm1kw
// Origem   : 01_Coleta_n8n/workflows/UN8KNwlEsoLKm1kw__TCC_Coletor_Amazon_agentes_de_IA_Bronze.json
// Gerado em: 2026-09-09 por extrair_jscode.py
//
// Este arquivo é uma CÓPIA LEGÍVEL, para leitura, diff e citação na monografia.
// A fonte da verdade é o n8n; o backup .json é o espelho dele.
// Para mudar o coletor: n8n (rascunho -> teste manual -> publicar) -> reexportar
// o .json -> rodar `python 01_Coleta_n8n/extrair_jscode.py` de novo.
// ============================================================================

// Percorre as 22 vitrines em escopo (tcc_amazon_vitrines) chamando o enxame-api
// para cada uma. Substituiu a pagina geral em 16/07/2026: ela rotacionava as vitrines
// (6 por rodada de um pool de 9, incluindo 3 fora do escopo da Parte A) e nao entregava
// preco ao EnxameBot. A rota por departamento entrega 50 itens com preco e com rank
// continuo #1..#50, medido em 3 replicas e testado em 8 vitrines antes da troca.
//
// A categoria nao vem da pagina: vem da tabela governada. Na pagina de departamento
// a categoria e a propria pagina, entao ler da tabela e mais confiavel que raspar.
//
// Ate 3 tentativas por vitrine, desde 08/09/2026, dentro deste no (sem tabela auxiliar).
//
// Motivo: a Amazon e fonte de melhor esforco e recusa com 503 por vitrine, naquele
// segundo. Com uma tentativa so, o que ela recusasse estava perdido: o Bronze e
// insert-only, e a rodada seguinte so vem 12h depois. Em 05-07/09/2026 isso custou
// 33 de 132 pares (vitrine, rodada) = 25%, e em 08/09/2026 a serie teve o pior caso:
// 12 das 22 vitrines numa rodada so.
// O efeito da repeticao foi medido: em 08/09/2026, das 9 vitrines que tinham falhado
// sondadas de novo, 7 voltaram 50/50 de primeira; as 2 que recusaram de novo
// voltaram 50/50 na segunda chamada, tres minutos depois. 9 de 9.
//
// Organizacao das passadas, e o motivo de cada escolha:
// - a 2a e a 3a passada percorrem so as vitrines que falharam, no fim da fila, nunca
//   logo depois da propria falha: quando a rodada chega ao fim ja se passaram minutos,
//   que e a ordem de grandeza em que a fonte voltou na sonda;
// - a pausa entre vitrines sobe de 3s para 5s nas passadas de retry: com uma fonte
//   que esta recusando, insistir mais devagar e o comportamento correto;
// - 60s entre passadas.
// O custo foi medido antes da implementacao: a rodada leva 80-89s (22 vitrines),
// e o pior caso absoluto (as 22 recusando tres vezes) fica em ~8 min, contra
// N8N_RUNNERS_TASK_TIMEOUT=1800 do runner. A folga e de 4x.
//
// So vira linha de erro a vitrine que a fonte recusou nas tres tentativas. Se a
// vitrine recusa e depois entrega, ela nao se perdeu, e gravar erro faria o
// "Alerta de Perda Silenciosa" (srxlA0ItOoj0BCGX) avisar sobre dado que esta la.
// O invariante de que o alerta e a Silver dependem se mantem: linha de erro
// tem item_id nulo e titulo comecando com "[ERRO]".
//
// O titulo declara quantas tentativas houve: "[ERRO] (3 tentativas)".
// Sem isso a serie ficaria incomparavel sem aviso: linha anterior a 08/09/2026 mede
// uma tentativa, linha posterior mede tres, e a taxa de 503 deixa de significar a
// mesma coisa. Com a marca, o proprio dado diz qual regime o produziu.
//
// Um unico coletado_em para a rodada inteira, inclusive nas linhas recuperadas na
// 3a passada. A purga diaria guarda "o snapshot mais recente" e o alerta agrupa
// rodada por esse campo: recarimbar no meio partiria a rodada em dois snapshots.
//
// Teste deterministico dos quatro ramos (inclusive "recusa e recupera", que nenhuma
// execucao real produz sob comando): 01_Coleta_n8n/teste_retry_amazon.mjs.
const vitrines = $input.all().map(i => i.json);
const agora = new Date().toISOString();
const BASE = "https://www.amazon.com.br";
const MAX_TENTATIVAS = 3;
const PAUSA_VITRINE_MS = 3000;
const PAUSA_VITRINE_RETRY_MS = 5000;
const PAUSA_PASSADA_MS = 60000;

const linhas = [];
const motivos = {};
let pendentes = vitrines;

for (let tentativa = 1; tentativa <= MAX_TENTATIVAS; tentativa++) {
  if (pendentes.length === 0) { break; }
  if (tentativa > 1) { await new Promise(r => setTimeout(r, PAUSA_PASSADA_MS)); }
  const pausa = tentativa === 1 ? PAUSA_VITRINE_MS : PAUSA_VITRINE_RETRY_MS;
  const falharam = [];
  for (const v of pendentes) {
    try {
      const resp = await this.helpers.httpRequest({
        method: "POST",
        url: "http://enxame-api:8000/agentes/coletar",
        body: { url: v.url },
        json: true,
        timeout: 120000,
      });
      // Acumula em lista propria e so anexa quando a vitrine fecha inteira: se a
      // chamada falhasse depois de ja ter produzido linhas, o retry duplicaria.
      const daVitrine = [];
      for (const n of (resp.linhas || [])) {
        const rel = n.link || "";
        const link = rel.startsWith("http") ? rel : (rel ? BASE + rel : null);
        const m = rel.match(/\/dp\/([A-Z0-9]{10})/i);
        daVitrine.push({ json: {
          item_id: m ? m[1] : null,
          titulo: n.titulo || null,
          preco: n.preco || null,
          categoria_pagina: v.rotulo_amazon,
          rank: n.rank || null,
          avaliacao: n.avaliacao || null,
          link: link,
          coletado_em: agora,
        }});
      }
      for (const l of daVitrine) { linhas.push(l); }
    } catch (e) {
      const detalhe = (e.message || String(e)).slice(0, 180);
      if (!motivos[v.rotulo_amazon]) { motivos[v.rotulo_amazon] = []; }
      motivos[v.rotulo_amazon].push(detalhe);
      falharam.push(v);
    }
    await new Promise(r => setTimeout(r, pausa));
  }
  pendentes = falharam;
}

// Vitrine que a fonte recusou nas tres tentativas: linha de erro auditavel, no
// padrao dos outros coletores. Falha silenciosa nao existe aqui.
for (const v of pendentes) {
  const ds = motivos[v.rotulo_amazon] || [];
  let motivo = "sem detalhe";
  if (ds.length > 0) {
    let iguais = true;
    for (const d of ds) { if (d !== ds[0]) { iguais = false; } }
    if (iguais) {
      motivo = ds[0];
    } else {
      // Motivos diferentes entre as tentativas: guarda os tres. Sem .join(), que o
      // runner bloqueia ("Security violation") nas duas camadas do SDK.
      motivo = "";
      for (const d of ds) { motivo = motivo ? motivo + " | " + d : d; }
      motivo = motivo.slice(0, 180);
    }
  }
  linhas.push({ json: {
    item_id: null,
    titulo: "[ERRO] (" + ds.length + " tentativas) " + motivo,
    preco: null,
    categoria_pagina: v.rotulo_amazon,
    rank: null,
    avaliacao: null,
    link: v.url,
    coletado_em: agora,
  }});
}
return linhas;

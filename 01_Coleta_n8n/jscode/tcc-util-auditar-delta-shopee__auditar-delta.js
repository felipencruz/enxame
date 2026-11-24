// ============================================================================
// GERADO AUTOMATICAMENTE — NÃO EDITE ESTE ARQUIVO.
//
// Workflow : TCC — [util] Auditar Delta Shopee
// Nó       : Auditar Delta
// ID n8n   : UUntUm2ErEuLKZVn
// Origem   : 01_Coleta_n8n/workflows/UUntUm2ErEuLKZVn__TCC_util_Auditar_Delta_Shopee.json
// Gerado em: 2026-09-09 por extrair_jscode.py
//
// Este arquivo é uma CÓPIA LEGÍVEL, para leitura, diff e citação na monografia.
// A fonte da verdade é o n8n; o backup .json é o espelho dele.
// Para mudar o coletor: n8n (rascunho -> teste manual -> publicar) -> reexportar
// o .json -> rodar `python 01_Coleta_n8n/extrair_jscode.py` de novo.
// ============================================================================

const linhas = $('Ler Bronze Shopee').all().map(i => i.json);

const porStamp = {};
for (const r of linhas) {
  const s = r.coletado_em;
  if (!s) continue;
  if (!porStamp[s]) porStamp[s] = [];
  porStamp[s].push(r);
}
const stamps = Object.keys(porStamp).sort();

const salesDe = {};
for (const s of stamps) {
  const m = {};
  for (const r of porStamp[s]) {
    const v = Number(r.sales);
    if (!Number.isFinite(v)) continue;
    if (m[r.item_id] === undefined || v > m[r.item_id]) { m[r.item_id] = v; }
  }
  salesDe[s] = m;
}

const obsPorItem = {};
for (const s of stamps) {
  for (const id of Object.keys(salesDe[s])) { obsPorItem[id] = (obsPorItem[id] || 0) + 1; }
}
const todosIds = Object.keys(obsPorItem);
const serieCompleta = todosIds.filter(id => obsPorItem[id] === stamps.length);

const balanco = { subiu: 0, igual: 0, caiu: 0 };
const casosQueCairam = [];
for (const id of todosIds) {
  if (obsPorItem[id] < 2) continue;
  const pts = [];
  for (const s of stamps) { if (salesDe[s][id] !== undefined) { pts.push(salesDe[s][id]); } }
  const d = pts[pts.length - 1] - pts[0];
  if (d > 0) { balanco.subiu++; }
  else if (d === 0) { balanco.igual++; }
  else {
    balanco.caiu++;
    if (casosQueCairam.length < 12) { casosQueCairam.push({ item_id: id, primeiro: pts[0], ultimo: pts[pts.length - 1], variacao_total: d, pontos_na_serie: pts.length }); }
  }
}

const trajetorias = serieCompleta.map(id => ({ item_id: id, serie_completa_28_pontos: stamps.map(s => salesDe[s][id]) }));

const pares = [];
const todosNegativos = [];
let totPos = 0; let totZero = 0; let totNeg = 0;
let totSumiram = 0; let totEntraram = 0;
for (let i = 1; i < stamps.length; i++) {
  const a = stamps[i - 1]; const b = stamps[i];
  const ma = salesDe[a]; const mb = salesDe[b];
  const horas = (new Date(b).getTime() - new Date(a).getTime()) / 3600000;
  let pos = 0; let zero = 0; let neg = 0; let somaPos = 0;
  const idsA = Object.keys(ma); const idsB = Object.keys(mb);
  for (const id of idsB) {
    if (ma[id] === undefined) continue;
    const d = mb[id] - ma[id];
    if (d > 0) { pos++; somaPos += d; }
    else if (d === 0) { zero++; }
    else { neg++; todosNegativos.push({ item_id: id, de: ma[id], para: mb[id], delta: d, snapshot: b }); }
  }
  const sumiram = idsA.filter(id => mb[id] === undefined);
  const entraram = idsB.filter(id => ma[id] === undefined);
  totSumiram += sumiram.length; totEntraram += entraram.length;
  totPos += pos; totZero += zero; totNeg += neg;
  pares.push({ de: a, para: b, horas_de_intervalo: Number(horas.toFixed(2)), itens_pareados: pos + zero + neg, delta_positivo: pos, delta_zero: zero, delta_negativo: neg, sumiram_do_top: sumiram.length, entraram_no_top: entraram.length });
}

const dupDentroSnapshot = [];
const porSnapshot = [];
for (const s of stamps) {
  const rs = porStamp[s];
  const cont = {};
  for (const r of rs) { cont[r.item_id] = (cont[r.item_id] || 0) + 1; }
  const ids = Object.keys(cont);
  const dups = ids.filter(id => cont[id] > 1);
  if (dups.length > 0) { dupDentroSnapshot.push({ snapshot: s, itens_repetidos: dups.length, exemplos: dups.slice(0, 3).map(id => ({ item_id: id, vezes: cont[id] })) }); }
  const paginas = {};
  for (const r of rs) { paginas['p' + r.page] = (paginas['p' + r.page] || 0) + 1; }
  porSnapshot.push({ snapshot: s, linhas: rs.length, itens_distintos: ids.length, por_pagina: paginas });
}

const totalPareados = totPos + totZero + totNeg;
const pct = (n) => (totalPareados > 0 ? Number((100 * n / totalPareados).toFixed(2)) : 0);

return [{ json: {
  gerado_em: new Date().toISOString(),
  ATENCAO: 'Util READ-ONLY. Nao grava nada.',
  PERGUNTA: 'O sales e ACUMULADO (total historico) ou JANELA MOVEL? A doc oficial da Shopee NAO define o campo (conferido 16/07). Entao o dado decide.',
  COMO_LER: 'Se acumulado: a serie de um item NUNCA cai, e TESTE_primeiro_vs_ultimo.caiu deve ser 0. Se janela movel: sobe e desce, e caiu fica perto de subiu. Medido em 16/07: 81 subiu / 80 igual / 76 CAIU -> NAO e acumulado.',
  snapshots: stamps.length,
  itens_distintos_no_periodo: todosIds.length,
  TESTE_primeiro_vs_ultimo_ponto: balanco,
  casos_que_terminaram_ABAIXO_de_onde_comecaram: casosQueCairam,
  trajetorias_dos_itens_presentes_em_TODOS_os_snapshots: trajetorias,
  REFRESH_1x_por_dia: { explicacao: 'So os pares 15:00->21:00 UTC tem movimento; nas outras transicoes o delta e zero em 100% dos itens. A coleta 6/6h remede o mesmo numero 4x.', por_par_de_snapshot: pares },
  DELTA_no_periodo_inteiro: { total_de_deltas_calculados: totalPareados, positivos: totPos, positivos_pct: pct(totPos), zeros: totZero, zeros_pct: pct(totZero), negativos: totNeg, negativos_pct: pct(totNeg) },
  NEGATIVOS_exemplos: todosNegativos.slice(0, 15),
  BURACOS: { sumiram_do_top_total: totSumiram, entraram_no_top_total: totEntraram },
  PAGINACAO_duplicata_dentro_do_snapshot: { explicacao: 'O coletor pede 5 paginas de 50; a API ecoa pageInfo.page 1..5 e devolve o MESMO conjunto -> 250 linhas, ~50 itens, cada um 5x. A Silver deduplica por (item_id, coletado_em). Sonda page=1 vs page=2 pendente.', casos: dupDentroSnapshot, por_snapshot: porSnapshot }
} }];

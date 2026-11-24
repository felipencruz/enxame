// ============================================================================
// GERADO AUTOMATICAMENTE — NÃO EDITE ESTE ARQUIVO.
//
// Workflow : TCC — [util] Auditar Sobreposicao Amazon
// Nó       : Auditar Sobreposicao
// ID n8n   : svkhNMVBampGIxLK
// Origem   : 01_Coleta_n8n/workflows/svkhNMVBampGIxLK__TCC_util_Auditar_Sobreposicao_Amazon.json
// Gerado em: 2026-09-09 por extrair_jscode.py
//
// Este arquivo é uma CÓPIA LEGÍVEL, para leitura, diff e citação na monografia.
// A fonte da verdade é o n8n; o backup .json é o espelho dele.
// Para mudar o coletor: n8n (rascunho -> teste manual -> publicar) -> reexportar
// o .json -> rodar `python 01_Coleta_n8n/extrair_jscode.py` de novo.
// ============================================================================

// Auditoria somente leitura da sobreposicao de departamentos da Amazon (16/07/2026).
// A troca da pagina geral pelas 22 vitrines por departamento fez aparecer o mesmo
// produto em mais de uma vitrine: os departamentos da Amazon se sobrepoem (o Echo
// Dot esta em Dispositivos Amazon e em Eletronicos). Na pagina geral isso nao
// ocorria. Nao e bug: e a natureza da fonte.
//
// Por que importa: o Score normaliza por categoria da Parte A, e as 22 vitrines
// colapsam em 14 categorias. 11 vitrines caem numa categoria compartilhada
// (4 em Eletronicos, 4 em Casa e jardim, 3 em Saude e beleza), entao o mesmo produto
// entraria 2x na mesma categoria, inflando a concorrencia (dim. C).
//
// As 3 perguntas que este util responde:
//  1. as duplicatas discordam entre si (problema de qualidade) ou sao o mesmo
//     produto em dois pools? -> campos_que_discordam
//  2. quem da o melhor rank, a vitrine estreita ou a ampla? -> desenha o desempate
//  3. alguma vitrine entregou menos que o esperado? -> vitrines_abaixo_do_esperado
//     (a regua de aceite mede proporcao, nao volume: uma vitrine com 1 item de 50
//     passa com 100% de preenchimento.)
//
// O Bronze guarda o dado cru de proposito; a deduplicacao e regra da Silver. Este
// util mede e mostra os casos concretos. So le. Nao grava nada.
const linhas = $('Ler Bronze Amazon').all().map(i => i.json);
const vitrines = $('Ler Vitrines').all().map(i => i.json);

const catDe = {};
const ativas = [];
for (const v of vitrines) {
  catDe[v.rotulo_amazon] = v.categoria_parte_a;
  if (v.ativo === true) { ativas.push(v.rotulo_amazon); }
}

// So a ultima rodada: cada rodada carimba um unico coletado_em.
const stamps = linhas.map(r => r.coletado_em).filter(Boolean).sort();
const ultimo = stamps[stamps.length - 1];
const daRodada = linhas.filter(r => r.coletado_em === ultimo);
const erros = daRodada.filter(r => String(r.titulo || '').startsWith('[ERRO]'));
const rodada = daRodada.filter(r => r.item_id && !String(r.titulo || '').startsWith('[ERRO]'));

// Volume por vitrine: a pagina de departamento entrega 50. Menos que isso e sinal.
const contagemVitrine = {};
for (const r of rodada) {
  contagemVitrine[r.categoria_pagina] = (contagemVitrine[r.categoria_pagina] || 0) + 1;
}
const abaixoDoEsperado = [];
for (const rot of ativas) {
  const n = contagemVitrine[rot] || 0;
  if (n < 50) { abaixoDoEsperado.push({ vitrine: rot, itens: n, esperado: 50, categoria_parte_a: catDe[rot] }); }
}

const porItem = {};
for (const r of rodada) {
  if (!porItem[r.item_id]) porItem[r.item_id] = [];
  porItem[r.item_id].push({
    vitrine: r.categoria_pagina,
    categoria_parte_a: catDe[r.categoria_pagina] || '(sem mapa)',
    rank: r.rank,
    preco: r.preco,
    avaliacao: r.avaliacao,
    titulo: String(r.titulo || '').slice(0, 70)
  });
}

const ids = Object.keys(porItem);
const multiVitrine = ids.filter(id => porItem[id].length > 1);

const colisaoMesmaCat = [];
const colisaoOutraCat = [];
for (const id of multiVitrine) {
  const cats = {};
  for (const o of porItem[id]) { cats[o.categoria_parte_a] = (cats[o.categoria_parte_a] || 0) + 1; }
  let dup = false;
  for (const k of Object.keys(cats)) { if (cats[k] > 1) dup = true; }
  if (dup) { colisaoMesmaCat.push(id); } else { colisaoOutraCat.push(id); }
}

// As linhas duplicadas concordam? Se preco/titulo/avaliacao batem, o desempate
// so decide qual rank sobrevive; o resto e a mesma medida repetida.
const discordam = { preco: 0, titulo: 0, avaliacao: 0, rank: 0 };
const casosDeDiscordancia = [];
for (const id of multiVitrine) {
  const oc = porItem[id];
  const campos = ['preco', 'titulo', 'avaliacao', 'rank'];
  for (const campo of campos) {
    const vals = new Set(oc.map(o => String(o[campo] === null || o[campo] === undefined ? '' : o[campo])));
    if (vals.size > 1) {
      discordam[campo]++;
      if (campo !== 'rank' && casosDeDiscordancia.length < 8) {
        casosDeDiscordancia.push({ item_id: id, campo: campo, valores: [...vals] });
      }
    }
  }
}

// Inflacao por categoria: linhas / itens distintos. 1.0 = sem duplicata.
const porCat = {};
for (const r of rodada) {
  const c = catDe[r.categoria_pagina] || '(sem mapa)';
  if (!porCat[c]) { porCat[c] = { linhas: 0, itens: new Set(), vitrines: new Set() }; }
  porCat[c].linhas++;
  porCat[c].itens.add(r.item_id);
  porCat[c].vitrines.add(r.categoria_pagina);
}
const resumoCat = {};
for (const c of Object.keys(porCat)) {
  resumoCat[c] = {
    vitrines: porCat[c].vitrines.size,
    linhas: porCat[c].linhas,
    itens_distintos: porCat[c].itens.size,
    inflacao: Number((porCat[c].linhas / porCat[c].itens.size).toFixed(3))
  };
}

const pares = {};
for (const id of multiVitrine) {
  const vs = porItem[id].map(o => o.vitrine).sort();
  for (let a = 0; a < vs.length; a++) {
    for (let b = a + 1; b < vs.length; b++) {
      const k = vs[a] + ' || ' + vs[b];
      pares[k] = (pares[k] || 0) + 1;
    }
  }
}

// O padrao que desenha a regra: nas colisoes, a vitrine estreita da rank melhor
// que a ampla? Se sim, "melhor rank vence" escolheria sistematicamente a medida
// mais lisonjeira (um #1 num pool pequeno nao vale um #1 num pool grande).
const quemDaOMelhorRank = {};
for (const id of colisaoMesmaCat) {
  const oc = porItem[id].slice().sort((a, b) =>
    Number(String(a.rank || '#999').replace('#', '')) - Number(String(b.rank || '#999').replace('#', '')));
  quemDaOMelhorRank[oc[0].vitrine] = (quemDaOMelhorRank[oc[0].vitrine] || 0) + 1;
}

// Efeito da regra de deduplicacao da Silver (definida em 16/07/2026):
// chave (item_id, categoria_parte_a); sobrevive o pior rank. Simulado, nao gravado.
const sobreviventes = {};
for (const r of rodada) {
  const c = catDe[r.categoria_pagina] || '(sem mapa)';
  const chave = r.item_id + '|' + c;
  const n = Number(String(r.rank || '#999').replace('#', ''));
  if (!sobreviventes[chave] || n > sobreviventes[chave].n) { sobreviventes[chave] = { n: n, vitrine: r.categoria_pagina }; }
}

const exemplos = colisaoMesmaCat.slice(0, 15).map(id => ({
  item_id: id,
  titulo: porItem[id][0].titulo,
  ocorrencias: porItem[id]
}));

return [{ json: {
  gerado_em: new Date().toISOString(),
  snapshot_auditado: ultimo,
  vitrines_ativas_esperadas: ativas.length,
  vitrines_que_entregaram: Object.keys(contagemVitrine).length,
  vitrines_abaixo_do_esperado: abaixoDoEsperado,
  linhas_de_erro_na_rodada: erros.length,
  linhas_na_rodada: rodada.length,
  itens_distintos: ids.length,
  itens_em_mais_de_uma_vitrine: multiVitrine.length,
  itens_duplicados_na_MESMA_categoria_parte_a: colisaoMesmaCat.length,
  itens_em_categorias_parte_a_DIFERENTES: colisaoOutraCat.length,
  campos_que_discordam_entre_as_duplicatas: discordam,
  casos_de_discordancia: casosDeDiscordancia,
  quem_da_o_melhor_rank_nas_colisoes: quemDaOMelhorRank,
  linhas_apos_a_regra_pior_rank_vence: Object.keys(sobreviventes).length,
  por_categoria_parte_a: resumoCat,
  pares_de_vitrine_que_colidem: pares,
  exemplos_para_desenhar_a_regra: exemplos
} }];

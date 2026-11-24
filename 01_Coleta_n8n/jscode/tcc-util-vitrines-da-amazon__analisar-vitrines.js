// ============================================================================
// GERADO AUTOMATICAMENTE — NÃO EDITE ESTE ARQUIVO.
//
// Workflow : TCC — [util] Vitrines da Amazon
// Nó       : Analisar Vitrines
// ID n8n   : jmH0IyQcgRN2z9in
// Origem   : 01_Coleta_n8n/workflows/jmH0IyQcgRN2z9in__TCC_util_Vitrines_da_Amazon.json
// Gerado em: 2026-09-09 por extrair_jscode.py
//
// Este arquivo é uma CÓPIA LEGÍVEL, para leitura, diff e citação na monografia.
// A fonte da verdade é o n8n; o backup .json é o espelho dele.
// Para mudar o coletor: n8n (rascunho -> teste manual -> publicar) -> reexportar
// o .json -> rodar `python 01_Coleta_n8n/extrair_jscode.py` de novo.
// ============================================================================

// Raio-X das vitrines da Amazon por rodada. Somente leitura.
// Perguntas que precisam de resposta antes da decisao: a Amazon tem um pool fixo de
// vitrines do qual sorteia 6, ou o pool tambem muda? O rank e comparavel entre
// rodadas se a vitrine nem sempre aparece?
const rows = $('Ler Bronze Amazon').all().map(i => i.json);

const porSnapshot = {};
for (const r of rows) {
  const s = String(r.coletado_em);
  porSnapshot[s] = porSnapshot[s] || {};
  const c = r.categoria_pagina || '(sem categoria)';
  porSnapshot[s][c] = (porSnapshot[s][c] || 0) + 1;
}

const snaps = Object.keys(porSnapshot).sort();
const todasCategorias = [...new Set(rows.map(r => r.categoria_pagina || '(sem categoria)'))].sort();

// Em quantas rodadas cada categoria apareceu (a "intermitencia" que ameaca a serie)
const presenca = {};
for (const c of todasCategorias) {
  presenca[c] = { rodadas: 0, de: snaps.length, produtos_por_rodada: [] };
  for (const s of snaps) {
    if (porSnapshot[s][c]) {
      presenca[c].rodadas += 1;
      presenca[c].produtos_por_rodada.push(porSnapshot[s][c]);
    }
  }
}

// O mesmo item_id reaparece em categorias diferentes? (isso quebraria o Score)
const catsPorItem = {};
for (const r of rows) {
  const k = r.item_id;
  catsPorItem[k] = catsPorItem[k] || new Set();
  catsPorItem[k].add(r.categoria_pagina || '(sem categoria)');
}
const itensEmMaisDeUmaCategoria = Object.entries(catsPorItem)
  .filter(([, set]) => set.size > 1)
  .map(([id, set]) => ({ item_id: id, categorias: [...set] }));

return [{ json: {
  gerado_em: new Date().toISOString(),
  total_linhas: rows.length,
  rodadas: snaps.length,
  categorias_distintas_no_total: todasCategorias.length,
  vitrines_por_rodada: snaps.map(s => ({
    quando: s,
    n_vitrines: Object.keys(porSnapshot[s]).length,
    n_produtos: Object.values(porSnapshot[s]).reduce((a, b) => a + b, 0),
    categorias: Object.keys(porSnapshot[s]).sort()
  })),
  presenca_por_categoria: presenca,
  itens_em_mais_de_uma_categoria: itensEmMaisDeUmaCategoria
} }];

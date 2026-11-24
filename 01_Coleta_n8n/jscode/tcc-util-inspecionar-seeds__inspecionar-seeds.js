// ============================================================================
// GERADO AUTOMATICAMENTE — NÃO EDITE ESTE ARQUIVO.
//
// Workflow : TCC — [util] Inspecionar Seeds
// Nó       : Inspecionar Seeds
// ID n8n   : fenQvqnDa1eU82YM
// Origem   : 01_Coleta_n8n/workflows/fenQvqnDa1eU82YM__TCC_util_Inspecionar_Seeds.json
// Gerado em: 2026-09-09 por extrair_jscode.py
//
// Este arquivo é uma CÓPIA LEGÍVEL, para leitura, diff e citação na monografia.
// A fonte da verdade é o n8n; o backup .json é o espelho dele.
// Para mudar o coletor: n8n (rascunho -> teste manual -> publicar) -> reexportar
// o .json -> rodar `python 01_Coleta_n8n/extrair_jscode.py` de novo.
// ============================================================================

// Inspetor somente leitura da tcc_seeds. Nao grava nada.
// Mostra o que sao as linhas inativas, como as origens se distribuem
// e qual o estado do youtube_slot.
const seeds = $('Ler Seeds').all().map(i => i.json);

const contar = (rows, campo) => {
  const m = {};
  for (const r of rows) {
    const v = r[campo];
    const k = (v === null || v === undefined || v === '') ? '(vazio)' : String(v);
    m[k] = (m[k] || 0) + 1;
  }
  return m;
};

const ativos = seeds.filter(r => r.ativo === true);
const inativos = seeds.filter(r => r.ativo !== true);
const comBuzz = seeds.filter(r => r.coletar_youtube === true);

return [{ json: {
  gerado_em: new Date().toISOString(),
  total: seeds.length,
  colunas: seeds.length ? Object.keys(seeds[0]) : [],
  ativos: ativos.length,
  inativos: inativos.length,
  por_origem: contar(seeds, 'origem'),
  por_origem_somente_ativos: contar(ativos, 'origem'),
  com_youtube: comBuzz.length,
  slot_todos: contar(seeds, 'youtube_slot'),
  slot_entre_os_com_buzz: contar(comBuzz, 'youtube_slot'),
  buzz_sem_slot: comBuzz.filter(r => !r.youtube_slot).map(r => r.termo),
  as_linhas_inativas: inativos.map(r => ({ id: r.id, termo: r.termo, categoria: r.categoria, origem: r.origem, justificativa: String(r.justificativa || '').slice(0, 160) })),
  amostra_com_buzz: comBuzz.slice(0, 3).map(r => ({ id: r.id, termo: r.termo, categoria: r.categoria, origem: r.origem, youtube_slot: r.youtube_slot }))
} }];

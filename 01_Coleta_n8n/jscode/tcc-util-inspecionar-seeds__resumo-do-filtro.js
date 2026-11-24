// ============================================================================
// GERADO AUTOMATICAMENTE — NÃO EDITE ESTE ARQUIVO.
//
// Workflow : TCC — [util] Inspecionar Seeds
// Nó       : Resumo do Filtro
// ID n8n   : fenQvqnDa1eU82YM
// Origem   : 01_Coleta_n8n/workflows/fenQvqnDa1eU82YM__TCC_util_Inspecionar_Seeds.json
// Gerado em: 2026-09-09 por extrair_jscode.py
//
// Este arquivo é uma CÓPIA LEGÍVEL, para leitura, diff e citação na monografia.
// A fonte da verdade é o n8n; o backup .json é o espelho dele.
// Para mudar o coletor: n8n (rascunho -> teste manual -> publicar) -> reexportar
// o .json -> rodar `python 01_Coleta_n8n/extrair_jscode.py` de novo.
// ============================================================================

// Simula a leitura que o coletor do YouTube faz (mesmas 3 condicoes), sem gastar
// cota nenhuma: aqui so se le a tabela, nao se chama a API. Serve para provar que o
// filtro por slot devolve a metade certa antes de publicar o coletor.
const doSlot = $('Simular Filtro YouTube').all().map(i => i.json);
const slots = new Set(doSlot.map(r => r.youtube_slot));

return [{ json: {
  gerado_em: new Date().toISOString(),
  slot_escolhido_pela_hora: [...slots],
  termos_que_seriam_coletados: doSlot.length,
  custo_em_unidades_de_cota: doSlot.length * 100,
  cabe_nas_10000: doSlot.length * 100 <= 10000,
  algum_sem_slot: doSlot.some(r => !r.youtube_slot),
  categorias: [...new Set(doSlot.map(r => r.categoria))].sort(),
  amostra: doSlot.slice(0, 5).map(r => ({ termo: r.termo, categoria: r.categoria, youtube_slot: r.youtube_slot }))
} }];

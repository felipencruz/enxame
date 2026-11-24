// ============================================================================
// GERADO AUTOMATICAMENTE — NÃO EDITE ESTE ARQUIVO.
//
// Workflow : TCC — [util] Preencher youtube_slot
// Nó       : Calcular Slot
// ID n8n   : 4LtPjoPSA55CF8Es
// Origem   : 01_Coleta_n8n/workflows/4LtPjoPSA55CF8Es__TCC_util_Preencher_youtube_slot.json
// Gerado em: 2026-09-09 por extrair_jscode.py
//
// Este arquivo é uma CÓPIA LEGÍVEL, para leitura, diff e citação na monografia.
// A fonte da verdade é o n8n; o backup .json é o espelho dele.
// Para mudar o coletor: n8n (rascunho -> teste manual -> publicar) -> reexportar
// o .json -> rodar `python 01_Coleta_n8n/extrair_jscode.py` de novo.
// ============================================================================

// Atribui o youtube_slot (A/B) aos termos com buzz.
// Regra determinista e reexecutavel: ordena os termos com coletar_youtube=true
// por (categoria, termo) e alterna A/B dentro de cada categoria, para que nenhum slot
// fique enviesado para uma vertical. O slot e derivado do dado, nao escolhido: rodar
// de novo depois de a amostra crescer reatribui tudo pela mesma regra.
// Comparacao por codepoint (nao localeCompare) para bater com o sorted() do Python.
//
// Custo de rodar no meio do dia (medido em 12/08/2026, antes da execucao):
// o coletor filtra por "$now.hour < 12 ? A : B", e o $now do n8n responde no fuso do
// workflow (America/Sao_Paulo), nao em UTC. As rodadas sao 00:00 e 12:00 BRT
// (03:00 e 15:00 UTC), entao A = rodada da madrugada, B = rodada do meio-dia.
// Termo que vai de A para B coleta duas vezes no mesmo dia, sem dano, porque o perfil
// agrupa por (termo, dia). Termo que vai de B para A nao coleta naquele dia: o A ja
// passou. Em 12/08/2026 foram 6 termos sem coleta naquele dia.
// Por isso, rodar logo depois da rodada das 12:00 BRT deixa o dia inteiro para todos.
const seeds = $('Ler Seeds').all().map(i => i.json);
const comBuzz = seeds.filter(r => r.coletar_youtube === true);

const cmp = (a, b) => {
  if (a.categoria !== b.categoria) return a.categoria < b.categoria ? -1 : 1;
  if (a.termo !== b.termo) return a.termo < b.termo ? -1 : 1;
  return 0;
};
comBuzz.sort(cmp);

const contador = {};
return comBuzz.map(r => {
  const cat = r.categoria;
  contador[cat] = contador[cat] || 0;
  const slot = contador[cat] % 2 === 0 ? 'A' : 'B';
  contador[cat] += 1;
  return { json: { id: r.id, termo: r.termo, categoria: cat, slot_atual: r.youtube_slot, youtube_slot: slot } };
});

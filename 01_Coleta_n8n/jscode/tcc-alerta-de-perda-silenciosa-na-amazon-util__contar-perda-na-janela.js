// ============================================================================
// GERADO AUTOMATICAMENTE — NÃO EDITE ESTE ARQUIVO.
//
// Workflow : TCC — Alerta de Perda Silenciosa na Amazon (util)
// Nó       : Contar Perda na Janela
// ID n8n   : srxlA0ItOoj0BCGX
// Origem   : 01_Coleta_n8n/workflows/srxlA0ItOoj0BCGX__TCC_Alerta_de_Perda_Silenciosa_na_Amazon_util.json
// Gerado em: 2026-09-09 por extrair_jscode.py
//
// Este arquivo é uma CÓPIA LEGÍVEL, para leitura, diff e citação na monografia.
// A fonte da verdade é o n8n; o backup .json é o espelho dele.
// Para mudar o coletor: n8n (rascunho -> teste manual -> publicar) -> reexportar
// o .json -> rodar `python 01_Coleta_n8n/extrair_jscode.py` de novo.
// ============================================================================

// Alerta de perda silenciosa na Amazon, criado em 11/08/2026: rodada que grava
// com parte das vitrines em erro, sem que nenhum outro alerta a detecte.
//
// O que este alerta vigia, e por que o de 18h nao basta. Aquele pergunta "quando
// foi a ultima linha?" e existe para detectar coletor parado. Uma rodada em que 3 das
// 22 vitrines falharam grava, e grava no horario certo: para aquele, e uma rodada
// normal. A perda nao e de rodada inteira, e de parte da rodada.
//
// Como a linha de erro e identificada: pelo item_id vazio, nao pelo texto do titulo.
// O invariante foi medido na serie exportada inteira, deduplicada por id (11/08/2026):
// 59 linhas de erro, as 59 com item_id vazio, e nenhuma linha de item_id vazio que
// nao seja erro. Reconferido em 24/08/2026 na serie ate aquela data: 82 de 82 nos
// dois sentidos, contando cada linha uma vez (os exports se sobrepoem, entao o
// concat cru dos arquivos conta linhas repetidas). E o mesmo invariante que a Silver
// usa para descartar essas linhas.
// O operador tambem foi medido (sonda de 11/08/2026, execucao 3248): no no
// dataTable, 'isEmpty' casa nulo, e 'eq' com string vazia nao casa nada.
//
// Os nos de leitura acima e este nao usam executeOnce, de proposito. Com o flag,
// a leitura seria truncada na primeira linha: com 3 vitrines em erro, o alerta
// diria "1 vitrine(s) em erro". O teste com dado fixado em 11/08/2026 (execucao
// 3249) injetou 4 linhas e confirmou a contagem.
//
// O envio foi testado em 11/08/2026 (execucao 3256): um rascunho temporario injetou
// uma vitrine ficticia so para o Filtro deixar passar, e o evolution-api aceitou a
// mensagem (fromMe: true). O rascunho foi desfeito no mesmo minuto; esta versao
// nao tem bloco de teste, e e a publicada. Sem esse disparo, a credencial so seria
// exercitada no primeiro episodio real, justamente quando uma falha custaria mais.
//
// Janela de 24h em vez de memoria. A Amazon coleta a 12/12h. Rodando 1x por dia,
// depois da segunda rodada, uma janela de 24h cobre as duas, e o workflow nao
// precisa guardar o que ja avisou. Sem estado guardado, nao ha estado que possa
// ficar inconsistente. (Alternativas descartadas em 11/08/2026: avisar a cada rodada,
// que dispararia em ~30% delas, e limiar >=3 vitrines, que perderia a maioria dos
// casos, porque a maioria e de 1 a 2 vitrines.)
//
// A janela depende do horario da purga, e a margem foi conferida: o backup diario
// purga a tabela as 15:00 BRT (18:00 UTC) deixando so o snapshot mais recente.
// Este alerta roda as 12:20 BRT (15:20 UTC), 2h40 antes da purga, e a essa hora a
// tabela tem as duas rodadas do dia (03:00 e 15:00 UTC) mais a de 15:00 do dia
// anterior, que a janela de 24h exclui por 20 minutos. Mover qualquer um dos dois
// horarios altera essa margem.
//
// Este no sempre emite o que viu, inclusive zero vitrine em erro; quem decide
// avisar e o Filtro seguinte. Monitor que devolve [] quando esta tudo bem e
// indistinguivel de monitor morto.
//
// O que este no nao faz: traduzir rotulo -> slug. Esse mapa e versionado, mora no
// 03_Analise/amazon_vitrines_inventario.py, e copia-lo para ca criaria uma segunda
// copia que envelhece sozinha. A mensagem aponta para o script que traduz.
const NL = String.fromCharCode(10);
const JANELA_H = 24;
const LIMIAR_VITRINES = 1;
const agora = Date.now();
const recentes = [];
let lidas = 0;
for (const item of $input.all()) {
  const j = item.json || {};
  if (!j.coletado_em) { continue; }
  lidas = lidas + 1;
  const idadeH = (agora - new Date(j.coletado_em).getTime()) / 3600000;
  if (idadeH <= JANELA_H) { recentes.push(j); }
}
const porVitrine = {};
const rodadas = {};
for (const r of recentes) {
  const nome = r.categoria_pagina || "(sem categoria)";
  if (!porVitrine[nome]) { porVitrine[nome] = { vitrine: nome, ocorrencias: 0, ultima_rodada: null, ultimo_motivo: null }; }
  porVitrine[nome].ocorrencias = porVitrine[nome].ocorrencias + 1;
  if (!porVitrine[nome].ultima_rodada || r.coletado_em > porVitrine[nome].ultima_rodada) {
    porVitrine[nome].ultima_rodada = r.coletado_em;
    porVitrine[nome].ultimo_motivo = r.titulo || null;
  }
  rodadas[r.coletado_em] = true;
}
const vitrines = [];
for (const nome of Object.keys(porVitrine)) { vitrines.push(porVitrine[nome]); }
vitrines.sort(function (a, b) { return a.vitrine < b.vitrine ? -1 : 1; });
const nRodadas = Object.keys(rodadas).length;
const alertar = vitrines.length >= LIMIAR_VITRINES;
let txt = "";
if (alertar) {
  txt = "*ENXAME - perda silenciosa na Amazon*" + NL + NL;
  txt = txt + "Nas ultimas " + JANELA_H + "h: " + vitrines.length + " vitrine(s) em erro, em " + nRodadas + " rodada(s)." + NL + NL;
  for (const v of vitrines) {
    const quando = v.ultima_rodada ? v.ultima_rodada.slice(0, 16).replace("T", " ") + " UTC" : "?";
    txt = txt + "- " + v.vitrine + " (" + v.ocorrencias + "x, ultima " + quando + ")" + NL;
  }
  txt = txt + NL + "Motivo gravado: " + (vitrines[0].ultimo_motivo || "?") + NL;
  txt = txt + "A rodada GRAVOU: o alerta de 18h nao pega isto." + NL;
  txt = txt + "Para sondar as vitrines: python 03_Analise/vitrines_amazon_em_erro.py";
}
return [{ json: {
  alertar: alertar,
  resumo: alertar ? vitrines.length + " vitrine(s) em erro em " + JANELA_H + "h" : "nenhuma vitrine em erro na janela, nada a enviar",
  janela_horas: JANELA_H,
  limiar_vitrines: LIMIAR_VITRINES,
  linhas_de_erro_lidas: lidas,
  linhas_de_erro_na_janela: recentes.length,
  rodadas_afetadas: nRodadas,
  verificado_em: new Date().toISOString(),
  vitrines: vitrines,
  mensagem: txt
} }];

// ============================================================================
// GERADO AUTOMATICAMENTE — NÃO EDITE ESTE ARQUIVO.
//
// Workflow : TCC — Alerta de Coletor Parado (util)
// Nó       : Avaliar Frescor
// ID n8n   : Pla4o3Wvk10O76QP
// Origem   : 01_Coleta_n8n/workflows/Pla4o3Wvk10O76QP__TCC_Alerta_de_Coletor_Parado_util.json
// Gerado em: 2026-09-09 por extrair_jscode.py
//
// Este arquivo é uma CÓPIA LEGÍVEL, para leitura, diff e citação na monografia.
// A fonte da verdade é o n8n; o backup .json é o espelho dele.
// Para mudar o coletor: n8n (rascunho -> teste manual -> publicar) -> reexportar
// o .json -> rodar `python 01_Coleta_n8n/extrair_jscode.py` de novo.
// ============================================================================

// Alerta de coletor parado, criado em 25/07/2026, depois de o coletor do
// Mercado Livre ficar 37 horas parado sem deteccao.
//
// Limiar = 18h, e o numero tem motivo. Amazon e YouTube coletam a 12/12h,
// entao a idade da ultima coleta dessas fontes oscila naturalmente ate 12h. Um limiar
// de 12h dispararia em todo ciclo normal, e alerta que dispara todo dia vira
// ruido que se aprende a ignorar, com o mesmo efeito de nao ter alerta.
// 18h da 6h de folga e teria detectado a parada do ML no mesmo dia.
//
// Este no sempre devolve um item, mesmo com tudo saudavel, por desenho: um
// monitor que nao mostra nada quando esta tudo bem e indistinguivel de um
// monitor morto, que e exatamente a falha silenciosa que este alerta existe
// para evitar. Toda execucao mostra o que o no viu, fonte por fonte, com
// idade em horas; quem decide enviar e o Filtro seguinte.
//
// 28/07/2026: o Mercado Livre voltou para a conta (5 de 5 fontes monitoradas).
// O ML estava com monitorar:false desde 25/07/2026 porque a fonte tinha fechado as
// rotas ao cracha honesto e o coletor fora despublicado; monitorar uma parada
// conhecida faria o alerta disparar todo dia. Em 28/07 a fonte reabriu, medido
// do mesmo servidor, com a mesma URL e o mesmo metodo de 25/07: 517.012 bytes,
// 162 IDs MLB e 301 precos ao EnxameBot, contra 133.957 bytes e zero produtos
// cinco dias antes. O coletor foi republicado e voltou a rodar a 6/6h.
// Com o flag em false, o ML estaria no ar e fora da vigilancia: a mesma falha
// silenciosa que este alerta existe para impedir.
const NL = String.fromCharCode(10);
const LIMITE_H = 18;
const FONTES = [
  { nome: 'Google Suggest', no: 'Ler Suggest', agenda: '6/6h', monitorar: true },
  { nome: 'YouTube', no: 'Ler YouTube', agenda: '12/12h', monitorar: true },
  { nome: 'Shopee', no: 'Ler Shopee', agenda: '6/6h', monitorar: true },
  { nome: 'Amazon', no: 'Ler Amazon', agenda: '12/12h', monitorar: true },
  { nome: 'Mercado Livre', no: 'Ler ML', agenda: '6/6h', monitorar: true }
];
const agora = Date.now();
const paradas = [];
const situacao = [];
for (const f of FONTES) {
  let ts = null;
  try { ts = ($(f.no).first() || {}).json.coletado_em || null; } catch (e) { ts = null; }
  const idadeH = ts ? (agora - new Date(ts).getTime()) / 3600000 : null;
  const reg = {
    fonte: f.nome, agenda: f.agenda, ultima_coleta: ts,
    idade_horas: idadeH === null ? null : Math.round(idadeH * 10) / 10,
    monitorada: f.monitorar
  };
  if (!f.monitorar) { reg.estado = 'fora da conta'; reg.motivo = f.motivo; situacao.push(reg); continue; }
  reg.parada = idadeH === null || idadeH > LIMITE_H;
  reg.estado = reg.parada ? 'PARADA' : 'ok';
  if (reg.parada) paradas.push(reg);
  situacao.push(reg);
}
let txt = '';
if (paradas.length > 0) {
  txt = '*ENXAME - coletor parado*' + NL + NL;
  for (const p of paradas) {
    const quando = p.ultima_coleta ? p.ultima_coleta.slice(0, 16).replace('T', ' ') + ' UTC' : 'nunca';
    const quanto = p.idade_horas === null ? 'sem nenhuma coleta' : p.idade_horas + 'h atras';
    txt += '- ' + p.fonte + ' (' + p.agenda + '): ultima em ' + quando + ', ' + quanto + NL;
  }
  txt += NL + 'Limiar: ' + LIMITE_H + 'h. Verificado em ' + new Date().toISOString().slice(0, 16).replace('T', ' ') + ' UTC.' + NL;
  txt += 'As 5 fontes estao na conta: o Mercado Livre voltou em 28/07.';
}
return [{ json: {
  alertar: paradas.length > 0,
  resumo: paradas.length === 0 ? 'tudo ok, nada a enviar' : paradas.length + ' fonte(s) parada(s)',
  limite_horas: LIMITE_H,
  fontes_monitoradas: FONTES.filter(function (f) { return f.monitorar; }).length,
  verificado_em: new Date().toISOString(),
  situacao: situacao,
  mensagem: txt
} }];

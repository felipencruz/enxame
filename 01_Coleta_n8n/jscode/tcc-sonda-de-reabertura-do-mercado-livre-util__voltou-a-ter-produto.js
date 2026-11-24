// ============================================================================
// GERADO AUTOMATICAMENTE — NÃO EDITE ESTE ARQUIVO.
//
// Workflow : TCC — Sonda de Reabertura do Mercado Livre (util)
// Nó       : Voltou a ter produto?
// ID n8n   : 8tJHu2GraKa3pnTU
// Origem   : 01_Coleta_n8n/workflows/8tJHu2GraKa3pnTU__TCC_Sonda_de_Reabertura_do_Mercado_Livre_util.json
// Gerado em: 2026-09-09 por extrair_jscode.py
//
// Este arquivo é uma CÓPIA LEGÍVEL, para leitura, diff e citação na monografia.
// A fonte da verdade é o n8n; o backup .json é o espelho dele.
// Para mudar o coletor: n8n (rascunho -> teste manual -> publicar) -> reexportar
// o .json -> rodar `python 01_Coleta_n8n/extrair_jscode.py` de novo.
// ============================================================================

// Sonda de reabertura do Mercado Livre, criada em 28/07/2026.
//
// Motivo: o coletor do ML foi despublicado em 25/07/2026 porque a fonte passou a
// servir dado apenas a quem se apresenta como navegador. A identidade do robo
// nao muda, mas e preciso vigiar se a fonte volta atras. O alerta de coletor
// parado deixa de fora uma parada conhecida (senao dispararia todo dia), entao,
// sem esta sonda, a serie seguiria parada por uma condicao que talvez ja nao
// existisse.
//
// Etica: a requisicao passa antes pelo Agente 1 (no anterior), que le o
// robots.txt para o EnxameBot. Se o Agente 1 negar, esta sonda nao busca, e mesmo
// assim emite diagnostico. A rota e a geral (/mais-vendidos/), permitida; a
// rota por categoria (/mais-vendidos/MLB...) e proibida e nao e acessada.
//
// Este no sempre emite, mesmo quando nada mudou: monitor que nao mostra nada
// quando esta tudo igual e indistinguivel de monitor morto.
// Quem decide enviar e o Filtro seguinte.
const NL = String.fromCharCode(10);
const LIMIAR_IDS = 20;
const LIMIAR_PRECOS = 20;

let permitido = false;
let motivo = 'nao foi possivel ler o veredito do Agente 1';
try {
  const v = $('Agente 1: robots permite?').first().json;
  permitido = v.permitido === true;
  motivo = v.motivo || (permitido ? 'permitido' : 'negado');
} catch (e) { permitido = false; }

let html = '';
let buscou = false;
try {
  const r = $('Buscar mais-vendidos').first().json;
  html = (r && (r.data || r.body)) || '';
  if (typeof html !== 'string') { html = JSON.stringify(html); }
  buscou = true;
} catch (e) { buscou = false; }

const ids = new Set(html.match(/MLB\d{6,}/g) || []);
const precos = (html.match(/R\$/g) || []).length;
const voltou = buscou && ids.size >= LIMIAR_IDS && precos >= LIMIAR_PRECOS;

// O limiar de 20 tem motivo: com o coletor saudavel, a pagina trazia ~157
// produtos; com a fonte fechada, ela devolve zero ao cracha honesto. 20 fica
// longe dos dois extremos: pagina parcial nao dispara e retorno real nao passa
// despercebido.
let txt = '';
if (voltou) {
  txt = '*ENXAME - o Mercado Livre voltou a servir produto*' + NL + NL;
  txt += 'A rota /mais-vendidos/ devolveu ' + ids.size + ' IDs MLB distintos e ';
  txt += precos + ' ocorrencias de preco AO CRACHA HONESTO (EnxameBot).' + NL + NL;
  txt += 'Desde 23/07 ela devolvia casca: 0 produtos.' + NL;
  txt += 'Encaminhamento ja decidido: republicar o workflow 5vSP1WtLKpTTVBn6' + NL;
  txt += 'e fechar o vazio da serie -- SEM tocar na identidade do robo.' + NL + NL;
  txt += 'Verificado em ' + new Date().toISOString().slice(0, 16).replace('T', ' ') + ' UTC.';
}

return [{ json: {
  avisar: voltou,
  fonte: 'mercadolivre',
  rota: 'https://www.mercadolivre.com.br/mais-vendidos/',
  cracha: 'EnxameBot/0.1 (+https://automatize-ai.tech)',
  agente1_permitido: permitido,
  agente1_motivo: motivo,
  buscou: buscou,
  bytes: html.length,
  ids_mlb_distintos: ids.size,
  ocorrencias_de_preco: precos,
  limiar_ids: LIMIAR_IDS,
  limiar_precos: LIMIAR_PRECOS,
  estado: !permitido ? 'robots negou -- nao buscamos'
        : !buscou ? 'busca falhou (rede ou bloqueio)'
        : voltou ? 'VOLTOU A TER PRODUTO'
        : 'segue servindo casca ao cracha honesto',
  verificado_em: new Date().toISOString(),
  mensagem: txt
} }];

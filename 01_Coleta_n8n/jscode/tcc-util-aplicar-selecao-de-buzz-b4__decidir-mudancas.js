// ============================================================================
// GERADO AUTOMATICAMENTE — NÃO EDITE ESTE ARQUIVO.
//
// Workflow : TCC — [util] Aplicar Selecao de Buzz (B4)
// Nó       : Decidir Mudancas
// ID n8n   : NH2PY5s42gnwh0sg
// Origem   : 01_Coleta_n8n/workflows/NH2PY5s42gnwh0sg__TCC_util_Aplicar_Selecao_de_Buzz_B4.json
// Gerado em: 2026-09-09 por extrair_jscode.py
//
// Este arquivo é uma CÓPIA LEGÍVEL, para leitura, diff e citação na monografia.
// A fonte da verdade é o n8n; o backup .json é o espelho dele.
// Para mudar o coletor: n8n (rascunho -> teste manual -> publicar) -> reexportar
// o .json -> rodar `python 01_Coleta_n8n/extrair_jscode.py` de novo.
// ============================================================================

// Aplica a selecao da Parte B4 na coluna coletar_youtube da tcc_seeds.
// As duas listas sao a saida de 03_Analise/parte_b4_remodelar_youtube.py: a regra
// mora no Python (auditavel, com teste); aqui so se escreve o resultado dela.
// Regra B, teto 95: fica quem ja coleta e tem serie de buzz que varia; as vagas
// restantes vao por suporte de mercado; sai quem tem serie constante (informacao
// zero) ou nenhum campeao no alvo.
//
// Rodada de 12/08/2026 (a 2a; a 1a foi em 22/07/2026). E a primeira que poda os termos
// que entraram sem buzz medido: os 7 que saem sao todos daquela leva, e nenhum
// termo da coorte antiga mudou de estado.
// Desde 12/08/2026 o script deriva "quem coleta hoje" do estado atual de coleta, e
// nao da serie do YouTube, que guarda tambem os termos ja desligados.
const LIGAR = ['bebida alcoolica','controle de videogame','escova de dentes','guarda roupa','lenco umedecido','micro ondas','mixer de cozinha'];
const DESLIGAR = ['cafe','camera de seguranca','mouse','protetor solar','shampoo','tapete','teclado'];
const TETO = 95;

const seeds = $('Ler Seeds').all().map(i => i.json);
const existe = {};
for (const s of seeds) { existe[s.termo] = true; }

// Fail-closed: se um termo da selecao nao existe na tabela, para tudo em vez de
// aplicar metade da mudanca em silencio.
const faltando = [];
for (const t of LIGAR) { if (!existe[t]) faltando.push(t); }
for (const t of DESLIGAR) { if (!existe[t]) faltando.push(t); }
if (faltando.length > 0) { throw new Error('Termos da selecao ausentes na tcc_seeds: ' + faltando); }

const mudancas = [];
for (const s of seeds) {
  let desejado = null;
  if (LIGAR.indexOf(s.termo) !== -1) { desejado = true; }
  else if (DESLIGAR.indexOf(s.termo) !== -1) { desejado = false; }
  if (desejado === null) { continue; }
  if (s.coletar_youtube === desejado) { continue; }
  mudancas.push({ json: { id: s.id, termo: s.termo, de: s.coletar_youtube, para: desejado, coletar_youtube: desejado, youtube_slot: desejado ? s.youtube_slot : null } });
}

// Trava do teto (desde 12/08/2026). O teto e a razao de a regra existir: 95 termos =
// 9.500 das 10.000 unidades/dia da API. Conferir o total previsto aqui, antes de gravar,
// e o unico ponto em que o erro ainda e barato: depois da gravacao, a cota estoura
// na coleta seguinte, longe daqui.
let ligadosHoje = 0;
for (const s of seeds) { if (s.coletar_youtube === true) { ligadosHoje += 1; } }
let ligando = 0;
let desligando = 0;
for (const m of mudancas) { if (m.json.para === true) { ligando += 1; } else { desligando += 1; } }
const previsto = ligadosHoje - desligando + ligando;
if (previsto > TETO) {
  throw new Error('a selecao deixaria ' + previsto + ' termos coletando buzz, acima do teto de ' + TETO + ' (cota do YouTube). Nada foi gravado.');
}

// Sempre emite o diagnostico, mesmo sem mudanca: monitor que devolve [] quando esta
// tudo bem e indistinguivel de monitor morto.
if (mudancas.length === 0) {
  return [{ json: { nada_a_fazer: true, ligados_hoje: ligadosHoje, previsto: previsto } }];
}
return mudancas;

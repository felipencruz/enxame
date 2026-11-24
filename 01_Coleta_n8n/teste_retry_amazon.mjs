/**
 * Teste determinístico do laço de coleta da Amazon COM RETRY (até 3 tentativas por vitrine).
 *
 * POR QUE ELE EXISTE, e por que nenhuma execução real o substitui.
 * O ramo que o retry existe para cobrir — "a vitrine recusou na 1ª tentativa e
 * entregou na 2ª" — não se produz sob comando contra a fonte: ele depende de a
 * Amazon recusar naquele segundo. Uma execução real exercita só o caminho feliz e
 * o erro persistente. Aqui o `httpRequest` é substituído por um duplo que falha
 * quando se manda falhar, e é isso que torna os quatro ramos verificáveis: um
 * instrumento que distingue causas se exercita uma vez com cada causa, e não só
 * com a saudável.
 *
 * O QUE ELE TRAVA, e cada um foi motivo de defeito possível no desenho:
 *  1. sucesso na 1ª  -> 50 linhas, NENHUMA linha de erro, 1 chamada;
 *  2. falha e recupera na 2ª/3ª -> 50 linhas, NENHUMA linha de erro (senão o
 *     alerta de perda silenciosa contaria vitrine que não se perdeu);
 *  3. falha nas 3 -> exatamente 1 linha de erro, `item_id` NULO e `titulo`
 *     começando com "[ERRO]" — os dois invariantes de que a Silver e o alerta
 *     dependem (`preparar_silver.linhas_legitimas_amazon`, workflow srxlA0ItOoj0BCGX);
 *  4. `coletado_em` IDÊNTICO em toda a rodada, inclusive nas linhas recuperadas na
 *     3ª passada — a purga diária guarda "o snapshot mais recente" e o alerta
 *     agrupa rodada por esse campo: carimbo novo no meio da rodada partiria o
 *     snapshot em dois;
 *  5. nada de linha duplicada quando a tentativa falha DEPOIS de já ter produzido
 *     linhas — por isso o laço só anexa ao resultado quando a vitrine fecha inteira.
 *
 * COMO RODAR:  node 01_Coleta_n8n/teste_retry_amazon.mjs
 * (as pausas entram por injeção, então ele roda em milissegundos)
 *
 * A FONTE DA VERDADE DO CÓDIGO É O n8n (`get_workflow_details`). O corpo abaixo é
 * uma CÓPIA do jsCode do nó "Coletar Vitrines" do
 * workflow UN8KNwlEsoLKm1kw, mantida aqui só para poder ser exercitada fora do n8n
 * — e ela diverge da produção no instante seguinte a qualquer edição lá.
 */

// ---------------------------------------------------------------------------
// A cópia do laço. Mantida o mais fiel possível ao jsCode publicado.
// ---------------------------------------------------------------------------
async function coletarVitrines({ vitrines, httpRequest, dormir, agora }) {
  const BASE = "https://www.amazon.com.br";
  const MAX_TENTATIVAS = 3;
  const PAUSA_VITRINE_MS = 3000;
  const PAUSA_VITRINE_RETRY_MS = 5000;
  const PAUSA_PASSADA_MS = 60000;

  const linhas = [];
  const motivos = {};
  let pendentes = vitrines;

  for (let tentativa = 1; tentativa <= MAX_TENTATIVAS; tentativa++) {
    if (pendentes.length === 0) { break; }
    if (tentativa > 1) { await dormir(PAUSA_PASSADA_MS); }
    const pausa = tentativa === 1 ? PAUSA_VITRINE_MS : PAUSA_VITRINE_RETRY_MS;
    const falharam = [];
    for (const v of pendentes) {
      try {
        const resp = await httpRequest({
          method: "POST",
          url: "http://enxame-api:8000/agentes/coletar",
          body: { url: v.url },
          json: true,
          timeout: 120000,
        });
        // Acumula em lista PRÓPRIA e só anexa se a vitrine fechar inteira: se a
        // chamada falhar depois de já ter produzido linhas, o retry duplicaria.
        const daVitrine = [];
        for (const n of (resp.linhas || [])) {
          const rel = n.link || "";
          const link = rel.startsWith("http") ? rel : (rel ? BASE + rel : null);
          const m = rel.match(/\/dp\/([A-Z0-9]{10})/i);
          daVitrine.push({ json: {
            item_id: m ? m[1] : null,
            titulo: n.titulo || null,
            preco: n.preco || null,
            categoria_pagina: v.rotulo_amazon,
            rank: n.rank || null,
            avaliacao: n.avaliacao || null,
            link: link,
            coletado_em: agora,
          }});
        }
        for (const l of daVitrine) { linhas.push(l); }
      } catch (e) {
        const detalhe = (e.message || String(e)).slice(0, 180);
        if (!motivos[v.rotulo_amazon]) { motivos[v.rotulo_amazon] = []; }
        motivos[v.rotulo_amazon].push(detalhe);
        falharam.push(v);
      }
      await dormir(pausa);
    }
    pendentes = falharam;
  }

  // Só vira LINHA DE ERRO quem a fonte recusou nas TRÊS tentativas.
  for (const v of pendentes) {
    const ds = motivos[v.rotulo_amazon] || [];
    let motivo = "sem detalhe";
    if (ds.length > 0) {
      let iguais = true;
      for (const d of ds) { if (d !== ds[0]) { iguais = false; } }
      if (iguais) {
        motivo = ds[0];
      } else {
        motivo = "";
        for (const d of ds) { motivo = motivo ? motivo + " | " + d : d; }
        motivo = motivo.slice(0, 180);
      }
    }
    linhas.push({ json: {
      item_id: null,
      titulo: "[ERRO] (" + ds.length + " tentativas) " + motivo,
      preco: null,
      categoria_pagina: v.rotulo_amazon,
      rank: null,
      avaliacao: null,
      link: v.url,
      coletado_em: agora,
    }});
  }
  return linhas;
}

// ---------------------------------------------------------------------------
// O duplo do httpRequest e os testes.
// ---------------------------------------------------------------------------
const AGORA = "2026-09-09T03:00:17.000Z";

function vitrine(rotulo) {
  return { rotulo_amazon: rotulo, url: "https://www.amazon.com.br/gp/bestsellers/" + rotulo };
}

/** Devolve 50 itens plausíveis, no formato do enxame-api. */
function paginaBoa(rotulo) {
  const linhas = [];
  for (let i = 1; i <= 50; i++) {
    linhas.push({
      titulo: rotulo + " produto " + i,
      preco: "R$ 10,00",
      rank: "#" + i,
      avaliacao: "4,5 de 5 estrelas",
      link: "/dp/B00000000" + (i % 10) + "/ref=x",
    });
  }
  return { linhas };
}

/**
 * `plano` mapeia rótulo -> nº de falhas antes de entregar (Infinity = nunca entrega).
 * Registra quantas chamadas cada vitrine recebeu, que é metade do que se afirma.
 */
function fazerHttp(plano) {
  const chamadas = {};
  return {
    chamadas,
    async httpRequest(req) {
      const rotulo = req.body.url.split("/bestsellers/")[1];
      chamadas[rotulo] = (chamadas[rotulo] || 0) + 1;
      const falhasAte = plano[rotulo] === undefined ? 0 : plano[rotulo];
      if (chamadas[rotulo] <= falhasAte) {
        throw new Error("Request failed with status code 503");
      }
      return paginaBoa(rotulo);
    },
  };
}

const dormirFake = async () => {};

let falhou = 0;
function ok(condicao, nome, detalhe) {
  if (condicao) {
    console.log("  ok   " + nome);
  } else {
    falhou++;
    console.log("  FALHOU " + nome + (detalhe ? "  -> " + detalhe : ""));
  }
}

function erros(linhas) {
  return linhas.filter((l) => String(l.json.titulo || "").startsWith("[ERRO]"));
}
function produtos(linhas) {
  return linhas.filter((l) => !String(l.json.titulo || "").startsWith("[ERRO]"));
}

console.log("\n1. sucesso na 1a tentativa");
{
  const h = fazerHttp({ toys: 0 });
  const r = await coletarVitrines({ vitrines: [vitrine("toys")], httpRequest: h.httpRequest, dormir: dormirFake, agora: AGORA });
  ok(h.chamadas.toys === 1, "chamou a fonte UMA vez", "chamou " + h.chamadas.toys);
  ok(produtos(r).length === 50, "50 linhas de produto", produtos(r).length + " linhas");
  ok(erros(r).length === 0, "nenhuma linha de erro");
}

console.log("\n2. recusa na 1a e entrega na 2a  (o ramo que o retry existe para cobrir)");
{
  const h = fazerHttp({ toys: 1 });
  const r = await coletarVitrines({ vitrines: [vitrine("toys")], httpRequest: h.httpRequest, dormir: dormirFake, agora: AGORA });
  ok(h.chamadas.toys === 2, "chamou a fonte DUAS vezes", "chamou " + h.chamadas.toys);
  ok(produtos(r).length === 50, "50 linhas de produto recuperadas", produtos(r).length + " linhas");
  ok(erros(r).length === 0, "NENHUMA linha de erro — senao o alerta contaria vitrine que nao se perdeu");
}

console.log("\n3. recusa na 1a e na 2a, entrega na 3a");
{
  const h = fazerHttp({ toys: 2 });
  const r = await coletarVitrines({ vitrines: [vitrine("toys")], httpRequest: h.httpRequest, dormir: dormirFake, agora: AGORA });
  ok(h.chamadas.toys === 3, "chamou a fonte TRES vezes", "chamou " + h.chamadas.toys);
  ok(produtos(r).length === 50, "50 linhas de produto recuperadas");
  ok(erros(r).length === 0, "nenhuma linha de erro");
}

console.log("\n4. recusa nas TRES  (o unico caso que ainda vira perda)");
{
  const h = fazerHttp({ toys: Infinity });
  const r = await coletarVitrines({ vitrines: [vitrine("toys")], httpRequest: h.httpRequest, dormir: dormirFake, agora: AGORA });
  ok(h.chamadas.toys === 3, "parou em TRES chamadas, nao insistiu mais", "chamou " + h.chamadas.toys);
  ok(erros(r).length === 1, "exatamente UMA linha de erro", erros(r).length + " linhas");
  const e = erros(r)[0].json;
  ok(e.item_id === null, "item_id NULO — e assim que o alerta e a Silver a acham");
  ok(String(e.titulo).startsWith("[ERRO]"), "titulo comeca com [ERRO] — o prefixo que a Silver filtra");
  ok(String(e.titulo).indexOf("(3 tentativas)") > 0, "declara as 3 tentativas na propria linha", e.titulo);
  ok(String(e.titulo).indexOf("503") > 0, "preserva o motivo da fonte", e.titulo);
  ok(e.categoria_pagina === "toys", "preserva a vitrine");
}

console.log("\n5. rodada mista, 22 vitrines  (o caso real de 08/09)");
{
  const plano = {};
  const vs = [];
  for (let i = 1; i <= 22; i++) {
    const nome = "vit" + i;
    vs.push(vitrine(nome));
    if (i <= 8) { plano[nome] = 1; }        // 8 recusam uma vez e voltam
    else if (i <= 10) { plano[nome] = 2; }  // 2 recusam duas e voltam na 3a
    else if (i <= 12) { plano[nome] = Infinity; } // 2 nunca voltam
    else { plano[nome] = 0; }
  }
  const h = fazerHttp(plano);
  const r = await coletarVitrines({ vitrines: vs, httpRequest: h.httpRequest, dormir: dormirFake, agora: AGORA });
  ok(produtos(r).length === 20 * 50, "20 vitrines entregaram 50 itens = 1.000 linhas", produtos(r).length + " linhas");
  ok(erros(r).length === 2, "so as 2 que recusaram TRES vezes viraram erro", erros(r).length + " linhas de erro");
  const carimbos = {};
  for (const l of r) { carimbos[l.json.coletado_em] = true; }
  ok(Object.keys(carimbos).length === 1, "UM unico coletado_em na rodada inteira — a purga guarda o snapshot mais recente", Object.keys(carimbos).length + " carimbos");
  const ids = {};
  let repetida = false;
  for (const l of produtos(r)) {
    const chave = l.json.categoria_pagina + "|" + l.json.rank;
    if (ids[chave]) { repetida = true; }
    ids[chave] = true;
  }
  ok(!repetida, "nenhuma linha duplicada pelo retry");
  // Sem retry, esta rodada teria perdido 12 vitrines: e a medida do que o retry recupera.
  ok(produtos(r).length === 1000 && erros(r).length === 2, "recuperou 10 das 12 vitrines que a rodada de 08/09 perderia");
}

console.log("\n6. a fonte devolve pagina VAZIA (nao e excecao): continua sem retry e sem erro");
{
  // Entrega sem linhas nao e falha para este laco — quem julga volume e a regua do
  // enxame-api, que ABORTA (limite 6) e ai vira excecao. Travado para que uma
  // mudanca futura nao transforme "vazio" em retry silencioso.
  const h = { chamadas: {}, async httpRequest(req) {
    const r = req.body.url.split("/bestsellers/")[1];
    h.chamadas[r] = (h.chamadas[r] || 0) + 1;
    return { linhas: [] };
  } };
  const r = await coletarVitrines({ vitrines: [vitrine("toys")], httpRequest: h.httpRequest, dormir: dormirFake, agora: AGORA });
  ok(h.chamadas.toys === 1, "uma chamada so", "chamou " + h.chamadas.toys);
  ok(r.length === 0, "nenhuma linha, nenhum erro — o silencio e do enxame-api, nao deste laco");
}

console.log("\n" + (falhou === 0 ? "TODOS OS TESTES PASSARAM" : falhou + " TESTE(S) FALHARAM"));
process.exit(falhou === 0 ? 0 : 1);

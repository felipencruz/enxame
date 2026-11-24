"""Agente 4: Supervisor e Reparador (fecha o ciclo auto-reparável).

Quando uma receita deixa de funcionar (a página mudou, ou o Agente 2 propôs um
seletor errado), o Supervisor mede o problema, descreve o defeito em texto e
devolve o diagnóstico ao LLM pedindo uma receita corrigida. Repete por algumas
tentativas e fica com a melhor.

Quem decide é o código, não o LLM (princípio do projeto):
- O LLM só propõe seletores, nunca valores nem o veredito.
- Quem mede é `validar_receita` (determinístico).
- Quem decide aceitar é `pontuar` com a comparação numérica abaixo. Uma receita
  nova só substitui a anterior se pontuar mais alto. O LLM não se autoavalia.

Caso real que motivou o desenho (14/07/2026, Amazon `/gp/bestsellers/`): o Agente 2
propôs `seletor_grupo: ".a-carousel-heading"` (o título do carrossel) em vez do
contêiner da vitrine; os itens passaram a ser procurados dentro do <h2> e a receita
foi de 36 para 0 itens. O erro foi detectado pela régua determinística, sem
intervenção humana.
"""

import json

from bs4 import BeautifulSoup

from app import custo_llm
from app.agentes import analista_estrutura


def _buscar_html_padrao(url: str) -> str:
    """Import tardio de propósito: `app.coleta_http` importa `app.agentes.conformidade`,
    e importá-lo no topo acoplaria o Supervisor à camada de rede, que os testes
    precisam substituir. Quem chama pode injetar outro `buscar_html`."""
    from app import coleta_http

    return coleta_http.buscar_html(url)


MAX_TENTATIVAS_PADRAO = 3
TAXA_CAMPO_RUIM = 0.5  # abaixo disso, o campo é considerado defeituoso


def pontuar(validacao: dict) -> float:
    """Nota objetiva de uma receita: 0.0 se não achou item algum; senão, a taxa
    média dos campos, contando só os valores que passam no tipo/faixa declarado
    (`taxa_valida`). Serve para comparar receitas entre si e usa a mesma medida
    da régua de aceite, para que uma receita não supere outra preenchendo campos
    com valores inválidos. Campo sem `tipo` declarado é medido só por
    preenchimento."""
    if not validacao.get("itens_encontrados"):
        return 0.0
    taxas = [c.get("taxa_valida", c["taxa"]) for c in validacao.get("campos", {}).values()]
    return round(sum(taxas) / len(taxas), 4) if taxas else 0.0


def _seletor_valido(seletor: str | None) -> bool:
    """O seletor CSS compila? Usa o mesmo parser da extração, não um regex.

    Seletor vazio passa como válido aqui, mas não significa "o próprio elemento do
    item": na extração (`analista_estrutura._extrair_campos`), `select_one("")`
    levanta, o erro é capturado e o campo sai vazio. Nenhuma receita usa seletor
    vazio; se o LLM propuser um, quem acusa é a taxa de preenchimento do campo.
    """
    if not seletor:
        return True
    try:
        BeautifulSoup("", "html.parser").select(seletor)
    except Exception:
        return False
    return True


def diagnosticar(receita: dict, validacao: dict) -> list[str]:
    """Traduz a medição em defeitos concretos; é isto que o LLM recebe de volta."""
    problemas = []
    if not validacao.get("itens_encontrados"):
        alvo = receita.get("seletor_item")
        if receita.get("seletor_grupo"):
            problemas.append(
                f"NENHUM item encontrado. O seletor_grupo {receita['seletor_grupo']!r} "
                f"ou o seletor_item {alvo!r} está errado. Atenção: o seletor_grupo deve ser o "
                "CONTÊINER da vitrine (o elemento que envolve os produtos), NÃO o título dela; "
                "e o seletor_item é procurado DENTRO do grupo."
            )
        else:
            problemas.append(f"NENHUM item encontrado: o seletor_item {alvo!r} não casa com nada.")
        return problemas

    campos_receita = {**(receita.get("campos_grupo") or {}), **(receita.get("campos") or {})}
    ausentes_confirmados = set((receita.get("_meta") or {}).get("campos_ausentes") or {})

    for nome, medida in validacao.get("campos", {}).items():
        taxa_valida = medida.get("taxa_valida", medida["taxa"])
        if taxa_valida >= TAXA_CAMPO_RUIM:
            continue
        if nome in ausentes_confirmados:
            # Já investigado: a fonte não publica este campo. Não é defeito de
            # receita e nenhum reparo o traria de volta; insistir só gastaria LLM.
            continue
        if nome in campos_receita and campos_receita[nome] is None:
            continue  # mapeado como null de propósito (prompt do Analista: campo inexistente vira null)
        regra = campos_receita.get(nome)
        if regra is None:
            problemas.append(f"Campo {nome!r} não foi mapeado na receita.")
        elif not _seletor_valido(regra.get("seletor")):
            # Seletor inválido é um defeito distinto de "preenche 0%". Em
            # `_extrair_campos`, um seletor CSS malformado cai num `except Exception`
            # e o campo sai `None`, indistinguível de um seletor correto que não achou
            # nada. Sem esta distinção, o LLM receberia "campo 0% preenchido" e
            # procuraria outro elemento quando o defeito é de sintaxe. Um diagnóstico
            # errado leva o reparo na direção errada.
            problemas.append(
                f"Campo {nome!r}: o seletor {regra.get('seletor')!r} é CSS INVÁLIDO — "
                "não chegou a ser aplicado. Reescreva o seletor com sintaxe válida "
                "(o problema é de sintaxe, não de o elemento não existir na página)."
            )
        elif medida["taxa"] >= TAXA_CAMPO_RUIM:
            # Caso detectado pela validação de tipo/faixa: o seletor encontra algo, mas
            # o que encontra não serve. É um defeito diferente de "não achou nada", e o
            # LLM precisa saber a diferença para não consertar o problema errado.
            problemas.append(
                f"Campo {nome!r}: o seletor {regra.get('seletor')!r} "
                f"(origem={regra.get('origem')}) PREENCHE {medida['taxa']:.0%} dos itens, mas só "
                f"{taxa_valida:.0%} dos valores são um {medida.get('tipo')!r} válido. Ele está "
                "pegando o elemento ERRADO — provavelmente um vizinho parecido. Aponte para o "
                "elemento que contém de fato esse dado."
            )
        else:
            problemas.append(
                f"Campo {nome!r} preenchido em apenas {medida['taxa']:.0%} dos itens — "
                f"o seletor {regra.get('seletor')!r} (origem={regra.get('origem')}) está errado "
                "ou aponta para um elemento que não existe na maioria dos itens."
            )
    return problemas


PROMPT_REPARO = """Você é o Supervisor de um sistema de extração de dados de e-commerce.
Uma receita de seletores CSS foi aplicada na página e MEDIDA por código determinístico.
O relatório de defeitos abaixo é factual — não discuta, corrija.

Regras (as mesmas do Analista):
1. Responda SOMENTE com o objeto JSON da receita corrigida, sem texto fora dele.
2. NUNCA retorne valores extraídos da página — apenas seletores.
3. Mantenha o que já funciona; mude só o necessário para sanar os defeitos.
4. Só use o combinador de filho direto ">" se o elemento for filho IMEDIATO;
   na dúvida use descendente (espaço).
5. Se houver vitrines/carrosséis, "seletor_grupo" é o CONTÊINER da vitrine (o
   elemento que contém os produtos), nunca o título; "campos_grupo" traz os campos
   do grupo; e "seletor_item" é procurado DENTRO do grupo."""


def _pedir_reparo(
    html: str,
    receita: dict,
    campos: list[dict],
    problemas: list[str],
    url: str,
    tentativa: int | None = None,
) -> dict:
    lista_campos = "\n".join(f"- {c['nome']}: {c.get('descricao', '')}" for c in campos)
    html_limpo = analista_estrutura.limpar_html(html)
    pedido = (
        f"Página: {url}\n\nCampos desejados (um valor por produto):\n{lista_campos}\n\n"
        f"Receita atual (com defeito):\n{json.dumps(receita, ensure_ascii=False, indent=2)}\n\n"
        f"Defeitos medidos por código determinístico:\n" + "\n".join(f"- {p}" for p in problemas) + "\n\n"
        f"HTML (limpo e truncado):\n{html_limpo}"
    )
    proposta = analista_estrutura._chamar_llm(
        [{"role": "system", "content": PROMPT_REPARO}, {"role": "user", "content": pedido}],
        contexto="supervisor",
        extra={"url": url, "tentativa": tentativa, "chars_html_enviado": len(html_limpo)},
    )
    proposta["_meta"] = {**(receita.get("_meta") or {}), "agente": "supervisor", "reparo": True}
    return proposta


def paginas_de_referencia(receita: dict | None) -> list[str]:
    """As outras páginas do domínio contra as quais um reparo é conferido.

    Declaradas na própria receita (`_meta.paginas_validacao`): são dado, não código,
    no mesmo padrão da `tcc_seeds` e da `tcc_amazon_vitrines`.
    """
    return list(((receita or {}).get("_meta") or {}).get("paginas_validacao") or [])


def _htmls_de_referencia(urls: list[str], buscar_html) -> tuple[dict, list[str]]:
    """Baixa as páginas de referência uma única vez. Página que não carrega é
    registrada e ignorada: bloquear o reparo por uma fonte fora do ar trocaria um
    problema real (receita quebrada) por outro (nada coletado)."""
    htmls, falhas = {}, []
    for u in urls:
        try:
            htmls[u] = buscar_html(u)
        except Exception as exc:  # noqa: BLE001  # qualquer falha aqui significa "não foi possível conferir"
            falhas.append(f"{u}: {type(exc).__name__}")
    return htmls, falhas


def reparar(
    html: str,
    receita: dict,
    campos: list[dict],
    url: str,
    max_tentativas: int = MAX_TENTATIVAS_PADRAO,
    buscar_html=None,
) -> dict:
    """Ciclo medir, diagnosticar, repropor, medir. Fica com a melhor receita.

    Retorna {"receita", "validacao", "pontuacao", "tentativas", "historico",
    "custo", "custo_chamadas", "validacao_multipagina"}. A receita devolvida nunca é
    pior que a de entrada: a troca só acontece se a pontuação subir (decisão do
    código, não do LLM).

    Validação multi-página (desde 23/07/2026). A receita é uma por domínio, e medir
    só a página que falhou permite sobreajuste. Caso observado em produção: ao
    reparar a vitrine Games e Consoles da Amazon (`titulo` em 18%), o Agente 4
    acertou o diagnóstico e reparou sozinho (0,816 para 0,944) com um `line-clamp-1`
    fixo, sobreajustado àquela página. Nas outras cinco vitrines testadas em
    seguida, a nota foi de 0,00 a 0,06: o reparo consertaria uma vitrine e
    quebraria vinte e uma. Na rodada seguinte a régua reprovaria as outras e o
    reparo oscilaria entre os dois layouts, gastando LLM a cada ciclo.

    Por isso, uma candidata só é aceita se, além de melhorar na página do reparo,
    não regredir em nenhuma página de referência do domínio (declaradas em
    `_meta.paginas_validacao`). É o mesmo princípio do restante do projeto (quem
    decide é a comparação numérica, não o LLM) aplicado ao escopo da receita, que
    é o domínio.
    """
    buscar_html = buscar_html or _buscar_html_padrao
    referencias = paginas_de_referencia(receita)
    htmls_ref, falhas_ref = _htmls_de_referencia(referencias, buscar_html) if referencias else ({}, [])

    def _notas_referencia(rec: dict) -> dict:
        return {
            u: pontuar(analista_estrutura.validar_receita(analista_estrutura.aplicar_receita(h, rec), campos))
            for u, h in htmls_ref.items()
        }

    melhor = receita
    melhor_val = analista_estrutura.validar_receita(analista_estrutura.aplicar_receita(html, receita), campos)
    melhor_nota = pontuar(melhor_val)
    melhor_ref = _notas_referencia(melhor)
    historico = [{"tentativa": 0, "pontuacao": melhor_nota, "problemas": diagnosticar(receita, melhor_val)}]

    # A sessão de custo envolve o laço inteiro: o custo de um reparo é a soma de
    # todas as tentativas, inclusive as recusadas, que custam o mesmo (desde 29/07/2026).
    with custo_llm.sessao() as chamadas_llm:
        for tentativa in range(1, max_tentativas + 1):
            problemas = diagnosticar(melhor, melhor_val)
            if not problemas:
                break
            candidata = _pedir_reparo(html, melhor, campos, problemas, url, tentativa)
            val = analista_estrutura.validar_receita(analista_estrutura.aplicar_receita(html, candidata), campos)
            nota = pontuar(val)

            # Proteção contra sobreajuste: melhorar aqui não pode piorar as outras páginas.
            notas_cand = _notas_referencia(candidata)
            regressoes = {
                u: (round(melhor_ref[u], 3), round(n, 3))
                for u, n in notas_cand.items()
                if n < melhor_ref[u] - 1e-9
            }

            aceita = nota > melhor_nota and not regressoes
            registro = {
                "tentativa": tentativa,
                "pontuacao": nota,
                "problemas": diagnosticar(candidata, val),
                "aceita": aceita,
            }
            if regressoes:
                registro["regressao_em_referencia"] = regressoes
            historico.append(registro)

            if aceita:
                melhor, melhor_val, melhor_nota, melhor_ref = candidata, val, nota, notas_cand

    return {
        "receita": melhor,
        "validacao": melhor_val,
        "pontuacao": melhor_nota,
        "tentativas": len(historico) - 1,
        "historico": historico,
        "custo": custo_llm.somar(chamadas_llm),
        "custo_chamadas": list(chamadas_llm),
        "validacao_multipagina": {
            "paginas": referencias,
            "conferidas": sorted(htmls_ref),
            "nao_carregaram": falhas_ref,
            "notas_da_receita_final": {u: round(n, 3) for u, n in melhor_ref.items()},
        },
    }

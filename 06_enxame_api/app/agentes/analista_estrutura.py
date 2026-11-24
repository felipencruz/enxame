"""Agente 2: Analista de Estrutura (o primeiro agente com LLM).

Recebe o HTML de uma página e propõe uma receita de extração: seletores CSS
para cada campo desejado. Princípio central do projeto: o LLM propõe
seletores, nunca valores. Quem extrai é `aplicar_receita` (código
determinístico), o que elimina o risco de valores alucinados.

Este módulo também contém a régua do Agente 3 (Extrator e Validador):
`aplicar_receita`, `validar_receita` e `aprovada`.

Formato da receita (JSON):
{
  "seletor_item": "li.produto",            # repete um por produto na página
  "campos": {
    "titulo": {"seletor": "h2.nome", "origem": "texto"},
    "link":   {"seletor": "a.link",  "origem": "atributo", "atributo": "href"}
  }
}

Grupos (opcional), para páginas organizadas em vitrines ou carrosséis por categoria:
{
  "seletor_grupo": "div.carrossel",        # cada grupo = uma categoria
  "campos_grupo": {                        # valor comum a todos os itens do grupo
    "categoria": {"seletor": "h2.titulo", "origem": "texto"}
  },
  "seletor_item": "li.produto",            # buscado dentro de cada grupo
  "campos": { ... }
}
Motivo: na Amazon o rank reinicia a cada carrossel (#1 de Cozinha, #1 de
Moda...), então "#1" só tem sentido junto da categoria, e o Score do Enxame é
normalizado por categoria. Sem grupo, a categoria fica fora do alcance: o
seletor de um campo é relativo ao item, e a categoria está acima do item, no
carrossel. Receita sem `seletor_grupo` é aplicada item a item na página toda.
"""

import json
import re
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup

from app import config, custo_llm

MAX_CHARS_HTML = 120_000  # HTML limpo que cabe com folga no contexto do modelo

PROMPT_SISTEMA = """Você é o Analista de Estrutura de um sistema de extração de dados de e-commerce.
Sua ÚNICA tarefa é analisar o HTML fornecido e propor seletores CSS.

Regras obrigatórias:
1. Responda SOMENTE com um objeto JSON, sem texto fora dele.
2. NUNCA retorne valores extraídos da página (títulos, preços etc.) — apenas seletores.
3. Formato exato da resposta:
   {"seletor_item": "<seletor CSS do elemento que se repete, um por produto>",
    "campos": {"<nome_do_campo>": {"seletor": "<seletor CSS relativo ao item>",
                                    "origem": "texto" | "atributo",
                                    "atributo": "<nome do atributo, se origem=atributo>"}}}
4. Os seletores de campos são RELATIVOS ao elemento do seletor_item.
5. Prefira seletores estáveis (classes semânticas, atributos data-*) a caminhos frágeis (nth-child longos).
6. Se um campo pedido não existir na página, use null no lugar do objeto do campo.
7. Cuidado com a hierarquia: só use o combinador de filho direto ">" se o elemento
   for filho IMEDIATO. Na dúvida, use descendente (espaço), que é mais tolerante.
8. Se o valor de um campo estiver mais completo/limpo em um atributo (ex.: aria-label
   de um link de avaliações) do que no texto visível, prefira origem "atributo".
9. Se a página estiver organizada em vitrines/carrosséis e algum campo pedido
   descrever o GRUPO (ex.: a categoria do carrossel, que vale para todos os produtos
   dentro dele), devolva também:
   "seletor_grupo": "<seletor CSS do carrossel>",
   "campos_grupo": {"<campo>": {"seletor": "<relativo ao grupo>", "origem": "texto"}}
   Nesse caso o seletor_item é buscado DENTRO do grupo, e os campos de grupo NÃO
   devem ser repetidos em "campos"."""


def limpar_html(html: str, max_chars: int = MAX_CHARS_HTML) -> str:
    """Remove o que não interessa à estrutura (scripts, estilos) e trunca."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "iframe", "link", "meta"]):
        tag.decompose()
    limpo = str(soup)
    return limpo[:max_chars]


def _chamar_llm(
    mensagens: list[dict],
    contexto: str = "analista_estrutura",
    extra: dict | None = None,
) -> dict:
    """Único ponto de chamada ao LLM e, desde 29/07/2026, único ponto onde o custo
    é registrado.

    `contexto` identifica quem gastou (`analista_estrutura` na criação,
    `supervisor` no reparo) e `extra` carrega o que só o chamador sabe (a
    tentativa do reparo, o caso da prova controlada). Os dois têm valor padrão e
    são passados por nome de propósito: os testes substituem esta função por um
    lambda, e um parâmetro posicional novo quebraria todos eles.

    O `usage` é lido da resposta e gravado antes do parse do conteúdo: uma chamada
    que volta com JSON inválido consumiu tokens do mesmo jeito, e um log que só
    registra sucesso subestimaria o custo.
    """
    if not config.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY não definida (ver .env do enxame-api)")
    inicio = time.monotonic()
    resposta = httpx.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {config.OPENAI_API_KEY}"},
        json={
            "model": config.OPENAI_MODEL,
            "messages": mensagens,
            "response_format": {"type": "json_object"},
            "temperature": 0,
        },
        timeout=180.0,
    )
    duracao = time.monotonic() - inicio
    resposta.raise_for_status()
    corpo = resposta.json()
    custo_llm.registrar(
        custo_llm.montar_evento(
            contexto=contexto,
            modelo=corpo.get("model") or config.OPENAI_MODEL,
            usage=corpo.get("usage"),
            duracao_s=duracao,
            url=(extra or {}).get("url"),
            extra={k: v for k, v in (extra or {}).items() if k != "url"},
        )
    )
    return json.loads(corpo["choices"][0]["message"]["content"])


def propor_receita(html: str, campos: list[dict], url: str) -> dict:
    """Pede ao LLM uma receita de seletores para os `campos` desejados.

    campos: [{"nome": "titulo", "descricao": "nome do produto"}, ...]
    """
    lista_campos = "\n".join(f"- {c['nome']}: {c.get('descricao', '')}" for c in campos)
    html_limpo = limpar_html(html)
    pedido = (
        f"Página: {url}\n\nCampos desejados (um valor por produto):\n{lista_campos}\n\n"
        f"HTML (limpo e truncado):\n{html_limpo}"
    )
    proposta = _chamar_llm(
        [
            {"role": "system", "content": PROMPT_SISTEMA},
            {"role": "user", "content": pedido},
        ],
        contexto="analista_estrutura",
        extra={"url": url, "chars_html_enviado": len(html_limpo)},
    )
    proposta["_meta"] = {
        "url_origem": url,
        "dominio": urlsplit(url).netloc,
        "modelo": config.OPENAI_MODEL,
        "criado_em": datetime.now(timezone.utc).isoformat(),
        "agente": "analista_estrutura",
        "versao_formato": 1,
        # Guarda o pedido junto da receita: nome e descrição de cada campo.
        # Medido em 15/07: o Analista acerta o layout de departamento da Amazon com
        # pontuação 0,984 quando recebe a descrição dos campos, e 0,167 quando
        # recebe só os nomes. Como a coleta agendada só conhece a receita salva,
        # sem isto o reparo do Agente 4 seria feito sem as descrições.
        "campos_pedidos": [
            {"nome": c["nome"], "descricao": c.get("descricao", ""), "tipo": c.get("tipo")}
            for c in campos
        ],
    }
    return proposta


def _extrair_campos(elemento, campos: dict) -> dict:
    """Aplica um bloco de campos a um elemento, sem LLM e sem propagar exceções."""
    valores = {}
    for nome, regra in (campos or {}).items():
        if not regra:
            valores[nome] = None
            continue
        try:
            alvo = elemento.select_one(regra["seletor"])
        except Exception:
            alvo = None  # seletor CSS inválido proposto pelo LLM: campo vazio
        if alvo is None:
            valores[nome] = None
        elif regra.get("origem") == "atributo":
            valores[nome] = alvo.get(regra.get("atributo", ""))
        else:
            valores[nome] = alvo.get_text(strip=True)
    return valores


def _mesclar(valores_grupo: dict, valores_item: dict) -> dict:
    """Une os valores do grupo com os do item. O item tem precedência, mas um campo
    vazio nunca apaga um valor já medido: se o LLM mapear o mesmo campo nos dois
    níveis (ex.: `categoria` no grupo e no item), o valor real prevalece sobre o None.
    Ausência de valor não é informação."""
    linha = dict(valores_grupo)
    for nome, valor in valores_item.items():
        if valor is not None or nome not in linha:
            linha[nome] = valor
    return linha


def aplicar_receita(html: str, receita: dict) -> list[dict]:
    """Extrai valores aplicando a receita, de forma determinística e sem LLM.

    Com `seletor_grupo`, os itens são buscados dentro de cada grupo e os
    `campos_grupo` (ex.: a categoria do carrossel) são replicados em cada linha
    daquele grupo.
    """
    soup = BeautifulSoup(html, "html.parser")
    seletor_item = receita.get("seletor_item")
    seletor_grupo = receita.get("seletor_grupo")

    if seletor_grupo:
        linhas = []
        for grupo in soup.select(seletor_grupo):
            valores_grupo = _extrair_campos(grupo, receita.get("campos_grupo"))
            itens = grupo.select(seletor_item) if seletor_item else [grupo]
            for item in itens:
                linhas.append(_mesclar(valores_grupo, _extrair_campos(item, receita.get("campos"))))
        return linhas

    itens = soup.select(seletor_item) if seletor_item else [soup]
    return [_extrair_campos(item, receita.get("campos")) for item in itens]


# --- Agente 3: validação de tipo e faixa --------------------------------------
#
# O que esta validação detecta e o que não detecta:
#   Detecta o seletor que aponta para o elemento errado, o caso comum. Ex.: o campo
#         `nota` casando com o número de avaliações (19.614): é número, mas está
#         fora da faixa 0 a 5. O preenchimento não percebe isso; a faixa percebe.
#   Não detecta valor correto com texto extra colado. O caso da Amazon
#         ("4,8 de 5 estrelas19.614") começa com 4,8 e passaria aqui. Isso exigiria
#         validação de formato, que é mais frágil (muda com o texto do site) e
#         ficou fora do escopo de propósito.

_NUMERO = re.compile(r"-?\d{1,3}(?:\.\d{3})*(?:,\d+)?|-?\d+(?:[.,]\d+)?")


def _primeiro_numero(valor: str) -> float | None:
    """Primeiro número do texto cru, em convenção pt-BR (1.234,56)."""
    m = _NUMERO.search(str(valor))
    if not m:
        return None
    try:
        return float(m.group(0).replace(".", "").replace(",", "."))
    except ValueError:
        return None


def _e_texto(v) -> bool:
    return bool(str(v).strip())


def _e_preco(v) -> bool:
    n = _primeiro_numero(v)
    return n is not None and n > 0


def _e_nota(v) -> bool:
    n = _primeiro_numero(v)
    return n is not None and 0 <= n <= 5


def _e_rank(v) -> bool:
    m = re.match(r"^\s*#\s*(\d+)\s*$", str(v))
    return bool(m) and int(m.group(1)) >= 1


def _e_percentual(v) -> bool:
    n = _primeiro_numero(v)
    return n is not None and 0 <= n <= 100


def _e_url(v) -> bool:
    return str(v).strip().startswith(("http://", "https://", "/"))


VALIDADORES = {
    "texto": _e_texto,
    "preco": _e_preco,
    "nota": _e_nota,
    "rank": _e_rank,
    "percentual": _e_percentual,
    "url": _e_url,
}


def validar_receita(linhas: list[dict], campos: list[dict]) -> dict:
    """Mede a qualidade da receita: quantos itens, % de preenchimento por campo e,
    quando o campo declara um `tipo`, % de valores que passam no tipo/faixa.

    `taxa` (presença) continua sendo reportada, pois é o diagnóstico que distingue
    "o seletor não achou nada" de "achou a coisa errada". Quem decide na régua é a
    `taxa_valida`. Campo sem `tipo` declarado tem `taxa_valida == taxa`.
    """
    total = len(linhas)
    preenchimento = {}
    for c in campos:
        nome = c["nome"]
        tipo = c.get("tipo")
        validador = VALIDADORES.get(tipo) if tipo else None
        preenchidos = sum(1 for l in linhas if l.get(nome))
        validos = (
            sum(1 for l in linhas if l.get(nome) and validador(l[nome]))
            if validador
            else preenchidos
        )
        preenchimento[nome] = {
            "preenchidos": preenchidos,
            "taxa": round(preenchidos / total, 3) if total else 0.0,
            "validos": validos,
            "taxa_valida": round(validos / total, 3) if total else 0.0,
            "tipo": tipo,
        }
    return {"itens_encontrados": total, "campos": preenchimento}


TAXA_CAMPO_RUIM = 0.5  # abaixo disso o campo é defeituoso (mesma régua do Supervisor)

# Campos essenciais: aqueles sem os quais o item não é identificável e que, por isso,
# não podem ser diluídos pela média dos demais. É a forma mais simples de ponderar
# por importância (peso binário), e veio de um defeito real:
#
#   Em 22/07 mediu-se que a vitrine "Games e Consoles" da Amazon vinha com `titulo` em
#   apenas 18% dos itens (o seletor fixava `line-clamp-3` e aqueles cards renderizam o
#   título em `line-clamp-1`). A régua aprovava: com link, rank, preço e avaliação
#   perfeitos, a média dos 5 campos dava 0,82. O Agente 4 não era acionado, e o defeito
#   persistiu por 6 dias: 488 item-dia entraram na análise sem termo, porque o
#   classificador de termos lê o título.
#
# Por que só o `titulo`, e não um piso para todo campo: no Mercado Livre, `preco_antigo`
# e `desconto` são legitimamente esparsos, pois só item com desconto os tem. Isso é
# característica da fonte, não defeito, e um piso genérico reprovaria a receita correta
# do ML. A régua vale para todos os domínios; validar a mudança só na Amazon teria
# quebrado o outro coletor.
#
# Ocupação desses campos no ML, medida contra a Bronze em 04/08/2026 (linhas de erro e
# `item_id` nulo removidos):
#
#   - Média de 73,8% nas 39 rodadas até 22/07, janela em que a regra foi escrita. As
#     receitas versionadas medem 0,707 (13/07) e 0,732 (15/07), uma rodada cada; o
#     número vem da série da Bronze, não das receitas.
#   - Nessa mesma janela, um piso genérico de 0,5 reprovaria 0 de 39 rodadas (a pior
#     é 0,705) e um piso de 0,738 reprovaria 20. O argumento se mantém: o campo é
#     esparso por natureza, e um piso genérico mediria a fonte, não a receita.
#   - Na série inteira (66 rodadas): ocupação geral de 0,730, faixa por rodada de
#     0,662 a 0,810.
#
# A receita pode declarar a sua própria lista em `_meta.campos_essenciais`; sem isso, vale
# este padrão. Margem medida na Amazon: o pior campo de Games e Consoles fica em 0,16 e o
# da segunda vitrine mais fraca em 0,82; o piso de 0,5 fica no meio de uma faixa vazia.
CAMPOS_ESSENCIAIS_PADRAO = ("titulo",)


def campos_essenciais(receita: dict | None = None) -> set[str]:
    """Quais campos não podem ficar abaixo do piso (ver `CAMPOS_ESSENCIAIS_PADRAO`)."""
    declarados = ((receita or {}).get("_meta") or {}).get("campos_essenciais")
    return set(declarados) if declarados else set(CAMPOS_ESSENCIAIS_PADRAO)


def campos_cobraveis(validacao: dict, receita: dict | None = None) -> dict:
    """Os campos pelos quais a receita pode ser cobrada.

    Ficam de fora os que já foram investigados e não existem na fonte, mapeados
    como `null` na receita ou listados em `_meta.campos_ausentes`. Exemplo real:
    `preco` na página geral de mais-vendidos da Amazon, que a fonte não serve a
    quem se identifica como robô. Cobrar por eles reprovaria uma receita correta.
    """
    medidas = (validacao or {}).get("campos", {})
    if not receita:
        return dict(medidas)
    mapeados = {**(receita.get("campos_grupo") or {}), **(receita.get("campos") or {})}
    ausentes = set((receita.get("_meta") or {}).get("campos_ausentes") or {})
    return {
        nome: medida
        for nome, medida in medidas.items()
        if nome not in ausentes and mapeados.get(nome, "nao-mapeado") is not None
    }


def aprovada(validacao: dict, receita: dict | None = None) -> bool:
    """Régua determinística de aceite. A receita só vai a produção se achou itens
    e a média dos campos cobráveis alcança `TAXA_CAMPO_RUIM`, contando apenas os
    valores que passam no tipo/faixa declarado (`taxa_valida`). Campo sem `tipo`
    tem `taxa_valida == taxa`.

    Por que não basta "preencheu ao menos um campo": caso real e reprodutível, no
    layout de departamento da Amazon, em que o Agente 2 acertou o `seletor_item`
    (50 itens) e o `link` (100%) e errou os outros cinco campos (0%). Essa régua
    aprovaria uma receita que coleta só links. Achar 50 itens e ler um campo de
    seis não é extrair.

    Por que não basta o preenchimento: um seletor apontado para o elemento vizinho
    preenche 100% dos itens com o dado errado. O caso típico é `nota` casar com o
    número de avaliações (19.614): é número, parece dado bom, e só a faixa 0 a 5
    revela o erro. Daí a `taxa_valida`.

    Limitações conhecidas:
    - Os campos têm peso binário: essencial ou não. Campo essencial (por padrão o
      `titulo`) abaixo do piso reprova sozinho, desde 22/07 (ver
      `CAMPOS_ESSENCIAIS_PADRAO`). Ponderação mais fina (título vale mais que
      desconto) fica como trabalho futuro.
    - Valida tipo/faixa, não formato: "4,8 de 5 estrelas19.614" (nota certa com o
      número colado) começa com 4,8 e passa. Há teste marcando essa fronteira.
    """
    if not validacao or not validacao.get("itens_encontrados"):
        return False
    # Um item sem `seletor_item` é a página inteira, não um produto.
    # `aplicar_receita` faz `itens = soup.select(seletor_item) if seletor_item else
    # [soup]`: sem seletor, o "item" é o documento todo, e os campos casam em
    # qualquer lugar da página. O resultado é 1 linha com taxas altas, com aparência
    # de receita perfeita. Página legítima de 1 produto continua passando; o que
    # reprova é 1 item e nenhum seletor que o delimite.
    if validacao.get("itens_encontrados") == 1 and receita and not receita.get("seletor_item"):
        return False
    cobraveis = campos_cobraveis(validacao, receita)
    if not cobraveis:
        # Nada a cobrar (todos os campos confirmados ausentes na fonte): o único
        # requisito é que a receita tenha achado itens, e ela achou.
        return True

    # Reprovação direta, que a média não pegaria: o campo declara um tipo, o seletor
    # preenche e nenhum valor passa. Isso não é preenchimento parcial, é seletor
    # apontado para o elemento errado, e a média não deve diluir esse defeito. Com 2
    # campos, um perfeito e um 100% errado, a média daria exatamente 0,5 e a
    # receita passaria no limite.
    for medida in cobraveis.values():
        if medida.get("tipo") and medida["taxa"] > 0 and medida.get("taxa_valida", 0) == 0:
            return False

    # Reprovação direta (desde 22/07): campo essencial abaixo do piso reprova sozinho,
    # sem diluição pela média. Responde ao defeito de Games e Consoles: título em 18%
    # dos itens numa receita cuja média dava 0,82 e passava (ver CAMPOS_ESSENCIAIS_PADRAO,
    # que também explica por que isto não é um piso para todo campo).
    for nome in campos_essenciais(receita):
        medida = cobraveis.get(nome)
        if medida and medida.get("taxa_valida", medida["taxa"]) < TAXA_CAMPO_RUIM:
            return False

    taxas = [c.get("taxa_valida", c["taxa"]) for c in cobraveis.values()]
    return (sum(taxas) / len(taxas)) >= TAXA_CAMPO_RUIM


def salvar_receita(
    receita: dict,
    validacao: dict | None = None,
    reparo: dict | None = None,
    custo: dict | None = None,
) -> str:
    """Versiona a receita em disco (uma pasta por domínio, arquivos datados).

    Quando `validacao` é informada, o veredito da régua fica gravado no `_meta`.
    Receita reprovada também é salva, como registro auditável do que o LLM propôs
    e do motivo da recusa (material de apêndice), mas leva `aprovada: false` e não
    é carregada por `carregar_receita_mais_recente`.

    Os campos `salvo_em` e `reparo_historico` (desde 25/07/2026) garantem que as
    receitas versionadas sejam uma trilha auditável de qual receita gerou qual dado:

    1. `criado_em` é gravado uma única vez, pelo Analista (Agente 2), e o Supervisor
       repara partindo do dicionário existente; a candidata herda o `criado_em` do
       pai. Exemplo: as três receitas de 23/07 da Amazon têm no `_meta` o carimbo
       `2026-07-16T01:36:18`, herdado de `receita_20260716_013618.json`, enquanto o
       nome do arquivo diz `20260723`. `criado_em` continua significando a criação
       pelo Analista; `salvo_em` é o carimbo desta gravação, e a diferença entre os
       dois revela um reparo.

    2. `supervisor.reparar` devolve `historico`, tentativa por tentativa, com
       pontuação, diagnóstico, aceite e as regressões em página de referência que
       motivaram uma recusa. Esse histórico fica em `_meta.reparo_historico` (o
       comentário abaixo explica por que não em `_meta.reparo`) e documenta o
       auto-reparo, por exemplo 0,816 para 0,944 na 2ª tentativa, no caso real de
       23/07.
    """
    receita.setdefault("_meta", {})
    receita["_meta"]["salvo_em"] = datetime.now(timezone.utc).isoformat()

    if validacao is not None:
        receita["_meta"]["validacao"] = validacao
        receita["_meta"]["aprovada"] = aprovada(validacao, receita)

    if reparo is not None:
        # Chave própria, e não `reparo`, de propósito. O `supervisor` grava
        # `_meta.reparo = True` (flag booleano) desde 23/07, e as receitas
        # versionadas carregam esse tipo. Sobrescrever com um dicionário mudaria o
        # tipo de um campo já presente no histórico de artefatos, que é a trilha de
        # auditoria. O flag responde "isto foi um reparo?"; esta chave responde
        # "como foi?".
        receita["_meta"]["reparo_historico"] = {
            "tentativas": reparo.get("tentativas"),
            "pontuacao_final": reparo.get("pontuacao"),
            "pontuacao_inicial": (reparo.get("historico") or [{}])[0].get("pontuacao"),
            "historico": reparo.get("historico"),
            "validacao_multipagina": reparo.get("validacao_multipagina"),
            # O custo não se repete aqui de propósito: ele fica em `_meta.custo_llm`,
            # fonte única do valor dentro do artefato (o mesmo número em dois campos
            # do mesmo arquivo pode divergir na primeira edição). O custo deste
            # reparo é o `custo_llm` desta gravação.
        }

    if custo is not None:
        # Quanto de LLM esta gravação consumiu (desde 29/07/2026). Transforma o
        # princípio "o LLM só entra para criar ou consertar" em número auditável
        # dentro do próprio artefato.
        receita["_meta"]["custo_llm"] = custo

    dominio = receita.get("_meta", {}).get("dominio", "desconhecido").replace(":", "_")
    pasta = config.DIR_RECEITAS / dominio
    pasta.mkdir(parents=True, exist_ok=True)
    carimbo = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    caminho = pasta / f"receita_{carimbo}.json"
    # O carimbo tem resolução de 1 segundo, e duas gravações no mesmo segundo se
    # sobrescreveriam numa pasta que é a trilha de auditoria. Não chegou a ocorrer (o
    # lote de 16/07 saiu com 5 a 11 s entre receitas), mas reparos encadeados aproximam
    # as gravações. O sufixo `_2`, `_3`... em vez de microssegundos no carimbo é
    # deliberado: o padrão `receita_AAAAMMDD_HHMMSS.json` é citado na documentação e
    # nos artefatos versionados, e o `sorted(..., reverse=True)` do carregador continua
    # pegando a mais recente (o sufixo ordena depois do nome base).
    sequencia = 2
    while caminho.exists():
        caminho = pasta / f"receita_{carimbo}_{sequencia}.json"
        sequencia += 1
    caminho.write_text(json.dumps(receita, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(caminho)

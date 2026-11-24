"""Prova do auto-reparo: demonstração controlada, reprodutível e offline.

Motivação (29/07/2026). O título do trabalho inclui "Auto-Reparável". Que o reparo
aconteceu está comprovado: há quatro receitas com `_meta.agente: supervisor`
versionadas. Faltava uma evidência reprodutível de como ele acontece, isto é, a
sequência tentativa a tentativa (medição, diagnóstico, proposta, medição, aceite ou
recusa). Esperar um reparo espontâneo depende de a fonte mudar de leiaute, o que pode
não ocorrer até a defesa.

O que o script faz. Pega a receita que está em produção, quebra um seletor de
propósito (cada quebra imita um defeito já observado) e pede ao Agente 4 que repare
sobre HTML real gravado. Captura o ciclo inteiro: cada tentativa, cada diagnóstico,
cada recusa, a proteção contra sobreajuste e o custo em tokens e em dólar.

O que ele é e o que não é (a distinção também vai no artefato):
- É evidência reprodutível: qualquer pessoa com o repositório e uma chave de API
  pode repetir e conferir.
- Não é reparo espontâneo. Os dois reparos de campo (15/07, 0 para 36 itens; e
  23/07, 0,816 para 0,944) continuam sendo a evidência observacional: ocorreram em
  produção, sem intervenção. São evidências de natureza diferente e complementares.
- A rede só é usada para falar com o LLM. As páginas vêm do disco: nenhuma
  requisição às fontes, nenhum dado novo, nada entra na Bronze.

Nada aqui grava em `receitas/`, que é a pasta de produção.

Uso:
    cd 06_enxame_api
    .venv/Scripts/python prova_auto_reparo.py
    .venv/Scripts/python prova_auto_reparo.py --dominio www.amazon.com.br --caso item_inexistente
    .venv/Scripts/python prova_auto_reparo.py --seco     # não chama o LLM; só mede as quebras
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
API = Path(__file__).resolve().parent
sys.path.insert(0, str(API))

CARIMBO = datetime.now(timezone.utc).strftime("%Y%m%d")
SAIDA_PADRAO = RAIZ / "02_Dados" / "raw" / f"prova_auto_reparo_{CARIMBO}"


# --- As páginas reais gravadas ---------------------------------------------
#
# A do Mercado Livre é de 29/07 (a fonte reabriu em 28/07); as da Amazon são de
# 25/07, do experimento de user-agent. Todas coletadas com o user-agent EnxameBot,
# que declara a identidade do robô.
PAGINAS = {
    "www.amazon.com.br": {
        "url_alvo": "https://www.amazon.com.br/gp/bestsellers/toys/",
        "html_alvo": "02_Dados/raw/experimento_cracha/20260725T032517Z_amazon_toys_EnxameBot.html",
        # Referências do domínio para a proteção contra sobreajuste. O perfil difere do
        # alvo de propósito, para que a conferência não repita a mesma página: uma
        # outra rota de departamento e a rota geral, onde a Amazon omite o preço para
        # o user-agent EnxameBot.
        "referencias": {
            "https://www.amazon.com.br/gp/bestsellers/sports/":
                "02_Dados/raw/experimento_cracha/20260725T032517Z_amazon_sports_EnxameBot.html",
            "https://www.amazon.com.br/gp/bestsellers/":
                "02_Dados/raw/experimento_cracha/20260725T032517Z_amazon_geral_EnxameBot.html",
        },
    },
    "www.mercadolivre.com.br": {
        "url_alvo": "https://www.mercadolivre.com.br/mais-vendidos/",
        "html_alvo": "02_Dados/raw/sonda_reabertura_ml_20260729/"
                     "20260729T020816Z_ml_mais-vendidos_EnxameBot.html",
        # Vazio de propósito: a receita do ML em produção não declara
        # `_meta.paginas_validacao`. A proteção contra sobreajuste é configurada por
        # dado, não por código; onde o dado não existe, ela não roda. O artefato
        # registra esse fato.
        "referencias": {},
    },
}


# --- As provocações ---------------------------------------------------------
#
# Cada uma imita um defeito já observado em produção. Uma quebra inventada mostraria
# que o sistema conserta problemas de laboratório; estas mostram que ele conserta
# defeitos que de fato ocorreram.

def _quebrar_item(receita: dict) -> dict:
    receita["seletor_item"] = ".seletor-que-nao-existe-em-lugar-nenhum"
    return receita


def _quebrar_grupo_no_titulo(receita: dict) -> dict:
    """O erro real do Agente 2 em 14/07 na Amazon: apontar o grupo para o título da
    vitrine em vez do contêiner. A receita foi de 36 itens para 0."""
    titulo_do_grupo = ((receita.get("campos_grupo") or {}).get("categoria") or {}).get("seletor")
    receita["seletor_grupo"] = titulo_do_grupo or "h2"
    return receita


def _quebrar_campo(receita: dict, campo: str) -> dict:
    """Campo essencial que some: o caso de Games e Consoles (23/07), em que o
    `titulo` caiu para 18% e a régua reprovou a receita inteira."""
    alvo = (receita.get("campos") or {}).get(campo)
    if alvo is None:
        raise KeyError(campo)
    alvo["seletor"] = f".{campo}-que-sumiu-do-leiaute"
    return receita


def _quebrar_vizinho(receita: dict, campo: str, vizinho: str) -> dict:
    """O defeito mais difícil de perceber: o seletor encontra algo, mas é o elemento
    errado. Preenchimento alto, valor inválido. É para detectar isto que a régua
    cobra tipo e faixa, e não só presença."""
    alvo = (receita.get("campos") or {}).get(campo)
    if alvo is None:
        raise KeyError(campo)
    alvo["seletor"] = vizinho
    alvo["origem"] = "texto"
    alvo.pop("atributo", None)
    return receita


def _quebrar_item_no_elemento_errado(receita: dict, seletor: str) -> dict:
    """Pior que não casar nada: casar muitos elementos errados. O seletor de item vira
    um elemento interno (o selo de rank, o título do carrossel), então a receita
    "acha" dezenas de itens e não extrai campo nenhum. O diagnóstico do Supervisor é
    outro, porque o defeito é outro."""
    receita["seletor_item"] = seletor
    return receita


CASOS = {
    "www.amazon.com.br": [
        ("item_inexistente",
         "O seletor de item deixa de casar (0 itens). Imita 15/07, quando o reparo "
         "levou a receita de 0 para 36 itens.",
         _quebrar_item),
        ("titulo_sumido",
         "O campo essencial `titulo` aponta para um seletor que não existe mais. "
         "Imita Games e Consoles (23/07): título em 18% e régua reprovando.",
         lambda r: _quebrar_campo(r, "titulo")),
        ("preco_sumido",
         "O campo essencial `preco` some do leiaute.",
         lambda r: _quebrar_campo(r, "preco")),
        ("titulo_no_vizinho",
         "O `titulo` passa a apontar para o PREÇO — preenche muito e vale nada. É o "
         "defeito que só a validação de tipo/faixa enxerga.",
         lambda r: _quebrar_vizinho(r, "titulo", ".p13n-sc-price")),
        ("item_no_elemento_errado",
         "O seletor de item vira o SELO DE RANK: acha dezenas de 'itens' e não extrai "
         "campo nenhum. Defeito diferente de 'não achou nada', e o diagnóstico muda.",
         lambda r: _quebrar_item_no_elemento_errado(r, ".zg-bdg-text")),
    ],
    "www.mercadolivre.com.br": [
        ("grupo_no_titulo",
         "O `seletor_grupo` aponta para o TÍTULO do carrossel em vez do contêiner. É "
         "literalmente o erro de 14/07 que motivou o desenho do Agente 4.",
         _quebrar_grupo_no_titulo),
        ("item_inexistente",
         "O seletor do slide deixa de casar (0 itens).",
         _quebrar_item),
        ("titulo_sumido",
         "O `titulo` do produto some do leiaute.",
         lambda r: _quebrar_campo(r, "titulo")),
        ("preco_sumido",
         "O `preco` some do leiaute.",
         lambda r: _quebrar_campo(r, "preco")),
        ("item_no_elemento_errado",
         "O seletor de slide vira o PREÇO: acha 'itens' que não têm nada dentro.",
         lambda r: _quebrar_item_no_elemento_errado(r, ".dynamic-carousel__price")),
    ],
}


def _sha256(caminho: Path) -> str:
    return hashlib.sha256(caminho.read_bytes()).hexdigest()


def _servidor_offline(mapa: dict[str, Path]):
    """Substitui a rede no Agente 4: as páginas de referência vêm do disco.

    Sem isto, a demonstração dependeria de a fonte estar no ar e servindo o mesmo
    leiaute, e deixaria de ser reprodutível."""

    def buscar_html(url: str) -> str:
        caminho = mapa.get(url)
        if caminho is None:
            raise FileNotFoundError(f"sem HTML gravado para {url}")
        return caminho.read_text(encoding="utf-8", errors="ignore")

    return buscar_html


def rodar_caso(dominio, nome, descricao, sabotagem, contexto, seco, max_tentativas):
    from app import coletor
    from app.agentes import analista_estrutura as ae
    from app.agentes import supervisor

    receita_producao = contexto["receita"]
    html = contexto["html"]
    url = contexto["url_alvo"]
    campos = coletor._campos_da_receita(receita_producao)

    quebrada = sabotagem(copy.deepcopy(receita_producao))

    # A proteção contra sobreajuste roda contra as páginas listadas em
    # `_meta.paginas_validacao`. A receita da Amazon declara `electronics` e
    # `kitchen`, que não estão gravadas aqui; sem a troca abaixo, as duas viram
    # `nao_carregaram` e a candidata é aceita sem conferência. A proteção é
    # fail-open (decisão de 23/07: não travar o reparo por uma página fora do ar),
    # o que significa que, em produção, uma referência indisponível desliga a
    # proteção sem aviso. Aqui as URLs são trocadas pelas que existem em disco, e a
    # troca fica declarada no artefato.
    trocadas = None
    if contexto["referencias"]:
        meta = quebrada.setdefault("_meta", {})
        trocadas = {
            "usadas_no_experimento": list(contexto["referencias"]),
            "declaradas_na_receita_de_producao": list(meta.get("paginas_validacao") or []),
            "por_que": "o guarda só pode ser exercido contra HTML gravado; as páginas "
                       "declaradas em produção não estão salvas no repositório",
        }
        meta["paginas_validacao"] = list(contexto["referencias"])

    val_quebrada = ae.validar_receita(ae.aplicar_receita(html, quebrada), campos)
    nota_quebrada = supervisor.pontuar(val_quebrada)
    aprovada_quebrada = ae.aprovada(val_quebrada, quebrada)
    diagnostico = supervisor.diagnosticar(quebrada, val_quebrada)

    registro = {
        "caso": nome,
        "descricao": descricao,
        "dominio": dominio,
        "url_alvo": url,
        "quebra": {
            "seletor_item": quebrada.get("seletor_item"),
            "seletor_grupo": quebrada.get("seletor_grupo"),
            "campos": {k: v.get("seletor") for k, v in (quebrada.get("campos") or {}).items()},
        },
        "paginas_validacao_do_experimento": trocadas,
        "antes_do_reparo": {
            "pontuacao": nota_quebrada,
            "itens_encontrados": val_quebrada.get("itens_encontrados"),
            "aprovada_pela_regua": aprovada_quebrada,
            "diagnostico_do_supervisor": diagnostico,
        },
    }

    # Trava de validade da demonstração: se a quebra não reprovou, o reparo não seria
    # acionado em produção, e repará-la aqui não teria significado. O caso é
    # registrado como inválido, e não omitido.
    if aprovada_quebrada:
        registro["resultado"] = "quebra_nao_reprovou"
        registro["observacao"] = (
            "A régua APROVOU a receita quebrada: em produção o Agente 4 não seria "
            "acionado. Isto não é falha do reparo — é medida da régua deste domínio."
        )
        return registro

    if seco:
        registro["resultado"] = "seco_sem_llm"
        return registro

    resultado = supervisor.reparar(
        html, quebrada, campos, url,
        max_tentativas=max_tentativas,
        buscar_html=_servidor_offline(contexto["referencias"]),
    )
    final = resultado["receita"]
    registro.update(
        resultado="reparado" if resultado["pontuacao"] > nota_quebrada else "nao_reparado",
        depois_do_reparo={
            "pontuacao": resultado["pontuacao"],
            "itens_encontrados": resultado["validacao"].get("itens_encontrados"),
            "aprovada_pela_regua": ae.aprovada(resultado["validacao"], final),
            "tentativas": resultado["tentativas"],
        },
        historico=resultado["historico"],
        validacao_multipagina=resultado["validacao_multipagina"],
        # A proteção rodou de fato, ou foi pulada por falta de referência carregável?
        # Sem este campo, "aceita" e "aceita sem conferência" ficam indistinguíveis.
        guarda_antisobreajuste_rodou=bool(resultado["validacao_multipagina"]["conferidas"]),
        custo_llm=resultado["custo"],
        chamadas_llm=resultado["custo_chamadas"],
        receita_reparada={k: v for k, v in final.items() if k != "_meta"},
        voltou_ao_seletor_de_producao=_compara_com_producao(final, receita_producao),
        candidatas_recusadas=[h for h in resultado["historico"] if h.get("aceita") is False],
    )
    return registro


def demonstrar_guarda() -> dict:
    """Demonstração da proteção contra sobreajuste, determinística e sem LLM.

    Por que separada e com candidata injetada: a proteção só atua quando uma
    candidata melhora na página que falhou e piora nas de referência. Nos sete
    casos com LLM real isso não ocorreu: todas as recusas foram por não pontuar mais
    alto. Como não se pode contar com o LLM para produzir uma proposta sobreajustada,
    e a proteção é código, ela é demonstrada de forma determinística.

    A candidata não é inventada: são duas receitas reais do repositório. A de
    produção lê as páginas de departamento e dá 0,0 na página geral (a Amazon não
    serve preço ao user-agent EnxameBot ali). A `receita_20260715_031818.json` é o
    oposto: 0,8 na geral e 0,0 em toys e em sports. Propor a de 15/07 como conserto
    da página geral reproduz o padrão do sobreajuste real de 23/07: melhora aqui e
    quebra o domínio.

    O que fica medido: a nota subiria (0,0 para 0,8) e, mesmo assim, a candidata é
    recusada, com as regressões identificadas página a página.
    """
    from app import coletor
    from app.agentes import analista_estrutura as ae
    from app.agentes import supervisor

    dominio = "www.amazon.com.br"
    alvo_url = "https://www.amazon.com.br/gp/bestsellers/"
    alvo_html = RAIZ / PAGINAS[dominio]["referencias"][alvo_url]
    referencias = {
        "https://www.amazon.com.br/gp/bestsellers/toys/":
            RAIZ / PAGINAS[dominio]["html_alvo"],
        "https://www.amazon.com.br/gp/bestsellers/sports/":
            RAIZ / PAGINAS[dominio]["referencias"]["https://www.amazon.com.br/gp/bestsellers/sports/"],
    }
    html = alvo_html.read_text(encoding="utf-8", errors="ignore")

    atual = copy.deepcopy(coletor.carregar_receita_mais_recente(dominio))
    campos = coletor._campos_da_receita(atual)
    atual.setdefault("_meta", {})["paginas_validacao"] = list(referencias)

    caminho_candidata = (API / "receitas" / dominio / "receita_20260715_031818.json")
    candidata_real = json.loads(caminho_candidata.read_text(encoding="utf-8"))
    candidata = {k: copy.deepcopy(v) for k, v in candidata_real.items() if k != "_meta"}

    original = ae._chamar_llm
    ae._chamar_llm = lambda mensagens, **kw: copy.deepcopy(candidata)
    try:
        resultado = supervisor.reparar(
            html, atual, campos, alvo_url,
            max_tentativas=1,
            buscar_html=_servidor_offline(referencias),
        )
    finally:
        ae._chamar_llm = original

    nota_candidata = supervisor.pontuar(
        ae.validar_receita(ae.aplicar_receita(html, candidata), campos)
    )
    # Quatro desfechos distintos, que precisam ser separados. O mais sutil é o vazio:
    # quando `reparar` não acha problema na página do alvo, sai do laço sem nenhuma
    # tentativa (o `break` em `supervisor.reparar`) e o histórico fica com uma única
    # entrada. Nesse caso `tentativa.get("aceita")` também é falsy; sem a separação
    # abaixo, uma demonstração que nunca exercitou a proteção reportaria "recusada",
    # exatamente o veredito que ela existe para produzir. Hoje o caso é latente (a
    # receita de produção dá 0,0 na página geral, então sempre há problema a
    # diagnosticar), mas bastaria a Amazon voltar a servir preço ao user-agent
    # EnxameBot ali, como o ML fez em 28/07, para ele ocorrer.
    nota_atual = resultado["historico"][0]["pontuacao"]
    tentativa = resultado["historico"][1] if len(resultado["historico"]) > 1 else None
    regressoes = (tentativa or {}).get("regressao_em_referencia")

    if tentativa is None:
        decisao = "NAO_DEMONSTRADO"
        por_que = ("a candidata nunca chegou a ser avaliada: não havia problema a "
                   "diagnosticar na página do alvo, então o laço de reparo saiu sem "
                   "tentativa. ESTE ARTEFATO NÃO SUSTENTA O ACHADO — refazer com uma "
                   "página em que a receita atual falhe.")
    elif tentativa.get("aceita"):
        decisao = "aceita"
        por_que = ("a candidata pontuou mais alto e não regrediu em nenhuma página de "
                   "referência — o guarda rodou e deixou passar")
    elif regressoes:
        decisao = "RECUSADA_PELO_GUARDA"
        por_que = "a candidata regrediu em página de referência do domínio"
    else:
        decisao = "RECUSADA_POR_NAO_PONTUAR"
        por_que = ("a candidata não pontuou mais alto na própria página do reparo — a "
                   "recusa é do critério numérico, e o guarda não chegou a decidir nada")

    return {
        "o_que_demonstra": "que uma candidata que MELHORA na página do reparo pode ser "
                           "recusada por regredir nas páginas de referência do domínio",
        "origem_da_candidata": (
            f"receita versionada {caminho_candidata.name} — NÃO veio do LLM nesta "
            "execução; foi injetada de propósito (ver docstring de demonstrar_guarda)"
        ),
        "pagina_do_reparo": alvo_url,
        "paginas_de_referencia": list(referencias),
        "nota_da_receita_atual_na_pagina_do_reparo": nota_atual,
        "nota_da_candidata_na_pagina_do_reparo": nota_candidata,
        "decisao": decisao,
        "por_que_essa_decisao": por_que,
        "regressao_em_referencia": regressoes,
        # Frase derivada das notas medidas, e não um literal fixo: o artefato só afirma
        # que a nota sobe quando de fato sobe.
        "sem_o_guarda_teria_sido": (
            "aceita — a nota na página do reparo sobe, e até 23/07 era só isso que se media"
            if nota_candidata > nota_atual else
            f"recusada de qualquer forma — a nota não sobe ({nota_atual} -> "
            f"{nota_candidata}), então esta rodada não isola o efeito do guarda"
        ),
        "receita_final": {k: v for k, v in resultado["receita"].items() if k != "_meta"},
        "custo_llm": {"chamadas": 0, "custo_usd": 0.0,
                      "observacao": "nenhuma chamada de API: a candidata foi injetada"},
    }


def _compara_com_producao(final: dict, producao: dict) -> dict:
    """O reparo devolveu o seletor original, ou achou outro caminho igualmente bom?

    As duas respostas são boas, e são diferentes. Um sistema que só soubesse voltar
    ao que já estava escrito não estaria reparando, estaria lembrando.
    """
    iguais, diferentes = [], {}
    for chave in ("seletor_item", "seletor_grupo"):
        if producao.get(chave) or final.get(chave):
            if final.get(chave) == producao.get(chave):
                iguais.append(chave)
            else:
                diferentes[chave] = {"producao": producao.get(chave), "reparo": final.get(chave)}
    for campo, regra in (producao.get("campos") or {}).items():
        atual = (final.get("campos") or {}).get(campo) or {}
        if atual.get("seletor") == regra.get("seletor"):
            iguais.append(campo)
        else:
            diferentes[campo] = {"producao": regra.get("seletor"), "reparo": atual.get("seletor")}
    return {"identicos": sorted(iguais), "divergentes": diferentes}


def main() -> None:
    parser = argparse.ArgumentParser(description="Prova controlada do auto-reparo")
    parser.add_argument("--saida", default=str(SAIDA_PADRAO))
    parser.add_argument("--dominio", action="append", choices=sorted(PAGINAS))
    parser.add_argument("--caso", action="append")
    parser.add_argument("--max-tentativas", type=int, default=3)
    parser.add_argument("--seco", action="store_true",
                        help="mede as quebras sem chamar o LLM (custo zero)")
    args = parser.parse_args()

    saida = Path(args.saida)
    saida.mkdir(parents=True, exist_ok=True)
    # O log bruto de todas as chamadas desta rodada fica junto do experimento, sem
    # se misturar ao log de produção.
    os.environ["LLM_LOG_PATH"] = str(saida / "llm_uso.jsonl")

    from app import coletor, config, custo_llm

    dominios = args.dominio or sorted(PAGINAS)
    casos_pedidos = set(args.caso or [])

    # Fail-closed: `--caso` não tem `choices` de propósito (os nomes se repetem entre
    # domínios). Sem esta checagem, um nome digitado errado filtraria todos os casos:
    # a rodada sairia vazia, gravaria o relatório, imprimiria "Gravado:" e custaria
    # zero, de forma indistinguível de uma rodada bem-sucedida.
    conhecidos = {nome for dom in dominios for nome, _, _ in CASOS[dom]}
    if casos_pedidos - conhecidos:
        parser.error(
            f"--caso desconhecido para {', '.join(dominios)}: "
            f"{', '.join(sorted(casos_pedidos - conhecidos))}. "
            f"Disponíveis: {', '.join(sorted(conhecidos))}"
        )
    relatorio = {
        "executado_em_utc": datetime.now(timezone.utc).isoformat(),
        "modelo_pedido": config.OPENAI_MODEL,
        "temperatura": 0,
        "max_tentativas": args.max_tentativas,
        "modo": "seco (sem LLM)" if args.seco else "com LLM real",
        "dominios": {},
    }

    for dominio in dominios:
        pagina = PAGINAS[dominio]
        receita = coletor.carregar_receita_mais_recente(dominio)
        if receita is None:
            print(f"[{dominio}] sem receita aprovada — pulado")
            continue
        html_alvo = RAIZ / pagina["html_alvo"]
        referencias = {url: RAIZ / rel for url, rel in pagina["referencias"].items()}
        contexto = {
            "receita": receita,
            "html": html_alvo.read_text(encoding="utf-8", errors="ignore"),
            "url_alvo": pagina["url_alvo"],
            "referencias": referencias,
        }

        bloco = {
            "url_alvo": pagina["url_alvo"],
            "html_alvo": {"arquivo": pagina["html_alvo"], "bytes": html_alvo.stat().st_size,
                          "sha256": _sha256(html_alvo)},
            "paginas_de_referencia": {
                url: {"arquivo": str(caminho.relative_to(RAIZ)).replace("\\", "/"),
                      "sha256": _sha256(caminho)}
                for url, caminho in referencias.items()
            },
            "receita_de_producao": {
                "criado_em": (receita.get("_meta") or {}).get("criado_em"),
                "agente": (receita.get("_meta") or {}).get("agente"),
                "declara_paginas_validacao": bool(
                    (receita.get("_meta") or {}).get("paginas_validacao")),
                "declara_tipos_dos_campos": any(
                    c.get("tipo") for c in ((receita.get("_meta") or {}).get("campos_pedidos") or [])
                ),
            },
            "casos": [],
        }

        print(f"\n=== {dominio} ===")
        for nome, descricao, sabotagem in CASOS[dominio]:
            if casos_pedidos and nome not in casos_pedidos:
                continue
            print(f"  · {nome} ...", end=" ", flush=True)
            try:
                registro = rodar_caso(dominio, nome, descricao, sabotagem, contexto,
                                      args.seco, args.max_tentativas)
            except Exception as erro:  # noqa: BLE001  # um caso com exceção não derruba os outros
                registro = {"caso": nome, "resultado": "erro", "erro": repr(erro)}
            bloco["casos"].append(registro)
            antes = (registro.get("antes_do_reparo") or {}).get("pontuacao")
            depois = (registro.get("depois_do_reparo") or {}).get("pontuacao")
            custo = (registro.get("custo_llm") or {}).get("custo_usd")
            print(f"{registro['resultado']} | {antes} -> {depois} | US$ {custo}")

        relatorio["dominios"][dominio] = bloco

    if not args.seco and (not args.dominio or "www.amazon.com.br" in args.dominio):
        print("\n=== demonstração do guarda anti-sobreajuste (sem LLM) ===")
        relatorio["demonstracao_do_guarda"] = demonstrar_guarda()
        print(f"  · candidata {relatorio['demonstracao_do_guarda']['decisao']} | "
              f"regressões: {relatorio['demonstracao_do_guarda']['regressao_em_referencia']}")

    eventos = custo_llm.ler(saida / "llm_uso.jsonl")
    # Dois números diferentes: o log é da pasta (append-only, acumula todas as rodadas
    # do experimento), enquanto o custo desta rodada é só o que ela gastou.
    relatorio["custo_desta_rodada"] = custo_llm.somar(
        [c for dom in relatorio["dominios"].values()
         for caso in dom["casos"] for c in (caso.get("chamadas_llm") or [])]
    )
    relatorio["custo_acumulado_do_log_da_pasta"] = custo_llm.somar(
        [e for e in eventos if not e.get("_ilegivel")]
    )
    relatorio["_leia_me"] = _leia_me(relatorio)

    # Nome com carimbo de data e hora: uma rodada não sobrescreve outra. Cada rodada,
    # inclusive as que falharam, é evidência.
    destino = saida / f"prova_auto_reparo_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    destino.write_text(json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nGravado: {destino}")
    rodada = relatorio["custo_desta_rodada"]
    print(f"Custo desta rodada: US$ {rodada['custo_usd']} em {rodada['chamadas']} "
          f"chamadas ({rodada['tokens_total']} tokens) · acumulado da pasta: "
          f"US$ {relatorio['custo_acumulado_do_log_da_pasta']['custo_usd']}")


def _leia_me(relatorio: dict) -> dict:
    return {
        "o_que_e": "Demonstração controlada do ciclo de auto-reparo: a receita de "
                   "produção é quebrada de propósito e o Agente 4 tenta consertá-la "
                   "sobre HTML real gravado.",
        "por_que_existe": "Que o reparo acontece já estava provado (4 receitas com "
                          "_meta.agente: supervisor no git). COMO ele acontece — "
                          "tentativa a tentativa, com recusa e diagnóstico — só existia "
                          "como anotação, sem artefato (grau C).",
        "o_que_prova": "Que o ciclo medir → diagnosticar → repropor → medir funciona, "
                       "que quem decide é código determinístico (a candidata só entra "
                       "se pontuar mais alto) e quanto isso custa em tokens e dólares.",
        "o_que_nao_prova": "Não é reparo espontâneo. Os dois de campo (15/07 e 23/07) "
                           "seguem sendo a evidência observacional; este é a evidência "
                           "reprodutível. São coisas diferentes e as duas contam.",
        "honestidade_metodologica": [
            "As quebras imitam defeitos que já ocorreram em produção, não defeitos "
            "inventados para o sistema ganhar.",
            "Caso em que a régua APROVA a receita quebrada é registrado como "
            "'quebra_nao_reprovou' — em produção o Agente 4 nem seria acionado.",
            "Nenhuma requisição às fontes: as páginas vêm do disco. A rede só fala com "
            "o LLM.",
            "Nada foi gravado em receitas/ nem no Bronze.",
            "temperature=0, mas o LLM não é garantidamente determinístico: repetir "
            "pode dar outro seletor. O que se repete é o CRITÉRIO, não a proposta.",
            "O campo guarda_antisobreajuste_rodou distingue 'candidata aceita depois "
            "de conferida nas páginas de referência' de 'aceita sem conferência'. O "
            "guarda falha ABERTO por decisão de 23/07 (página de referência fora do "
            "ar não trava o reparo), então essa distinção precisa estar no artefato.",
        ],
        "custo": "O bloco custo_total soma os tokens medidos no `usage` de cada "
                 "resposta. O dólar é derivado da tabela de preços de app/custo_llm.py "
                 "(fonte e data declaradas lá). O log bruto está em llm_uso.jsonl.",
        "como_reproduzir": "cd 06_enxame_api && .venv/Scripts/python prova_auto_reparo.py",
    }


if __name__ == "__main__":
    main()

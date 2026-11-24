"""Sonda do REPARO do Mercado Livre depois da troca de layout.

POR QUE ELA EXISTE
------------------
Em 25/09/2026, entre 06:00 e 12:00 BRT, o ML trocou a marcação da página de mais vendidos
(`dynamic-carousel__*` -> `poly-card` / `sbc-products-carousel`). A receita de produção (v3)
passou a extrair 0 itens, e a régua de volume abortou a coleta SEM acionar o Agente 4, porque
conta os itens pela própria receita (o grupo `.dynamic__carousel` sumiu). Foi pedido o
caminho B — o reparo pelo Agente 4 —, mas com um portão antes de valer: esta sonda roda o
Agente 4 ISOLADO sobre o HTML guardado e devolve a candidata para ser conferida por fora.

O QUE ELA FAZ
-------------
Lê a receita APROVADA mais recente do domínio (a mesma que o coletor carregaria), aplica-a ao
HTML dado, e chama `supervisor.reparar` exatamente como o `coletor` chamaria — mesmos campos,
mesmo número de tentativas. Grava num diretório de saída: a candidata, o histórico do ciclo,
a validação, o custo e uma amostra das linhas extraídas por carrossel.

O QUE ELA NÃO FAZ: não busca a página (usa o HTML dado, que é a prova versionada), não salva
receita no volume, não grava no Bronze. O custo do LLM vai para `LLM_LOG_PATH` — passe um
caminho fora do log de produção, como a prova de 29/07 fez.

Uso, de dentro do container:
    docker exec -e LLM_LOG_PATH=/tmp/reparo_ml/llm_uso.jsonl -w /srv/enxame-api enxame-api \
        python sonda_reparo_layout_ml.py /tmp/ml_layout_novo.html /tmp/reparo_ml

SEGUNDA PASSADA (25/09, passo 1 do plano aprovado por ele): a primeira devolveu a candidata com
`categoria` em 0% — o layout novo não tem título de carrossel legível (os `h2` vêm em espanhol e
DESALINHADOS), e o identificador confiável é o link "Ver mais" de cada carrossel. Dois
argumentos opcionais, e os dois são DADO que o próprio coletor já usa, não atalho:
    --receita-inicial <json>   parte da candidata anterior ("mantenha o que já funciona")
    --descricao campo=texto    troca a descrição de um campo, como faria `_meta.campos_pedidos`
A descrição diz ONDE está o dado, nunca o seletor: quem escreve o seletor continua sendo o LLM.
"""

import json
import sys
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

from app import coletor
from app.agentes import analista_estrutura, supervisor

URL = "https://www.mercadolivre.com.br/mais-vendidos/"
DOMINIO = "www.mercadolivre.com.br"


def _sem_rede(url: str) -> str:
    raise RuntimeError(f"a sonda não busca página nenhuma (pedida: {url})")


def main(caminho_html: str, saida: str, receita_inicial: str | None = None,
         descricoes: dict | None = None) -> int:
    html = Path(caminho_html).read_text(encoding="utf-8")
    pasta = Path(saida)
    pasta.mkdir(parents=True, exist_ok=True)

    producao = coletor.carregar_receita_mais_recente(DOMINIO)
    if producao is None:
        print("sem receita aprovada para o domínio")
        return 2
    receita = json.loads(Path(receita_inicial).read_text(encoding="utf-8")) if receita_inicial else producao
    # Os NOMES dos campos saem sempre da receita de PRODUÇÃO: a régua mede o que ela produz.
    campos = coletor._campos_da_receita(producao)
    for campo in campos:
        if descricoes and campo["nome"] in descricoes:
            campo["descricao"] = descricoes[campo["nome"]]
    antes = analista_estrutura.validar_receita(analista_estrutura.aplicar_receita(html, receita), campos)

    resultado = supervisor.reparar(html, receita, campos, URL, buscar_html=_sem_rede)
    candidata = resultado["receita"]
    linhas = analista_estrutura.aplicar_receita(html, candidata)

    amostra = OrderedDict()
    for linha in linhas:
        chave = str(linha.get("categoria"))
        amostra.setdefault(chave, [])
        if len(amostra[chave]) < 3:
            amostra[chave].append(linha)

    relatorio = {
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "html": caminho_html,
        "chars_html": len(html),
        "receita_de_entrada": receita_inicial or (producao.get("_meta") or {}).get("salvo_em"),
        "campos_pedidos": campos,
        "nota_antes": supervisor.pontuar(antes),
        "itens_antes": antes.get("itens_encontrados"),
        "nota_depois": resultado["pontuacao"],
        "aprovada_pela_regua": analista_estrutura.aprovada(resultado["validacao"], candidata),
        "tentativas": resultado["tentativas"],
        "historico": resultado["historico"],
        "validacao": resultado["validacao"],
        "custo": resultado["custo"],
        "validacao_multipagina": resultado["validacao_multipagina"],
        "linhas_por_categoria": {k: sum(1 for l in linhas if str(l.get("categoria")) == k) for k in amostra},
        "amostra": amostra,
    }
    (pasta / "candidata.json").write_text(json.dumps(candidata, ensure_ascii=False, indent=2), encoding="utf-8")
    (pasta / "relatorio.json").write_text(json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: relatorio[k] for k in (
        "nota_antes", "itens_antes", "nota_depois", "aprovada_pela_regua", "tentativas", "custo",
        "linhas_por_categoria")}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    argumentos = sys.argv[1:]
    inicial, descricoes, posicionais = None, {}, []
    while argumentos:
        a = argumentos.pop(0)
        if a == "--receita-inicial":
            inicial = argumentos.pop(0)
        elif a == "--descricao":
            nome, _, texto = argumentos.pop(0).partition("=")
            # `@arquivo`: texto com espaços não atravessa SSH + docker exec intacto.
            descricoes[nome] = Path(texto[1:]).read_text(encoding="utf-8").strip() if texto.startswith("@") else texto
        else:
            posicionais.append(a)
    if len(posicionais) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(posicionais[0], posicionais[1], inicial, descricoes))

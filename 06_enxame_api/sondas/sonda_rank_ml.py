"""Sonda do RANK do Mercado Livre. Read-only, sem LLM, sem gravação.

POR QUE ELA EXISTE
------------------
Pedido de 23/09: o coletor do Mercado Livre passa a GRAVAR o rank, como a Amazon. Hoje a posição
no carrossel é reconstruída pela ordem de inserção do Bronze (`preparar_silver.
posicao_no_carrossel_ml`). Antes de mexer na receita e no coletor, esta sonda mede na página
**de hoje** os dois sinais que a fonte serve em cada slide:

    posicao   o `aria-label="k de M"` do PRÓPRIO slide (`.andes-carousel-snapped__slide`)
              — sem buracos, é a que alimenta o percentil da Silver hoje;
    selo      o texto "Nº MAIS VENDIDO" (`.dynamic-carousel__pill-container--text-best-seller`)
              — o rank DECLARADO pela fonte, equivalente ao `#N` da Amazon, e COM buracos.

E mede o que se mede antes de pôr campo novo numa receita: a nota
da régua (média dos campos) com e sem eles.

O `aria-label` mora no próprio elemento do item, e `aplicar_receita` só busca DESCENDENTES
(`select_one`; `:scope` e seletor vazio não devolvem o próprio elemento — medido em 24/09,
soupsieve 2.8.4). Por isso a `posicao` é lida AQUI, pela sonda, e não pela receita: é o que
diz se vale mudar o código para ler o atributo do próprio item.

O QUE ELA NÃO FAZ: não chama o LLM, não salva receita, não grava no Bronze. Uma requisição
HTTP, passando pelo Agente 1 antes.

Uso, de dentro do container (o 1º argumento, opcional, é onde gravar o HTML medido):
    docker exec -w /srv/enxame-api enxame-api python sonda_rank_ml.py /tmp/ml_rank.html
Localmente, contra um HTML versionado:
    python sondas/sonda_rank_ml.py --arquivo <caminho.html>
"""

import copy
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup

from app import bloqueio, coleta_http, coletor
from app.agentes import analista_estrutura as ae
from app.agentes import conformidade, supervisor

DOMINIO = "www.mercadolivre.com.br"
URL = "https://www.mercadolivre.com.br/mais-vendidos/"
UA = conformidade.USER_AGENT_PADRAO
SELETOR_SELO = ".dynamic-carousel__pill-container--text-best-seller"
_POSICAO = re.compile(r"^\s*(\d+)\s+de\s+(\d+)\s*$")
_SELO = re.compile(r"^\s*(\d+)\s*º")


def _nota(html: str, receita: dict, extra: list[dict] | None = None) -> dict:
    linhas = ae.aplicar_receita(html, receita)
    campos = coletor._campos_da_receita(receita)
    if extra:
        if len(extra) != len(linhas):
            raise ValueError(f"desalinhado: {len(extra)} posições para {len(linhas)} linhas")
        for linha, valores in zip(linhas, extra):
            linha.update(valores)
        campos = campos + [{"nome": k, "descricao": "", "tipo": None} for k in extra[0]]
    validacao = ae.validar_receita(linhas, campos)
    return {
        "itens": validacao["itens_encontrados"],
        "nota": supervisor.pontuar(validacao),
        "aprovada": ae.aprovada(validacao, receita),
        "taxas": {k: v["taxa"] for k, v in validacao["campos"].items()},
    }


def medir(html: str, receita: dict) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    carrosseis, posicoes = [], []
    problemas = {"posicao_ilegivel": 0, "posicao_fora_da_ordem_do_dom": 0, "M_diferente_do_n": 0,
                 "sem_selo": 0, "selo_ilegivel": 0, "selo_nao_crescente": 0, "selo_menor_que_posicao": 0}
    for grupo in soup.select(receita["seletor_grupo"]):
        regra_cat = (receita.get("campos_grupo") or {}).get("categoria") or {}
        cab = grupo.select_one(regra_cat.get("seletor", "h2")) if regra_cat else None
        slides = grupo.select(receita["seletor_item"])
        n = len(slides)
        selos, ks = [], []
        for i, sl in enumerate(slides, start=1):
            rotulo = sl.get("aria-label")
            posicoes.append({"posicao": rotulo})
            m = _POSICAO.match(rotulo or "")
            if not m:
                problemas["posicao_ilegivel"] += 1
                ks.append(None)
            else:
                k, total = int(m.group(1)), int(m.group(2))
                ks.append(k)
                problemas["posicao_fora_da_ordem_do_dom"] += int(k != i)
                problemas["M_diferente_do_n"] += int(total != n)
            t = sl.select_one(SELETOR_SELO)
            if t is None:
                problemas["sem_selo"] += 1
                selos.append(None)
                continue
            ms = _SELO.match(t.get_text(strip=True))
            if not ms:
                problemas["selo_ilegivel"] += 1
                selos.append(None)
            else:
                selos.append(int(ms.group(1)))
        validos = [s for s in selos if s is not None]
        problemas["selo_nao_crescente"] += sum(b <= a for a, b in zip(validos, validos[1:]))
        problemas["selo_menor_que_posicao"] += sum(
            1 for s, k in zip(selos, ks) if s is not None and k is not None and s < k
        )
        carrosseis.append({
            "categoria": cab.get_text(strip=True) if cab else None,
            "n": n,
            "selo_max": max(validos) if validos else None,
            "selo_buracos": (max(validos) - len(validos)) if validos else None,
            "selo_difere_da_posicao": sum(
                1 for s, k in zip(selos, ks) if s is not None and k is not None and s != k
            ),
        })

    com_selo = copy.deepcopy(receita)
    com_selo["campos"]["selo_mais_vendido"] = {"seletor": SELETOR_SELO, "origem": "texto"}
    return {
        "bytes_html": len(html),
        "slides": len(posicoes),
        "carrosseis": carrosseis,
        "problemas": problemas,
        "regua": {
            "producao": _nota(html, receita),
            "+selo": _nota(html, com_selo),
            "+posicao": _nota(html, receita, posicoes),
            "+selo+posicao": _nota(html, com_selo, posicoes),
        },
    }


def main(argv: list[str]) -> int:
    receita = coletor.carregar_receita_mais_recente(DOMINIO)
    if "--arquivo" in argv:
        caminho = Path(argv[argv.index("--arquivo") + 1])
        html = caminho.read_text(encoding="utf-8", errors="replace")
        origem = str(caminho)
    else:
        veredito = conformidade.verificar(URL, UA)
        print(f"Agente 1: {'PERMITIDO' if veredito.permitido else 'NEGADO'} ({veredito.motivo})")
        if not veredito.permitido:
            return 1
        regra = bloqueio.volume_esperado(DOMINIO)
        html = coleta_http.buscar_html(URL, UA, piso_bytes=(regra or {}).get("piso_bytes"))
        origem = f"{URL} ao vivo, {datetime.now(timezone.utc).isoformat()}, crachá {UA}"
        destino = next((a for a in argv if not a.startswith("--")), None)
        if destino:
            Path(destino).write_text(html, encoding="utf-8")
            print(f"HTML gravado em {destino}")
    saida = {"origem": origem, "receita": (receita.get("_meta") or {}).get("criado_em"), **medir(html, receita)}
    print(json.dumps(saida, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

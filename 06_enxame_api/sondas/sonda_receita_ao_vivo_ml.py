"""Sonda: aplica uma receita do Mercado Livre à página AO VIVO, pelo caminho do coletor.

POR QUE ELA EXISTE
------------------
Para ensaiar uma receita nova ANTES de ela ir para o volume. Se a v4 entrasse no volume antes de o
`Achatar Produtos` novo ser publicado, a rodada agendada seguinte gravaria a URL do link "Ver mais"
como categoria. Esta sonda busca a página exatamente como o `coletor` busca (Agente 1, piso de
bytes do domínio) e aplica a receita DADA POR ARQUIVO, sem tocar em `receitas/`.

A saída tem o formato da resposta de `/agentes/coletar` (`linhas`, `validacao`, `aprovada`), para
alimentar o `Achatar Produtos` num workflow temporário sem gravação.

O QUE ELA NÃO FAZ: não chama LLM, não salva receita, não grava no Bronze. Uma requisição à fonte.

Uso, de dentro do container:
    docker exec -w /srv/enxame-api enxame-api python sonda_receita_ao_vivo_ml.py \
        /tmp/receita_v4.json /tmp/ensaio_v4
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from app import bloqueio, coleta_http, coletor
from app.agentes import analista_estrutura, conformidade

URL = "https://www.mercadolivre.com.br/mais-vendidos/"
DOMINIO = "www.mercadolivre.com.br"


def main(caminho_receita: str, saida: str) -> int:
    receita = json.loads(Path(caminho_receita).read_text(encoding="utf-8"))
    pasta = Path(saida)
    pasta.mkdir(parents=True, exist_ok=True)

    agente = conformidade.USER_AGENT_PADRAO
    veredito = conformidade.verificar(URL, agente)
    if not veredito.permitido:
        print(f"Agente 1 negou: {veredito.motivo}")
        return 3
    volume = bloqueio.volume_esperado(DOMINIO)
    carimbo = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    html = coleta_http.buscar_html(URL, agente, piso_bytes=volume.get("piso_bytes"))
    (pasta / f"{carimbo}_ml_mais-vendidos_EnxameBot.html").write_text(html, encoding="utf-8")

    linhas = analista_estrutura.aplicar_receita(html, receita)
    bloqueio.conferir_volume(URL, len(linhas), volume.get("itens_esperados"), volume.get("piso_fracao", 0.5))
    validacao = analista_estrutura.validar_receita(linhas, coletor._campos_da_receita(receita))
    resposta = {
        "url": URL,
        "linhas": linhas,
        "validacao": validacao,
        "aprovada": analista_estrutura.aprovada(validacao, receita),
        "llm_usado": False,
        "sonda": {"carimbo": carimbo, "chars_html": len(html), "receita": caminho_receita},
    }
    (pasta / "resposta.json").write_text(json.dumps(resposta, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"chars_html": len(html), "itens": len(linhas), "aprovada": resposta["aprovada"],
                      "taxas": {k: v["taxa"] for k, v in validacao["campos"].items()}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1], sys.argv[2]))

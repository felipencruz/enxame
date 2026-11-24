"""Detecção de bloqueio da fonte: separa "a receita quebrou" de "a fonte bloqueou".

O coletor trata "0 itens extraídos" como sinal de que a receita quebrou e
precisa de reparo pelo LLM. Uma página de bloqueio também rende 0 itens, mas ali
a receita está intacta: quem bloqueou foi a fonte. Sem esta distinção, um
bloqueio da Amazon acionaria o reparo sem necessidade (custo de LLM) e poderia
gravar lixo na Bronze. Regra: bloqueio aborta, não repara.

Dois tipos de parada, por motivos diferentes:
- `DesafioAntiBot`: o site interpôs um CAPTCHA. Paramos por razão ética: o
  projeto não resolve CAPTCHA (ver capítulo de ética do TCC). Vira HTTP 451.
- `PaginaBloqueada`: o site não entregou a página real (erro HTTP, página de
  aviso pequena). Paramos por constatação técnica: não há o que extrair. Vira
  HTTP 503.

Marcadores observados em produção (13 e 14/07/2026):
- Mercado Livre via `httpx` puro: página `suspicious-traffic-frontend`; via
  navegador, redireciona para `/captcha/wall`.
- Amazon `www.amazon.com.br/gp/bestsellers/` a partir da máquina local: HTTP 503
  com 1.643 caracteres e título "Amazon.com.br Algo deu errado". A partir do VPS,
  a mesma URL entrega a página real (cerca de 617 KB).

Régua de volume (04/08/2026)
----------------------------
Os testes acima são por marcador, isto é, por um sinal que a fonte emite. Entre
23 e 28/07 o Mercado Livre serviu uma página sem sinal algum: 133.957 caracteres
(26 vezes o limiar universal), `<title>` legítimo "Mais vendidos", nenhum
marcador de desafio e nenhum produto. O `conferir()` aplicado ao HTML gravado
(`02_Dados/raw/sonda_rotas_ml_20260725/`) aprova essa página, e o coletor
acionaria o Agente 4 para reparar uma receita intacta (medição de 31/07).

A régua mede volume de duas formas, porque as fontes falham de modos opostos
(medido sobre a série inteira):
- bytes de HTML: a casca do ML tem 134 KB, contra 514 KB de uma página saudável
  servida ao mesmo user-agent, na mesma URL, quatro dias depois;
- itens extraídos: a Amazon declara a falha (o 503 vira linha de `[ERRO]`), mas
  já devolveu uma vitrine com 1 item de 50 sem erro, e a régua de campos aprovou,
  porque 1 de 1 é 100%.

Os pisos são dado, não código: ficam em `06_enxame_api/receitas/_volume_esperado.json`,
por domínio, com a evidência e a data. Domínio sem linha no arquivo não tem
régua de volume (fail-open declarado), porque um piso para domínio não medido
seria um número sem evidência.

A régua também aborta, não repara, pelo mesmo critério adotado em 23/07, quando
o ML bloqueou: não se aciona o Agente 4 contra uma página que a fonte não
serviu. O reparo continua responsável pelo seu caso: página boa, volume normal,
campos vazios.
"""

import json
import re
from pathlib import Path

from app import config

# Uma vitrine real de e-commerce tem centenas de KB; as páginas de bloqueio/erro
# observadas têm ~1,6 KB. O limiar fica folgado para não confundir as duas.
LIMIAR_HTML_CURTO = 5_000

# A régua de volume fica fora do código, como as vitrines e as sementes.
ARQUIVO_VOLUME = config.DIR_RECEITAS / "_volume_esperado.json"

# CAPTCHA ou interstício anti-bot: parada ética.
MARCADORES_DESAFIO = ("/captcha/", "captcha/wall", "suspicious-traffic")

# A própria fonte anuncia o erro no <title>: parada técnica.
MARCADORES_ERRO_TITULO = ("algo deu errado", "something went wrong", "desculpe")

_TITULO = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


class DesafioAntiBot(Exception):
    """O site respondeu com CAPTCHA/anti-bot. Por política, abortamos aqui (não
    resolvemos CAPTCHA) e o fato é documentado; o fallback (Apify) é acionado
    por decisão humana."""

    def __init__(self, url_final: str):
        super().__init__(f"Bloqueio anti-bot/CAPTCHA detectado (URL final: {url_final})")
        self.url_final = url_final


class PaginaBloqueada(Exception):
    """A fonte não entregou a página real (erro HTTP ou página de aviso). Não é
    receita quebrada: abortar sem acionar o LLM."""

    def __init__(self, url: str, motivo: str):
        super().__init__(f"A fonte não entregou a página ({motivo}) — URL: {url}")
        self.url = url
        self.motivo = motivo


def volume_esperado(dominio: str, arquivo: Path | None = None) -> dict:
    """O que uma página saudável deste domínio entrega. `{}` se não houver medição.

    Devolver `{}` é resposta, não falha: é o fail-open declarado no `_leia_me` do
    próprio arquivo, e domínio não medido não recebe piso. Arquivo ausente ou
    ilegível cai no mesmo caso, de propósito: a régua de volume é uma trava
    adicional e não deve derrubar uma coleta que funciona por causa de um JSON.
    """
    caminho = arquivo or ARQUIVO_VOLUME
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return (dados.get("dominios") or {}).get(dominio, {})


def titulo_da_pagina(html: str) -> str:
    achado = _TITULO.search(html)
    return achado.group(1).strip().lower() if achado else ""


def eh_desafio(url_final: str, html: str) -> bool:
    alvo_url, alvo_html = url_final.lower(), html.lower()
    return any(m in alvo_url or m in alvo_html for m in MARCADORES_DESAFIO)


def conferir(
    url_final: str, html: str, status: int | None = None, piso_bytes: int | None = None
) -> None:
    """Levanta a exceção correspondente se a resposta não for uma página real.

    Ordem importa: o desafio anti-bot é checado primeiro porque é a parada com
    razão ética (451), e não uma mera indisponibilidade.

    `piso_bytes` é a régua de volume do domínio (dado, ver o topo do arquivo).
    Quando informado, vale além do limiar universal; é o que separa a casca de
    134 KB do ML de uma página real. Sem ele, só o limiar universal se aplica.
    """
    if eh_desafio(url_final, html):
        raise DesafioAntiBot(url_final)

    if status is not None and status >= 400:
        raise PaginaBloqueada(url_final, f"HTTP {status}")

    if len(html) < LIMIAR_HTML_CURTO:
        raise PaginaBloqueada(
            url_final, f"página curta demais ({len(html)} caracteres, mínimo {LIMIAR_HTML_CURTO})"
        )

    if piso_bytes is not None and len(html) < piso_bytes:
        raise PaginaBloqueada(
            url_final,
            f"volume de HTML abaixo do piso do domínio ({len(html)} caracteres, "
            f"piso {piso_bytes}) — a fonte serviu casca, não há o que extrair",
        )

    titulo = titulo_da_pagina(html)
    if any(m in titulo for m in MARCADORES_ERRO_TITULO):
        raise PaginaBloqueada(url_final, f"a fonte anunciou erro no título: {titulo!r}")


def piso_de_itens(itens_esperados: int, piso_fracao: float) -> int:
    """O piso absoluto, derivado do esperado e arredondado para baixo.

    Fica numa função própria porque o número aparece em dois lugares (a decisão e
    a mensagem de erro), e duas contas iguais escritas separadas podem divergir.
    """
    return int(itens_esperados * piso_fracao)


def conferir_volume(
    url: str, itens: int, itens_esperados: int | None, piso_fracao: float = 0.5
) -> None:
    """A segunda metade da régua: a página veio inteira, mas quase sem itens.

    Roda depois de aplicar a receita, no coletor, porque é lá que a contagem
    existe. A régua não cabe em `conferir(url, html, status)`, cuja assinatura não
    recebe quantos itens a receita extraiu. A fixture `HTML_PAGINA_REAL` de
    `test_bloqueio.py` (500 divs, título "Mais Vendidos", nenhum marcador) é
    indistinguível da casca do ML pelos critérios do `conferir()`, e o teste
    afirma que ela passa. Isso está correto: o que a distingue não é a página, e
    sim o que se extraiu dela.

    Por que abortar em vez de reparar (as quatro objeções levantadas em 17/07,
    respondidas com medição):
    1. Onde persistir o histórico? Não se persiste: a expectativa é uma constante
       medida, declarada e datada em `receitas/_volume_esperado.json`, e remedir é
       rodar o `auditar_volume_coleta.py`. É o mesmo desenho da régua do buzz.
    2. Um falso positivo acionaria o reparo por LLM? Não: esta régua aborta. O
       custo de um falso positivo é uma rodada perdida (o alerta das 18h detecta),
       não uma chamada de LLM nem lixo na Bronze.
    3. Se a fonte tiver menos conteúdo, o reparo não tem o que consertar e a
       rodada falha sem gravar nada. Continua verdade, e por isso a decisão é
       abortar declarando o motivo, em vez de tentar consertar.
    4. A régua nunca foi testada contra uma queda legítima? Hoje há 868 pares
       (vitrine, rodada) na Amazon e 70 rodadas no ML. A maior queda legítima
       medida é de 2% na Amazon (867 vitrines com 50 itens e uma com 49) e de 4%
       no ML (mínimo 151 contra mediana 158). Com piso em 50% do esperado, a régua
       reprovaria zero rodadas legítimas nos dois domínios; a distância entre o
       piso e o menor valor legítimo é grande (25 contra 49 na Amazon, 78 contra
       151 no ML).

    `itens_esperados = None` desliga a régua para aquele domínio, de propósito.
    """
    if itens_esperados is None:
        return
    piso = piso_de_itens(itens_esperados, piso_fracao)
    if itens < piso:
        raise PaginaBloqueada(
            url,
            f"volume de itens abaixo do piso do domínio ({itens} extraídos, piso {piso}, "
            f"esperado ~{itens_esperados}) — a página veio, o conteúdo não",
        )

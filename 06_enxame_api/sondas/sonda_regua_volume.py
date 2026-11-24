"""Sonda de verificação da RÉGUA DE VOLUME em produção — read-only, sem LLM, sem gravação.

POR QUE ELA EXISTE
------------------
A régua de volume nasceu de medição sobre HTML **gravado**. Instrumento validado só
com material congelado **não está validado**:
a primeira chamada real faz parte do conserto, não do teste depois. Esta sonda é essa
chamada — e ela roda **antes** de a régua valer para uma rodada de verdade.

O QUE ELA FAZ, E O QUE ELA NÃO FAZ
----------------------------------
- Busca a página de cada domínio com o crachá honesto, **passando pelo Agente 1** antes.
- Aplica a receita de produção e mostra o que a régua **decidiria** em cada metade.
- **Não chama o LLM** (não passa pelo caminho de reparo), **não grava no Bronze**
  (quem grava é o n8n) e **não salva receita**. É a "gravação desligada".

Ela imprime o veredito das duas metades separadas — piso de bytes e piso de itens — e,
de quebra, a taxa de preenchimento de cada campo, que é a régua antiga. Um deploy só é
bom se os TRÊS números continuarem os de sempre.

Uso, de dentro do container:
    docker exec -w /srv/enxame-api enxame-api python sonda_regua_volume.py
"""

import sys

from app import bloqueio, coleta_http, coletor
from app.agentes import analista_estrutura as ae
from app.agentes import conformidade

ALVOS = [
    ("www.mercadolivre.com.br", "https://www.mercadolivre.com.br/mais-vendidos/"),
    ("www.amazon.com.br", "https://www.amazon.com.br/gp/bestsellers/toys/"),
]
UA = conformidade.USER_AGENT_PADRAO


def sondar(dominio: str, url: str) -> bool:
    print("=" * 78)
    print(f"{dominio}  ->  {url}")
    regra = bloqueio.volume_esperado(dominio)
    if not regra:
        print("  [!!] SEM RÉGUA DECLARADA — o `_volume_esperado.json` não chegou ao container?")
        return False
    piso_b = regra["piso_bytes"]
    esperado = regra["itens_esperados"]
    piso_i = bloqueio.piso_de_itens(esperado, regra.get("piso_fracao", 0.5))
    print(f"  régua declarada: piso_bytes={piso_b:,} | itens_esperados={esperado} | piso_itens={piso_i}")

    veredito = conformidade.verificar(url, UA)
    print(f"  Agente 1: {'PERMITIDO' if veredito.permitido else 'NEGADO'} ({veredito.motivo})")
    if not veredito.permitido:
        return False

    try:
        html = coleta_http.buscar_html(url, UA, piso_bytes=piso_b)
    except bloqueio.PaginaBloqueada as erro:
        print(f"  [!!] PISO DE BYTES REPROVOU A PÁGINA REAL: {erro.motivo}")
        return False
    print(f"  bytes: {len(html):,}  ({len(html)/piso_b:.1f}x o piso)")

    receita = coletor.carregar_receita_mais_recente(dominio)
    linhas = ae.aplicar_receita(html, receita)
    try:
        bloqueio.conferir_volume(url, len(linhas), esperado, regra.get("piso_fracao", 0.5))
    except bloqueio.PaginaBloqueada as erro:
        print(f"  [!!] PISO DE ITENS REPROVOU A PÁGINA REAL: {erro.motivo}")
        return False
    print(f"  itens: {len(linhas)}  ({len(linhas)/piso_i:.1f}x o piso)")

    campos = coletor._campos_da_receita(receita)
    validacao = ae.validar_receita(linhas, campos)
    taxas = " · ".join(f"{n}={c['taxa']:.2f}" for n, c in validacao["campos"].items())
    print(f"  régua de campos: aprovada={ae.aprovada(validacao, receita)}  |  {taxas}")
    return True


if __name__ == "__main__":
    ok = all([sondar(d, u) for d, u in ALVOS])
    print("=" * 78)
    print("VEREDITO:", "as duas fontes passam a régua nova" if ok else "ALGO REPROVOU: NAO SUBIR")
    sys.exit(0 if ok else 1)

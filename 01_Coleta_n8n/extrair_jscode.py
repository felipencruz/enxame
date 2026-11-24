# -*- coding: utf-8 -*-
"""
Extrai o JavaScript dos Code nodes do n8n para arquivos .js legíveis.

POR QUE ESTE SCRIPT EXISTE
--------------------------
O JavaScript dos coletores é a lógica que produziu **todo o Bronze** do TCC — as
sugestões do Google, o buzz do YouTube, o `sales` da Shopee (a única quantidade de
vendas do projeto) e os agentes de extração do ML e da Amazon. Só que ele vivia
exclusivamente dentro dos backups JSON, como string escapada:

    "jsCode": "const seeds = $input.all()...\\n  try {\\n..."

Nesse formato não dá para ler com conforto, comparar duas versões, nem colar na
monografia sem desescapar `\\n` na mão. E é justamente o código que a banca pode
pedir para ver.

O CONTRATO (importante, e é o que evita criar um problema no lugar de resolver um)
---------------------------------------------------------------------------------
Os `.js` gerados são **artefato derivado, NÃO fonte da verdade**:

    n8n (produção)  →  backup .json  →  [este script]  →  .js legível

Editar o `.js` não muda nada em lugar nenhum. Para alterar um coletor, o caminho
continua sendo o de sempre: rascunho no n8n → teste manual → publicar → reexportar
o backup JSON → rodar este script de novo. Cada arquivo gerado leva um cabeçalho
dizendo isso, para ninguém editar no lugar errado seis meses depois.

O ELO FRACO DA CADEIA (medido em 16/07; este script não o cobre)
----------------------------------------------------------------
A cadeia acima só vale se o backup for fiel à produção, e **nada garante isso**.
Este script confere o backup contra o `jscode/` (avisa sobre órfão); **ninguém
confere o backup contra o n8n**. Em 16/07 o backup do coletor do ML estava 43
minutos atrás da produção — gravava `categoria_pagina: null` (pré-receita v2)
enquanto a produção gravava o valor certo — e o `.js` gerado aqui herdou o erro
por um dia inteiro, com cara de fonte confiável.

Se um `.js` daqui for citado na monografia, **confira antes contra o n8n**
(`get_workflow_details` → comparar o `jsCode` do nó Code). Enquanto essa
verificação não for automática, o cabeçalho "GERADO AUTOMATICAMENTE" garante
que o `.js` reflete o **backup** — não que o backup reflita a **produção**.

USO
---
    python 01_Coleta_n8n/extrair_jscode.py
"""

import json
import re
import unicodedata
from datetime import date
from pathlib import Path

AQUI = Path(__file__).parent
DESTINO = AQUI / "jscode"

# Onde os backups estão (corrigido em 04/08/2026). Até então o script procurava
# `AQUI.glob("workflow_*.json")`, a convenção do export manual. O backup automático
# de 29/07 (`exportar_workflows.py`) grava em `workflows/` com o nome
# `<id>__<nome>.json`, e o glob antigo casava zero arquivos: o script criava a pasta
# vazia e saía com código 0, sem erro visível.
ORIGEM = AQUI / "workflows"
# O manifesto mora na mesma pasta e não é workflow — sem isto ele cairia em `sem_code`.
NAO_E_WORKFLOW = {"manifesto.json"}


def slug(texto: str) -> str:
    """'TCC — [util] Status das Coletas' -> 'tcc-util-status-das-coletas'"""
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    t = re.sub(r"[^\w\s-]", " ", t).strip().lower()
    return re.sub(r"[-\s]+", "-", t).strip("-")


def cabecalho(arquivo_json: str, workflow: str, no: str, wid: str | None) -> str:
    return (
        "// ============================================================================\n"
        "// GERADO AUTOMATICAMENTE — NÃO EDITE ESTE ARQUIVO.\n"
        "//\n"
        f"// Workflow : {workflow}\n"
        f"// Nó       : {no}\n"
        f"// ID n8n   : {wid or '(não registrado no backup)'}\n"
        f"// Origem   : 01_Coleta_n8n/workflows/{arquivo_json}\n"
        f"// Gerado em: {date.today().isoformat()} por extrair_jscode.py\n"
        "//\n"
        "// Este arquivo é uma CÓPIA LEGÍVEL, para leitura, diff e citação na monografia.\n"
        "// A fonte da verdade é o n8n; o backup .json é o espelho dele.\n"
        "// Para mudar o coletor: n8n (rascunho -> teste manual -> publicar) -> reexportar\n"
        "// o .json -> rodar `python 01_Coleta_n8n/extrair_jscode.py` de novo.\n"
        "// ============================================================================\n\n"
    )


def main() -> None:
    if not ORIGEM.is_dir():
        raise SystemExit(
            f"ERRO: nao achei a pasta de backups em {ORIGEM}.\n"
            "Refaça o export antes (exportar_workflows.py): este script lê o backup, não o n8n."
        )
    entradas = [a for a in sorted(ORIGEM.glob("*.json")) if a.name not in NAO_E_WORKFLOW]
    if not entradas:
        # Fail-closed: "nenhum arquivo" e "nenhum Code node" são coisas diferentes, e
        # até 04/08 as duas saíam como "0 arquivo(s)" com código 0.
        raise SystemExit(f"ERRO: nenhum JSON de workflow em {ORIGEM} — nada a extrair.")

    DESTINO.mkdir(exist_ok=True)
    gerados, sem_code = [], []

    for arq in entradas:
        dados = json.loads(arq.read_text(encoding="utf-8"))
        nome_wf = dados.get("name", arq.stem)
        wid = dados.get("workflowIdOrigem") or dados.get("id")
        nos_js = [
            n for n in dados.get("nodes", [])
            if (n.get("parameters") or {}).get("jsCode")
        ]
        if not nos_js:
            sem_code.append(nome_wf)
            continue
        for no in nos_js:
            codigo = no["parameters"]["jsCode"]
            destino = DESTINO / f"{slug(nome_wf)}__{slug(no['name'])}.js"
            destino.write_text(
                cabecalho(arq.name, nome_wf, no["name"], wid) + codigo.rstrip() + "\n",
                encoding="utf-8",
            )
            gerados.append((destino.name, len(codigo.splitlines())))

    print(f"{len(gerados)} arquivo(s) em 01_Coleta_n8n/jscode/\n")
    for nome, linhas in sorted(gerados):
        print(f"  {linhas:>4} linhas  {nome}")
    if sem_code:
        print("\nSem Code node (nada a extrair):")
        for n in sem_code:
            print(f"  - {n}")

    orfaos = [
        f.name for f in DESTINO.glob("*.js")
        if f.name not in {g[0] for g in gerados}
    ]
    if orfaos:
        print("\nAVISO: arquivos .js sem workflow correspondente (nó renomeado ou removido?):")
        for o in orfaos:
            print(f"  - {o}")
        print("  Conferir e apagar à mão — este script não deleta nada.")


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""Backup dos workflows do n8n: do SQLite do VPS para JSON versionado.

POR QUE ESTE SCRIPT EXISTE
--------------------------
O n8n e a fonte da verdade dos workflows, e estes JSON nao sao editados para
reimportar. Eles existem porque workflows, credenciais, historico de execucoes e a
camada Bronze vivem no mesmo `database.sqlite` do servidor: sem uma copia fora
dele, uma perda do banco levaria tudo junto. Os JSON sao copia de seguranca datada
e material de apoio da monografia.

O QUE ESTE SCRIPT EXPORTA
-------------------------
Os workflows do TCC, definidos por `parentFolderId = 'qIpDRrBIJKv95lnd'` (a pasta
"TCC") e `isArchived = 0`. Medido no VPS em 04/08/2026, e o unico filtro que
reproduz exatamente o conjunto do backup versionado de 29/07:

    total no banco ................................ 90
    isArchived = 0 (a instancia inteira) .......... 46
    pasta TCC, incluindo arquivados ............... 20
    pasta TCC + isArchived = 0 .................... 17   <- o recorte certo

(17 em 04/08; 18 a partir de 11/08, com o Alerta de Perda Silenciosa. O total
vivo sai no campo `total_do_tcc` do manifesto.)

Candidatos descartados, com o motivo medido:
  - `projectId` nao discrimina: os 90 workflows da instancia estao no mesmo
    projeto (`yGLnfxeHfaeFNpD1`).
  - `name LIKE 'TCC%'` erra dos dois lados: pega 20 (inclui arquivados) e perde o
    `pliN9f1zwIhClN2M` (Backup diario da camada bronze), que e do TCC e nao tem o
    prefixo.

O filtro `isArchived = 0` deixa de fora, de proposito, os workflows do TCC
arquivados. Eles sao listados a cada execucao no campo
`arquivados_fora_do_backup` do manifesto, para que arquivar nao seja confundido
com perder.

SEGURANCA: O QUE NAO SAI DAQUI
------------------------------
A tabela `credentials_entity` nao e lida. Do workflow sai o campo `credentials` de
cada no, que contem apenas `{id, name}`, um ponteiro, nunca o segredo. Mesmo
assim ha duas varreduras, e qualquer uma delas aborta o export antes de gravar:

  - por NOME de chave (`SUSPEITAS`);
  - por VALOR: o script le os `.env` do servidor e procura cada valor
    literalmente no JSON. Um segredo escrito a mao num `jsCode`, numa URL ou num
    campo de nome inocente escapa da primeira varredura e cai nesta. Nenhum valor
    e impresso: ao achar, o script cita so o NOME da variavel e o workflow.

COMO RODAR (do Windows, com o script copiado para o VPS)
--------------------------------------------------------
    scp -i ~/.ssh/vps_dashboard exportar_workflows.py root@IP:/tmp/
    ssh -i ~/.ssh/vps_dashboard root@IP python3 /tmp/exportar_workflows.py

A saida fica em /tmp/workflows_backup/ no VPS; traga com `scp -r`.

QUAL HASH COMPARAR: `sha256_definicao`
--------------------------------------
O campo `staticData` guarda estado de execucao que o proprio n8n escreve (por
exemplo, `recurrenceRules` do Schedule Trigger). Ele muda sem edicao humana e sem
mover o `updatedAt`. Em 04/08/2026, comparando com o backup de 29/07, 16 de 17
arquivos bateram byte a byte; o 17o (Coletor Amazon) diferia so em
`staticData.recurrenceRules`. Por isso o manifesto traz dois hashes:
  - `sha256` .............. do arquivo inteiro, como esta em disco;
  - `sha256_definicao` .... sem o `staticData`; e este que responde se o
                            workflow foi editado.

LEITURA SEGURA
--------------
O SQLite e aberto em modo read-only (`file:...?mode=ro`), o que e seguro com o n8n
rodando. Copiar o arquivo com `cp` nao e: ha WAL ativo, e a copia crua sai
corrompida. Para copiar o banco, o certo e `sqlite3 .backup`.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone

DB = "/var/lib/docker/volumes/n8n_data/_data/database.sqlite"
SAIDA = "/tmp/workflows_backup"

# O recorte do TCC. Ver o bloco "O QUE ESTE SCRIPT EXPORTA" no topo: medido em
# 04/08/2026, e o unico filtro que reproduz o backup versionado de 29/07.
PASTA_TCC = "qIpDRrBIJKv95lnd"

# Chaves cujo VALOR jamais deveria aparecer num JSON de workflow. Se aparecerem,
# o script aborta antes de gravar: e mais barato investigar do que despoluir git.
SUSPEITAS = re.compile(
    r'"(password|secret|token|apiKey|api_key|accessToken|refreshToken|clientSecret'
    r'|privateKey|sessionToken|authorization)"\s*:\s*"[^"]{8,}"',
    re.IGNORECASE,
)

# Os `.env` do servidor, para a varredura POR VALOR. Nao e a lista de segredos: e
# onde eles moram, e o script so os usa como agulha de busca.
ENVS = ("/docker/n8n/.env", "/docker/enxame-api/.env", "/opt/evolution/.env")

# Valor curto demais gera falso positivo (um "true", um numero de porta). Abaixo
# disto a busca por valor nao paga o ruido.
MIN_SEGREDO = 12

# A FORMA DE UM SEGREDO, julgada pelo VALOR e nao pelo nome da variavel.
# Chave de API e token sao cadeias opacas (base64/hex). Endereco, fuso e e-mail
# podem aparecer num workflow legitimamente.
#
# Medido no VPS em 04/08/2026: a primeira versao disto abortou o export num
# `DOMAIN_NAME`. Os 3 valores de configuracao dos `.env` (DOMAIN_NAME,
# GENERIC_TIMEZONE, SSL_EMAIL) nao sao segredo; os 8 segredos de verdade sao todos
# opacos. O que cai fora desta forma vira aviso, e nao aborto.
FORMA_DE_SEGREDO = re.compile(r"^[A-Za-z0-9+/=_-]{16,}$")

# OS 3 VALORES DE CONFIGURACAO, POR NOME (conserto de 09/09/2026).
#
# A barra esta na classe da FORMA_DE_SEGREDO, e `America/Sao_Paulo` (17 caracteres,
# todos em `[A-Za-z0-9+/=_-]`) casa com ela: o export abortava com
# "o valor da variavel GENERIC_TIMEZONE aparece literalmente". Como o guarda falha
# fechado e o exportador so roda quando chamado, o bloqueio ficou sem ser notado de
# 11/08 a 09/09.
#
# A barra nao sai da regex porque segredo em base64 usa barra. O aborto continua
# valendo para todo valor opaco; a excecao e nominal, fechada e cobre exatamente os
# 3 valores de configuracao dos `.env`. A busca continua sendo pelo VALOR: o nome so
# decide o desfecho quando o valor foi encontrado.
CONFIG_NAO_SEGREDO = ("DOMAIN_NAME", "GENERIC_TIMEZONE", "SSL_EMAIL")


def carregar_segredos() -> dict[str, str]:
    """Le os `.env` e devolve {NOME_DA_VARIAVEL: valor} para buscar POR VALOR.

    O valor nunca e impresso, logado nem gravado: ele so serve de agulha para o
    `in` la embaixo. Uma busca que grava o proprio padrao vaza o segredo que procura.
    """
    segredos: dict[str, str] = {}
    for caminho in ENVS:
        try:
            with open(caminho, encoding="utf-8", errors="replace") as fh:
                conteudo = fh.read()
        except OSError:
            continue  # `.env` que nao existe neste host nao e erro
        for linha in conteudo.splitlines():
            linha = linha.strip()
            if not linha or linha.startswith("#") or "=" not in linha:
                continue
            nome, _, valor = linha.partition("=")
            valor = valor.strip().strip("'\"")
            if len(valor) >= MIN_SEGREDO:
                segredos[nome.strip()] = valor
    return segredos


def conectar(caminho: str) -> sqlite3.Connection:
    """Abre o banco somente para leitura -- nunca escreve, nunca copia o arquivo."""
    if not os.path.exists(caminho):
        sys.exit("ERRO: nao achei o banco em " + caminho)
    return sqlite3.connect("file:" + caminho + "?mode=ro", uri=True)


def colunas(con: sqlite3.Connection, tabela: str) -> list[str]:
    return [linha[1] for linha in con.execute("PRAGMA table_info(" + tabela + ")")]


def medir_data_tables(con: sqlite3.Connection) -> list[dict]:
    """Conta linhas de cada tabela de data table -- e o proxy da cota do painel."""
    achadas = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'data_table_user_%'"
        " ORDER BY name"
    ).fetchall()
    medidas = []
    for (nome,) in achadas:
        try:
            linhas = con.execute("SELECT COUNT(*) FROM '" + nome + "'").fetchone()[0]
        except sqlite3.Error as erro:
            linhas = "erro: " + str(erro)
        medidas.append({"tabela": nome, "linhas": linhas})
    return medidas


def arquivados_do_tcc(con: sqlite3.Connection) -> list[dict]:
    """Os workflows do TCC que o `isArchived = 0` deixa de fora.

    Sem esta lista, "arquivei um workflow" e indistinguivel de "o backup perdeu um
    workflow" para quem abrir a pasta daqui a seis meses. Pega tambem os que
    tenham saido da pasta, casando pelo nome.
    """
    sql = (
        "SELECT id, name, updatedAt FROM workflow_entity "
        "WHERE isArchived = 1 AND (parentFolderId = ? OR name LIKE 'TCC%') "
        "ORDER BY name"
    )
    return [
        {"id": i, "nome": n, "atualizado_em": str(u)}
        for i, n, u in con.execute(sql, (PASTA_TCC,))
    ]


def conferir_vazamento_por_valor(
    texto: str, nome_wf: str, segredos: dict[str, str], avisos: list[str]
) -> None:
    """Procura o segredo pelo VALOR, nunca pelo nome da variavel.

    Dois desfechos, e a diferenca e a FORMA do valor -- nao o nome dele:

    - valor **opaco** (`FORMA_DE_SEGREDO`): ABORTA. E chave de API ou token, e nao
      ha motivo legitimo para estar literal num workflow.
    - valor **nao opaco** (dominio, fuso, e-mail): vira AVISO. Aparecer num
      workflow e esperado; abortar aqui seria o falso positivo que faz alguem
      desligar a varredura -- e varredura desligada nao protege ninguem.

    Nos dois casos so o NOME da variavel e citado. O valor nao entra na mensagem,
    que iria para o terminal, para o historico do shell e para o log de CI.
    """
    for nome_var, valor in segredos.items():
        if valor not in texto:
            continue
        if FORMA_DE_SEGREDO.match(valor) and nome_var not in CONFIG_NAO_SEGREDO:
            sys.exit(
                "ABORTADO: o valor da variavel " + nome_var + " aparece literalmente "
                "no workflow '" + nome_wf + "'. Nada foi gravado. Tire o segredo do "
                "workflow (use credencial do n8n) antes de exportar."
            )
        avisos.append(nome_var + " (valor de configuracao) aparece em '" + nome_wf + "'")


def exportar(con: sqlite3.Connection) -> dict:
    cols = colunas(con, "workflow_entity")
    desejadas = [c for c in ("id", "name", "active", "nodes", "connections", "settings",
                             "staticData", "meta", "pinData", "versionId", "triggerCount",
                             "createdAt", "updatedAt", "isArchived", "description") if c in cols]
    sql = "SELECT " + ", ".join('"' + c + '"' for c in desejadas) + " FROM workflow_entity"
    # O recorte do TCC. Nao e "todos os nao-arquivados": ver o topo do arquivo.
    sql += " WHERE parentFolderId = ?"
    if "isArchived" in cols:
        sql += " AND isArchived = 0"
    sql += " ORDER BY name"

    total_no_vps = con.execute(
        "SELECT COUNT(*) FROM workflow_entity"
        + (" WHERE isArchived = 0" if "isArchived" in cols else "")
    ).fetchone()[0]

    segredos = carregar_segredos()
    avisos: list[str] = []

    os.makedirs(SAIDA, exist_ok=True)
    manifesto = []
    for linha in con.execute(sql, (PASTA_TCC,)):
        wf = dict(zip(desejadas, linha))
        for campo in ("nodes", "connections", "settings", "staticData", "meta", "pinData"):
            if isinstance(wf.get(campo), str) and wf[campo]:
                try:
                    wf[campo] = json.loads(wf[campo])
                except (ValueError, TypeError):
                    pass

        texto = json.dumps(wf, ensure_ascii=True, indent=2, sort_keys=True, default=str)
        vazamento = SUSPEITAS.search(texto)
        if vazamento:
            sys.exit("ABORTADO: possivel segredo em '" + str(wf.get("name")) + "': "
                     + vazamento.group(0)[:60])
        conferir_vazamento_por_valor(texto, str(wf.get("name")), segredos, avisos)

        seguro = re.sub(r"[^A-Za-z0-9]+", "_", str(wf.get("name", "sem_nome"))).strip("_")[:70]
        arquivo = str(wf.get("id")) + "__" + seguro + ".json"
        # O hash e do texto gravado em disco, com o `\n` final. Antes de 05/08/2026 o
        # manifesto guardava o sha256 de `texto` sem o `\n`, e o `sha256sum` de todos os
        # 17 arquivos divergia do manifesto.
        conteudo = texto + "\n"
        with open(os.path.join(SAIDA, arquivo), "w", encoding="utf-8") as fh:
            fh.write(conteudo)

        # `bate_com_vps`: o `versionId` foi relido do banco DEPOIS de gravar. Se
        # alguem publicou uma versao no meio do export, o backup daquele workflow
        # e de um instante que ja passou -- e isso tem de aparecer, nao sumir.
        atual = con.execute(
            "SELECT versionId FROM workflow_entity WHERE id = ?", (wf.get("id"),)
        ).fetchone()
        manifesto.append({
            "arquivo": arquivo,
            "id": wf.get("id"),
            "nome": wf.get("name"),
            "ativo": bool(wf.get("active")),
            "nos": len(wf.get("nodes") or []),
            "versionId": wf.get("versionId"),
            "atualizado_em": str(wf.get("updatedAt")),
            "bate_com_vps": bool(atual and atual[0] == wf.get("versionId")),
            "sha256": hashlib.sha256(conteudo.encode("utf-8")).hexdigest(),
            "sha256_definicao": hashlib.sha256(
                json.dumps({c: v for c, v in wf.items() if c != "staticData"},
                           ensure_ascii=True, indent=2, sort_keys=True,
                           default=str).encode("utf-8")
            ).hexdigest(),
        })

    return {
        "_leia_me": {
            "o_que_e": "Backup dos workflows do n8n do TCC Enxame, lido do SQLite do VPS.",
            "escopo": ("Apenas os workflows do TCC: pasta '" + PASTA_TCC + "' e isArchived = 0. "
                       "A instancia tem outros workflows, fora do TCC, que nao entram "
                       "neste repositorio. O projectId NAO discrimina (os 90 estao no mesmo "
                       "projeto) e o nome tambem nao (o 'Backup diario da camada bronze' e do "
                       "TCC e nao tem o prefixo). Medido em 04/08/2026."),
            "por_que": ("Workflows, credenciais, historico e o Bronze vivem no mesmo "
                        "database.sqlite do servidor; sem uma copia fora dele, uma perda do "
                        "banco levaria tudo junto."),
            "o_que_nao_esta_aqui": ("(1) Segredos: a tabela credentials_entity nao e lida; o campo "
                                    "'credentials' dos nos guarda apenas {id, name}, que e ponteiro. "
                                    "Duas varreduras abortam o export -- uma por NOME de chave e "
                                    "outra pelo VALOR dos .env do servidor. "
                                    "(2) Workflows ARQUIVADOS do TCC: estao listados em "
                                    "'arquivados_fora_do_backup', com id e nome, para que arquivar "
                                    "nao seja o mesmo que perder em silencio."),
            "como_usar": ("Copia de seguranca e apendice da monografia. NAO editar para reimportar: "
                          "o n8n segue sendo a fonte da verdade."),
            "qual_hash_comparar": ("Para saber se alguem MEXEU no workflow, compare "
                                   "'sha256_definicao'. O 'sha256' inclui o campo staticData, que "
                                   "o proprio n8n reescreve (recurrenceRules do Schedule Trigger) "
                                   "sem edicao humana e sem mover o updatedAt -- comparar por ele "
                                   "acusa divergencia onde nao houve mudanca. Medido em 04/08/2026."),
            "reproduzir": "01_Coleta_n8n/exportar_workflows.py, rodado no VPS com python3.",
        },
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "banco": DB,
        "origem": DB,
        "pasta_do_tcc": PASTA_TCC,
        "total_do_tcc": len(manifesto),
        "total_no_vps": total_no_vps,
        "arquivados_fora_do_backup": arquivados_do_tcc(con),
        "avisos_da_varredura_por_valor": avisos,
        "workflows": manifesto,
    }


def main() -> None:
    con = conectar(DB)
    try:
        manifesto = exportar(con)
        manifesto["data_tables_no_momento_do_backup"] = medir_data_tables(con)
    finally:
        con.close()

    with open(os.path.join(SAIDA, "manifesto.json"), "w", encoding="utf-8") as fh:
        json.dump(manifesto, fh, ensure_ascii=True, indent=2, sort_keys=True)

    print("workflows do TCC exportados: " + str(manifesto["total_do_tcc"])
          + "   (a instancia tem " + str(manifesto["total_no_vps"]) + " nao-arquivados)")
    for wf in manifesto["workflows"]:
        print(("  [ativo] " if wf["ativo"] else "  [     ] ") + str(wf["nome"])
              + "  (" + str(wf["nos"]) + " nos)"
              + ("" if wf["bate_com_vps"] else "   <- MUDOU DURANTE O EXPORT"))

    if manifesto["avisos_da_varredura_por_valor"]:
        print("")
        print("avisos da varredura POR VALOR (nao abortam -- valor de configuracao):")
        for aviso in manifesto["avisos_da_varredura_por_valor"]:
            print("  " + aviso)

    fora = manifesto["arquivados_fora_do_backup"]
    print("")
    if fora:
        # Listados para que arquivar nao seja confundido com perder.
        print("workflows do TCC ARQUIVADOS, de proposito fora deste backup: " + str(len(fora)))
        for wf in fora:
            print("  " + str(wf["id"]) + "  " + str(wf["nome"]))
    else:
        print("nenhum workflow do TCC arquivado.")

    print("")
    print("data tables (linhas vivas):")
    for dt in manifesto["data_tables_no_momento_do_backup"]:
        print("  " + dt["tabela"] + ": " + str(dt["linhas"]))


if __name__ == "__main__":
    main()

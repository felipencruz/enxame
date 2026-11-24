"""Guarda no repositório uma cópia do log de custo do LLM de produção.

Por que este script existe
--------------------------
O `logs/llm_uso.jsonl` do container `enxame-api` é o único registro dos tokens e do
custo de cada chamada de LLM feita em produção, e uma chamada que já aconteceu não
pode ser reexecutada. O arquivo fica num volume do VPS, fora do git e fora do backup
do SQLite; um dado que existe em um único lugar não está preservado. Enquanto o
arquivo tinha só a linha da conferência de deploy (29/07), não havia o que perder; a
partir do primeiro reparo em produção, passa a haver.

Regra aplicada (a mesma do HTML das execuções do n8n): linha nova no log de produção
é copiada para `02_Dados/raw/` no mesmo dia. O log corrido do container continua fora
do git (`.gitignore`, bloco "Log corrido de uso do LLM"); o que entra é esta cópia,
com `sha256` no manifesto, porque aqui ela serve de evidência.

O que ele confere, e por que falha explicitamente
-------------------------------------------------
1. O log é só-acréscimo. A cópia anterior tem de ser prefixo do log atual. Se não
   for, o arquivo de produção encolheu ou foi reescrito; o caso típico é um container
   recriado sem o volume `./logs` (o `--build` de 29/07 apagou scripts assim). Seguir
   sem aviso sobrescreveria a única cópia do passado com um log mais curto.
2. Toda linha é JSON e traz `custo_usd` não nulo. Custo nulo aparece quando o modelo
   informado na resposta não casa com a tabela de preços (ver
   `custo_llm.familia_do_modelo`): o log grava a chamada sem custo, e o fail-safe do
   registro esconderia o defeito.

O que ele não faz: não escreve nada no VPS (só `cat` por SSH) e não chama LLM.

Uso (da raiz do projeto, na máquina local de desenvolvimento):
    06_enxame_api/.venv/Scripts/python 06_enxame_api/guardar_log_llm.py
Sai 0 com "sem linha nova" ou "N linha(s) nova(s) guardada(s)"; sai 1 se uma conferência
falhar, sem tocar na cópia existente.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DESTINO = RAIZ / "02_Dados" / "raw" / "llm_uso_producao"
COPIA = DESTINO / "llm_uso.jsonl"
MANIFESTO = DESTINO / "manifesto.json"
# O endereco do servidor fica fora do repositorio: variavel de ambiente ENXAME_SERVIDOR.
SERVIDOR = os.environ.get("ENXAME_SERVIDOR", "<IP_DO_SERVIDOR>")
SSH = ["ssh", "-i", str(Path.home() / ".ssh" / "vps_dashboard"), "root@" + SERVIDOR]
LOG_REMOTO = "/docker/enxame-api/logs/llm_uso.jsonl"

LEIA_ME = {
    "o_que_e": "Cópia do log de custo do LLM de PRODUÇÃO (container enxame-api, volume ./logs), "
    "guardada por 06_enxame_api/guardar_log_llm.py. Uma linha por chamada de LLM.",
    "por_que": "Chamada de LLM que já aconteceu não se reexecuta, e o log de produção vive só no "
    "VPS. Esta cópia é a prova versionada dos tokens e do custo.",
    "invariantes": "O log é só-acréscimo (a cópia anterior é prefixo da atual) e toda linha traz "
    "custo_usd não nulo. O script falha alto se qualquer um cair, sem tocar na cópia.",
    "o_que_nao_prova": "Não prova que TODA chamada foi registrada: prova o que o registrador "
    "gravou. A conferência externa (log × extrato da OpenAI) é outra, feita em 29/07.",
}


def sha256(dado: bytes) -> str:
    return hashlib.sha256(dado).hexdigest()


def conferir_apendice(anterior: bytes, atual: bytes) -> int:
    """Devolve quantas linhas o log ganhou; levanta se ele não for só-acréscimo."""
    if not atual.startswith(anterior):
        raise ValueError(
            f"o log de produção NÃO contém a cópia anterior como prefixo "
            f"({len(anterior)} bytes guardados, {len(atual)} bytes agora): ele encolheu ou foi "
            f"reescrito — container recriado sem o volume ./logs? A cópia existente NÃO foi tocada."
        )
    return atual[len(anterior):].count(b"\n")


def conferir_linhas(atual: bytes) -> int:
    """Levanta em linha que não é JSON ou sem custo; devolve o total de linhas."""
    n = 0
    for i, linha in enumerate(atual.decode("utf-8").splitlines(), 1):
        if not linha.strip():
            continue
        try:
            registro = json.loads(linha)
        except json.JSONDecodeError as erro:
            raise ValueError(f"linha {i} do log não é JSON: {erro}") from erro
        if registro.get("custo_usd") is None:
            raise ValueError(
                f"linha {i} do log sem custo_usd (modelo {registro.get('modelo')!r}): o modelo "
                f"respondido não casou a tabela de preços de app/custo_llm.py."
            )
        n += 1
    return n


def ler_log_remoto() -> bytes:
    resultado = subprocess.run([*SSH, "cat", LOG_REMOTO], capture_output=True, check=True, timeout=60)
    return resultado.stdout


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    atual = ler_log_remoto()
    anterior = COPIA.read_bytes() if COPIA.exists() else b""
    try:
        novas = conferir_apendice(anterior, atual)
        total = conferir_linhas(atual)
    except ValueError as erro:
        print(f"FALHOU: {erro}")
        return 1
    if COPIA.exists() and novas == 0:
        print(f"sem linha nova: {total} linha(s), sha256 {sha256(atual)[:12]}… igual à cópia guardada")
        return 0
    DESTINO.mkdir(parents=True, exist_ok=True)
    COPIA.write_bytes(atual)
    manifesto = {
        "_leia_me": LEIA_ME,
        "copiado_em_utc": datetime.now(timezone.utc).isoformat(),
        "origem": f"{SSH[-1]}:{LOG_REMOTO}",
        "linhas": total,
        "bytes": len(atual),
        "sha256": sha256(atual),
        "linhas_novas_nesta_copia": novas,
    }
    MANIFESTO.write_text(json.dumps(manifesto, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{novas} linha(s) nova(s) guardada(s): {total} no total, sha256 {sha256(atual)[:12]}…")
    return 0


if __name__ == "__main__":
    sys.exit(main())

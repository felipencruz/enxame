"""Guarda no repositório o registro de chamadas do `enxame-api` de produção.

Por que este script existe
--------------------------
O access log do container `enxame-api` é o único lugar em que fica registrada cada
chamada que os coletores fazem à API, com a hora e o status. É ali que aparece cada
recusa da fonte (o `503` de uma vitrine da Amazon, o `503` do HTTP 500 do Mercado
Livre), inclusive as que o retry recupera na 2ª ou 3ª passada e que, por isso, não
chegam à Bronze: a Bronze só guarda o que resta depois das tentativas.

Esse log existe em um único lugar: nasce com o container, é apagado num `--build` ou
`--force-recreate` e não entra no backup do SQLite nem no export do Drive. O que ele
guarda desde a criação do container (05/08/2026 01:39 UTC) só existe lá.

Regra aplicada (a mesma do `guardar_log_llm.py`): o que só existe no servidor é
copiado para `02_Dados/raw/` com `sha256`, e a cópia é só-acréscimo. Entra apenas o
necessário (hora, método, rota e status de cada requisição HTTP), não o log inteiro.

O que ele confere, e por que falha explicitamente
-------------------------------------------------
1. O registro é só-acréscimo. O trecho do container atual já guardado tem de
   reaparecer, idêntico, no log atual. Se não reaparecer, o log foi reescrito, e
   seguir sem aviso sobrescreveria a única cópia do passado.
   A rotação é o caso legítimo semelhante: o container usa `json-file` com no máximo
   3 arquivos de 10 MB, então, se o log passar de cerca de 30 MB, o Docker descarta o
   começo. O log atual passa a começar no meio do trecho guardado, e isso é aceito,
   porque o que saiu do servidor continua na cópia. Exige-se que a sobreposição seja
   idêntica.
2. Container novo não é emendado automaticamente. Se o container foi recriado, o log
   antigo foi perdido inteiro, e o intervalo entre a última linha guardada e a criação
   do container novo é irrecuperável. O script para com código 1 e mostra a lacuna; só
   com `--container-novo` ele acrescenta o trecho novo, e a lacuna fica registrada no
   manifesto. A emenda é uma decisão consciente do operador.
3. Toda linha que parece requisição tem de ser lida. Linha com `HTTP/1.` que o padrão
   não reconhece levanta erro: um formato novo de log (uvicorn atualizado) não pode
   resultar em "nenhuma chamada nova" com código 0.

O que ele não faz
-----------------
- Não escreve nada no VPS (só `docker logs` e `docker inspect` por SSH) e não chama LLM.
- Não identifica o coletor de cada chamada: a linha não traz o domínio. Amazon e
  Mercado Livre se separam pela hora (a Amazon roda às 03:00 e 15:00 UTC; o ML às 03,
  09, 15 e 21 UTC, uma chamada por rodada), e essa separação é feita na análise.
- Não guarda o que não é requisição (início do servidor, avisos, traceback): só conta.

Uso (da raiz do projeto, na máquina local de desenvolvimento):
    06_enxame_api/.venv/Scripts/python 06_enxame_api/guardar_log_chamadas.py
Sai 0 com "sem chamada nova" ou "N chamada(s) nova(s) guardada(s)"; sai 1 se uma
conferência falhar, sem tocar na cópia existente.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DESTINO = RAIZ / "02_Dados" / "raw" / "log_chamadas_enxame_api"
COPIA = DESTINO / "chamadas.csv"
MANIFESTO = DESTINO / "manifesto.json"
# O endereco do servidor fica fora do repositorio: variavel de ambiente ENXAME_SERVIDOR.
SERVIDOR = os.environ.get("ENXAME_SERVIDOR", "<IP_DO_SERVIDOR>")
SSH = ["ssh", "-i", str(Path.home() / ".ssh" / "vps_dashboard"), "root@" + SERVIDOR]
CONTAINER = "enxame-api"
COLUNAS = ["container_criado_em", "momento_utc", "metodo", "rota", "status"]

# `2026-09-30T03:00:47.280468734Z INFO:     172.18.0.6:59584 - "POST /agentes/coletar HTTP/1.1" 503 Service Unavailable`
REQUISICAO = re.compile(
    r'^(?P<momento>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z) INFO:\s+\S+ - '
    r'"(?P<metodo>[A-Z]+) (?P<rota>\S+) HTTP/1\.[01]" (?P<status>\d{3})\b'
)

LEIA_ME = {
    "o_que_e": "Registro de cada requisição HTTP ao enxame-api de PRODUÇÃO (hora UTC, método, "
    "rota, status), extraído do access log do container por 06_enxame_api/guardar_log_chamadas.py. "
    "Uma linha por requisição; container_criado_em separa os containers (o log nasce com cada um).",
    "por_que": "É o único registro de cada recusa da fonte, inclusive as que o retry recupera e que "
    "por isso nunca chegam ao Bronze. O log vive só no container e some num --build.",
    "invariantes": "Só-acréscimo: o trecho guardado reaparece idêntico no log do servidor (a rotação "
    "do json-file pode cortar o começo, e isso se aceita). Container novo só entra com --container-novo, "
    "e o intervalo perdido fica em 'segmentos'. Toda linha de requisição é lida.",
    "o_que_nao_prova": "Não diz de que coletor é a chamada: a linha não traz o domínio, e Amazon e "
    "Mercado Livre se separam pela hora, em análise. Não cobre nada antes de 2026-08-05T01:39 UTC "
    "(criação do container) nem os intervalos de container recriado listados em 'segmentos'.",
}


def sha256(dado: bytes) -> str:
    return hashlib.sha256(dado).hexdigest()


def extrair(log: str, container_criado_em: str) -> tuple[list[tuple[str, ...]], Counter]:
    """Devolve as requisições (na ordem do log) e a contagem das linhas que não são requisição."""
    chamadas: list[tuple[str, ...]] = []
    outras: Counter = Counter()
    for i, linha in enumerate(log.splitlines(), 1):
        if not linha.strip():
            continue
        m = REQUISICAO.match(linha)
        if m:
            chamadas.append((container_criado_em, m["momento"], m["metodo"], m["rota"], m["status"]))
        elif "HTTP/1." in linha:
            raise ValueError(
                f"linha {i} parece requisição e o padrão não a lê — formato novo de log? "
                f"Nada foi gravado. Linha: {linha[:160]!r}"
            )
        else:
            outras[_tipo(linha)] += 1
    return chamadas, outras


def _tipo(linha: str) -> str:
    """Rótulo curto de uma linha que não é requisição (para o manifesto contar, não guardar)."""
    corpo = linha.split(" ", 1)[1] if " " in linha else linha
    return re.sub(r"\[\d+\]|\d+", "N", corpo.strip())[:60]


def mesclar(guardadas: list[tuple[str, ...]], atuais: list[tuple[str, ...]],
            container: str, aceitar_container_novo: bool = False) -> tuple[list[tuple[str, ...]], dict]:
    """Junta a cópia guardada com o log de agora; levanta se o log não for só-acréscimo.

    Devolve (linhas que entram na cópia, resumo). As linhas do container atual que já estão
    guardadas têm de reaparecer idênticas no log atual, a partir do começo do log ou de um
    ponto do meio, se a rotação do json-file descartou o início.
    """
    do_container = [c for c in guardadas if c[0] == container]
    outros = {c[0] for c in guardadas} - {container}

    if not guardadas:
        return list(atuais), {"novas": len(atuais), "cortadas_pela_rotacao": 0, "container_novo": True}

    if not do_container:
        ultimo = guardadas[-1]
        if not aceitar_container_novo:
            raise ValueError(
                f"o container '{CONTAINER}' foi RECRIADO: a cópia termina no container criado em "
                f"{ultimo[0]} (última chamada {ultimo[1]}) e o de agora foi criado em {container}. "
                f"O que o container antigo registrou depois de {ultimo[1]} está PERDIDO. "
                f"Nada foi gravado; rode com --container-novo para acrescentar o trecho novo, e o "
                f"buraco fica escrito no manifesto."
            )
        return guardadas + atuais, {"novas": len(atuais), "cortadas_pela_rotacao": 0,
                                    "container_novo": True,
                                    "lacuna_de": ultimo[1], "lacuna_ate": container}

    if guardadas[-len(do_container):] != do_container:
        raise ValueError(
            f"a cópia tem linhas do container {container} fora do fim do arquivo "
            f"(containers anteriores: {sorted(outros)}) — cópia corrompida? Nada foi gravado."
        )

    if not atuais:
        raise ValueError(
            f"o log de agora não tem NENHUMA requisição, e a cópia tem {len(do_container)} deste "
            f"container — o log foi reescrito ou o comando não leu o container certo. Nada foi gravado."
        )

    # Rotação: o log de agora pode começar no meio do trecho guardado.
    cortadas = 0
    if atuais[0] != do_container[0]:
        try:
            cortadas = do_container.index(atuais[0])
        except ValueError:
            raise ValueError(
                f"a primeira requisição do log de agora ({atuais[0][1]}) não está na cópia deste "
                f"container, que começa em {do_container[0][1]} — o log NÃO é só-acréscimo "
                f"(reescrito, ou rotação que passou do fim da cópia). Nada foi gravado."
            ) from None
    sobreposicao = do_container[cortadas:]
    if atuais[:len(sobreposicao)] != sobreposicao:
        raise ValueError(
            f"o log de agora DIVERGE da cópia no trecho que as duas têm ({len(sobreposicao)} "
            f"requisições desde {sobreposicao[0][1]}) — ele foi reescrito. Nada foi gravado."
        )
    novas = atuais[len(sobreposicao):]
    return guardadas + novas, {"novas": len(novas), "cortadas_pela_rotacao": cortadas,
                               "container_novo": False}


def para_csv(linhas: list[tuple[str, ...]]) -> bytes:
    buf = io.StringIO()
    escritor = csv.writer(buf, lineterminator="\n")
    escritor.writerow(COLUNAS)
    escritor.writerows(linhas)
    return buf.getvalue().encode("utf-8")


def ler_csv(dado: bytes) -> list[tuple[str, ...]]:
    leitor = csv.reader(io.StringIO(dado.decode("utf-8")))
    cabecalho = next(leitor, None)
    if cabecalho is None:
        return []
    if cabecalho != COLUNAS:
        raise ValueError(f"a cópia tem cabeçalho {cabecalho}, esperado {COLUNAS}. Nada foi gravado.")
    return [tuple(linha) for linha in leitor]


def _ssh(comando: str) -> str:
    resultado = subprocess.run([*SSH, comando], capture_output=True, check=True, timeout=120)
    return resultado.stdout.decode("utf-8")


def ler_do_servidor() -> tuple[str, str]:
    """(criação do container, log com carimbo), só leitura. O `2>&1` é remoto: o uvicorn
    escreve parte do log em stderr, e o `docker logs` devolve cada fluxo pelo seu."""
    criado = _ssh(f"docker inspect -f '{{{{.Created}}}}' {CONTAINER}").strip()
    log = _ssh(f"docker logs --timestamps {CONTAINER} 2>&1")
    return criado, log


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    aceitar = "--container-novo" in argv
    criado, log = ler_do_servidor()
    anterior = COPIA.read_bytes() if COPIA.exists() else b""
    manifesto_antigo = json.loads(MANIFESTO.read_text(encoding="utf-8")) if MANIFESTO.exists() else {}
    if anterior and manifesto_antigo.get("sha256") != sha256(anterior):
        print("FALHOU: a cópia em disco não bate com o sha256 do manifesto — ela foi editada "
              "ou convertida (fim de linha?). Nada foi gravado.")
        return 1
    try:
        guardadas = ler_csv(anterior)
        atuais, outras = extrair(log, criado)
        linhas, resumo = mesclar(guardadas, atuais, criado, aceitar)
    except ValueError as erro:
        print(f"FALHOU: {erro}")
        return 1

    if resumo["novas"] == 0 and anterior:
        print(f"sem chamada nova: {len(linhas)} guardada(s), sha256 {sha256(anterior)[:12]}… "
              f"igual; o log do servidor tem {len(atuais)}.")
        return 0

    dado = para_csv(linhas)
    segmentos = manifesto_antigo.get("segmentos", [])
    if resumo["container_novo"]:
        segmentos.append({"container_criado_em": criado,
                          "lacuna_antes": ({"de": resumo["lacuna_de"], "ate": resumo["lacuna_ate"]}
                                           if "lacuna_de" in resumo else None)})
    status = Counter(c[4] for c in linhas)
    DESTINO.mkdir(parents=True, exist_ok=True)
    COPIA.write_bytes(dado)
    manifesto = {
        "_leia_me": LEIA_ME,
        "copiado_em_utc": datetime.now(timezone.utc).isoformat(),
        "origem": f"{SSH[-1]}: docker logs --timestamps {CONTAINER}",
        "segmentos": segmentos,
        "requisicoes": len(linhas),
        "primeira": linhas[0][1] if linhas else None,
        "ultima": linhas[-1][1] if linhas else None,
        "por_status": dict(sorted(status.items())),
        "bytes": len(dado),
        "sha256": sha256(dado),
        "novas_nesta_copia": resumo["novas"],
        "cortadas_pela_rotacao_nesta_copia": resumo["cortadas_pela_rotacao"],
        "linhas_do_log_que_nao_sao_requisicao": dict(outras.most_common()),
    }
    MANIFESTO.write_text(json.dumps(manifesto, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{resumo['novas']} chamada(s) nova(s) guardada(s): {len(linhas)} no total "
          f"({manifesto['primeira']} → {manifesto['ultima']}), sha256 {sha256(dado)[:12]}…")
    if resumo["cortadas_pela_rotacao"]:
        print(f"  (a rotação do json-file já descartou {resumo['cortadas_pela_rotacao']} delas do "
              f"servidor — elas agora só existem nesta cópia)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

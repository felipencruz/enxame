# -*- coding: utf-8 -*-
"""Conferidor dos lotes manuais do Google Trends (`02_Dados/trends/`).

Por que existe. A coleta do Trends é manual e roda em passe único (definido em 02/09):
baixar tudo sem julgar e medir no fim. Este script é a etapa de medir no fim. Sem ele,
a segunda passada exigiria inspecionar 30 gráficos, que é o que o passe único existe
para evitar.

O que ele confere (cada check corresponde a um defeito observado no dado):

1. Configuração: região, categoria e janela. Errar a configuração não produz termo
   esmagado; produz dado silenciosamente errado no lote inteiro (`PLANO_TRENDS.md`).
2. Dia anômalo: dia em que a série inteira zera, ou em que um termo salta acima de
   10× a própria mediana. `16/08/2026` está quebrado na fonte desde a primeira medição.
3. Lote contaminado (check introduzido em 03/09). O Trends divide a série pelo máximo
   do lote. Se o máximo cair num dia anômalo, o lote inteiro é esmagado contra um valor
   que não existe, e os 5 termos se perdem de uma vez, não só o vizinho pequeno.
   Reagrupar por magnitude não resolve: o valor espúrio supera qualquer termo.
4. Resolução por termo: o critério do plano, 12 ou menos valores distintos em 56 dias,
   reprova. Reproduzido aqui de propósito, para o script não criar régua nova.
5. Lote sem série, que tem três causas (07/09). O download solo de 07/09 trouxe 22
   arquivos só com cabeçalho. A fonte responde "não há dados suficientes", e isso é uma
   resposta, não uma falha (confirmado na interface).
   (a) sem o cabeçalho `Dia,`: ilegível, refazer (derruba o script);
   (b) cabeçalho ok e o termo nunca teve série em lote nenhum: limite da fonte, não
   refazer; (c) cabeçalho ok, mas o termo já rendeu série acompanhado: o download solo
   é que não serve para ele, refazer em par. O caso (c) existe porque `bomba de encher
   bola` tinha 9 distintos no `lote01` e voltou vazio sozinho: "um termo sozinho é sempre
   o máximo" vale só para os termos que a fonte aceita exibir.

6. A janela `c` (20/10): a busca nova do experimento 2, de `07/09` a `19/10`, fixada antes
   do download. Arquivo `c` com outra janela reprova (mal configurado), e o resumo informa
   quantos termos com série até 06/09 resolveram nela.

O que ele não confere, declarado explicitamente: se o termo foi pedido como "Termo de
pesquisa" ou como "Tópico". O CSV não carrega essa distinção, só o nome e a região. É o
único item da configuração que depende de conferência manual.

Uso:

    06_enxame_api/.venv/Scripts/python 03_Analise/conferir_trends.py
    06_enxame_api/.venv/Scripts/python 03_Analise/conferir_trends.py <pasta>

Sai com código 1 só quando algum arquivo precisa voltar da fonte: lote contaminado,
mal configurado ou ilegível. Termo esmagado sozinho não derruba o script: é o resultado
esperado do passe único, e a saída correspondente é a lista de refazer. Limite da fonte
também não derruba: nenhum download o resolve, e um auditor que falha sempre deixa de
ser lido.
"""
from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

# O piso é o do `PLANO_TRENDS.md`, não um número novo: 12 distintos em 56 dias.
# Termo abaixo dele perdeu resolução para o vizinho (ou para um dia anômalo) e volta à fila.
PISO_DISTINTOS = 12
DIAS_DA_CALIBRACAO = 56

# Desde 03/09 o piso é uma taxa. A janela encolheu (de 56 dias para 38 + 18, para evitar
# o `16/08`), e um piso absoluto calibrado em 56 dias reprovaria por construção uma janela
# de 18: nenhum termo pode ter 13 valores distintos em 18 observações sem ser quase
# perfeito. Critério de contagem calibrado num tamanho de série muda de significado quando
# o tamanho muda. O piso mínimo de 3 existe porque abaixo disso "distintos" deixa de medir
# resolução.
PISO_MINIMO = 3


def piso_para(n_dias: int) -> int:
    """Piso de valores distintos para uma janela de `n_dias`.

    Invariante: em 56 dias devolve 12, o número definido no `PLANO_TRENDS.md`; para
    janelas de outro tamanho, aplica a mesma taxa.
    """
    return max(PISO_MINIMO, round(PISO_DISTINTOS * n_dias / DIAS_DA_CALIBRACAO))

# Dias em que a fonte não entrega dado. Descobertos por medição, não supostos; o `16/08`
# aparece nos 15 lotes baixados até 03/09. Esta lista é dado: dia novo entra aqui.
# 19, 20 e 21/09 entram com o download da janela `c`: a consulta inteira zera em 16, 22 e
# 17 dos 51 arquivos (os de pouco volume), e os de muito volume seguem normais. Não é
# apagão geral, então nada muda no tratamento: o nulo continua sendo decidido por lote em
# `dias_anomalos()`, regra escrita antes do dado (protocolo §8i).
DIAS_QUEBRADOS_CONHECIDOS = {"2026-07-19", "2026-08-16", "2026-09-19", "2026-09-20", "2026-09-21"}

REGIAO_ESPERADA = "Brasil"
CATEGORIA_ESPERADA = "Todas as categorias"

# A terceira janela (`c`), a busca nova do experimento 2 da H1 (20/10). A data final é
# fixa, escrita antes do download: baixar em dois dias com "hoje" deixaria a pasta com duas
# janelas diferentes (`PLANO_TRENDS.md`). 19/10 é o último dia que a fonte já tinha fechado
# quando a lista foi escrita. Arquivo `c` com outra janela é mal configurado e derruba o
# auditor, para que o erro apareça aqui e não só no experimento.
JANELA_C = ("2026-09-07", "2026-10-19")


def janela_do_lote(nome: str) -> str:
    """`'a'`, `'b'` ou `'c'`, pela letra logo antes de `.csv`.

    A janela precisa ser identificada explicitamente: tratar tudo que não é `b` como `a`
    faria um arquivo `c` ser lido como série de julho e disputar o dono do termo com ela,
    sem aviso. Os lotes sem letra (`01` a `05`, `P1`) são da janela antiga, que conta
    como `a`.
    """
    base = nome[:-4] if nome.endswith(".csv") else nome
    return base[-1] if base and base[-1] in ("b", "c") else "a"


def par_na_janela(nome: str, janela: str) -> str:
    """O arquivo da mesma composição em outra janela: `trends_lote06a.csv` → `..06c.csv`.

    Os lotes antigos não têm letra: `trends_lote01.csv` → `trends_lote01c.csv`.
    """
    base = nome[:-4] if nome.endswith(".csv") else nome
    if base and base[-1] in ("a", "b", "c"):
        base = base[:-1]
    return f"{base}{janela}.csv"


class Lote:
    """Um CSV de lote, já parseado. `valores` guarda a string crua ('<1' é censura)."""

    def __init__(self, caminho: Path):
        self.caminho = caminho
        self.nome = caminho.name
        self.categoria: str | None = None
        self.termos: list[str] = []
        self.regioes: list[str] = []
        self.dias: list[str] = []
        self.valores: dict[str, list[str]] = {}
        self._ler()

    def _ler(self) -> None:
        linhas = self.caminho.read_text(encoding="utf-8-sig").splitlines()
        for linha in linhas:
            if linha.lower().startswith("categoria:"):
                self.categoria = linha.split(":", 1)[1].strip()
        try:
            i = next(k for k, l in enumerate(linhas) if l.startswith("Dia,"))
        except StopIteration:
            return  # arquivo sem série: o próprio relatório trata
        cabecalho = next(csv.reader([linhas[i]]))[1:]
        for coluna in cabecalho:
            # formato: "micro ondas: (Brasil)"
            termo, _, resto = coluna.partition(":")
            self.termos.append(termo.strip())
            self.regioes.append(resto.strip().strip("()").strip())
        self.valores = {t: [] for t in self.termos}
        for linha in linhas[i + 1:]:
            if not linha.strip():
                continue
            celulas = next(csv.reader([linha]))
            self.dias.append(celulas[0].strip())
            for termo, valor in zip(self.termos, celulas[1:]):
                self.valores[termo].append(valor.strip())

    # ------------------------------------------------------------------ medidas

    @staticmethod
    def num(valor: str) -> float:
        """'<1' é um valor censurado, não zero: vira 0,5 para efeito de comparação.

        Só aparece quando a escala já foi esmagada; tratá-lo como 0 esconderia
        justamente o sintoma que este script procura.
        """
        return 0.5 if valor == "<1" else float(valor)

    def distintos(self, termo: str, ignorar: set[str] | None = None) -> int:
        """Valores distintos, descontando os dias anômalos.

        Contar por arquivo, sem descontar, faz o `lixeira` parecer aprovado: dá 13 com o
        dia sem dado e 12 sem ele, e o `PLANO_TRENDS.md` já adotava o segundo ("são 12
        coletados e 11 acima do piso"). Contar o dia que a fonte não entregou como se
        fosse um valor infla a resolução de todo termo que tem dia zerado.
        """
        ignorar = ignorar or set()
        return len({
            v for dia, v in zip(self.dias, self.valores[termo]) if dia not in ignorar
        })

    def termos_com_volume(self) -> list[str]:
        """Termos cuja mediana passa de 2: os únicos cujo zero significa alguma coisa.

        Sem isto, "a linha inteira zerou" dispara em lote de termos minúsculos, onde
        quase todas as colunas são zero o tempo todo. Medido em 03/09 no `P4a`: três
        dos quatro termos são zero em todos os dias, então bastava o quarto cair para o
        auditor anunciar 8 "dias sem dado" que não existiam.
        """
        vivos = []
        for termo in self.termos:
            serie = [self.num(v) for v in self.valores[termo]]
            if sorted(serie)[len(serie) // 2] > 2:
                vivos.append(termo)
        return vivos

    def dias_anomalos(self) -> dict[str, list[str]]:
        """Dia -> motivos. Dois padrões: a consulta inteira zerada, ou salto de 10×.

        "Zerada" se mede sobre os termos com volume, e exige pelo menos dois. Um termo
        sozinho caindo a zero é dropout daquele termo e aparece em `zeros_suspeitos`, não
        aqui. A diferença importa: esta lista vira nulo no carregador, e anular um dia que
        a fonte entregou seria inventar buraco.
        """
        achados: dict[str, list[str]] = defaultdict(list)
        vivos = self.termos_com_volume()
        for i, dia in enumerate(self.dias):
            if len(vivos) >= 2 and all(self.num(self.valores[t][i]) == 0 for t in vivos):
                achados[dia].append(
                    f"consulta inteira zerada ({len(vivos)} termos com volume)"
                )
                continue
            for termo in self.termos:
                serie = [self.num(v) for v in self.valores[termo]]
                mediana = sorted(serie)[len(serie) // 2]
                if mediana > 0 and serie[i] >= 10 * mediana:
                    achados[dia].append(
                        f"{termo} = {self.valores[termo][i]} (mediana {mediana:g})"
                    )
        return dict(achados)

    def zeros_suspeitos(self) -> dict[str, list[str]]:
        """Dia -> termos com zero isolado, que é dia sem dado disfarçado de queda.

        O check dos 10× só pega o dia quebrado quando ele sobe ou quando a linha inteira
        zera. O `19/07` mostrou o terceiro caso: naquele dia o `bebedouro de galao` e a
        `mangueira de jardim` zeram em lotes onde os vizinhos seguem normais; a fonte
        falhou para alguns termos, não para todos.

        Critério: o termo zera num dia mas tem mediana > 2, ou seja, não é um termo que
        vive perto de zero. Zero num termo que nunca chega perto de zero é buraco.
        Isto importa para a H1: zero falso no meio da série vira queda falsa e contamina
        a correlação (a mesma armadilha do campo `sales`).
        """
        achados: dict[str, list[str]] = defaultdict(list)
        for termo in self.termos:
            serie = [self.num(v) for v in self.valores[termo]]
            mediana = sorted(serie)[len(serie) // 2]
            if mediana <= 2:
                continue  # termo que vive perto de zero: zero ali é legítimo
            for i, v in enumerate(serie):
                if v == 0:
                    achados[self.dias[i]].append(f"{termo} (mediana {mediana:g})")
        return dict(achados)

    def dia_do_maximo(self) -> tuple[str, str, float] | None:
        """(dia, termo, valor) do máximo do lote, que define a escala."""
        melhor = None
        for termo in self.termos:
            for i, valor in enumerate(self.valores[termo]):
                v = self.num(valor)
                if melhor is None or v > melhor[2]:
                    melhor = (self.dias[i], termo, v)
        return melhor


def melhor_resolucao_por_termo(lotes: list[Lote]) -> dict[str, int]:
    """Termo -> o maior nº de valores distintos que ele alcançou em qualquer lote da pasta.

    Existe para julgar o lote vazio, e só a pasta inteira responde isso: um termo que
    volta sem série e nunca teve série em lugar nenhum é a fonte dizendo "não há dados
    suficientes"; o mesmo arquivo vazio para um termo que já rendeu série acompanhado
    é outro caso, em que o download solo é que não serve. Ver `sem_dados_na_fonte`.
    """
    melhor: dict[str, int] = {}
    for lote in lotes:
        if not lote.dias:
            continue
        anomalos = set(lote.dias_anomalos())
        for termo in lote.termos:
            # Aparição rasa não conta como sinal. Com a janela `b` na pasta, o
            # `touca de natacao` exibe {0, <1, 1} em 21 dias: três valores distintos,
            # que batem o piso mínimo e o promoveriam de "limite da fonte" para "o solo
            # não serve para ele", o que é falso. Um critério de contagem calibrado em
            # 38 a 56 dias muda de significado numa janela de 21.
            if max(lote.num(v) for v in lote.valores[termo]) <= 1:
                continue
            d = lote.distintos(termo, ignorar=anomalos)
            melhor[termo] = max(melhor.get(termo, 0), d)
    return melhor


def donos_da_janela_a(lotes: list[Lote]) -> dict[str, tuple[str, int, int]]:
    """Termo -> (arquivo dono, distintos, piso). Os lotes `b` e `c` não competem.

    "Dono" é o arquivo em que o termo passou do piso com a maior folga relativa; é desse
    arquivo que a série do termo sai. Os outros 4 termos de um lote estão lá para
    reproduzir a composição, não para render série: eles têm dono em outro arquivo.
    """
    return donos_da_janela(lotes, "a")


def donos_da_janela(lotes: list[Lote], janela: str) -> dict[str, tuple[str, int, int]]:
    """O mesmo critério de dono, só entre os arquivos de uma janela (`a`, `b` ou `c`).

    Na janela `c` o dono é o arquivo de maior folga, e não o par do dono antigo. O
    experimento 2 usa só a busca posterior a 06/09, então a série `c` nunca é emendada a
    nada: o que importa nela é a resolução. Reproduzir a composição no download continua
    correto, porque dá a melhor chance de resolver, mas amarrar o dono ao par descartaria
    um termo que resolveu num vizinho.
    """
    dono: dict[str, tuple[str, int, int]] = {}
    folga: dict[str, float] = {}
    for lote in lotes:
        if janela_do_lote(lote.nome) != janela or not lote.dias:
            continue
        anomalos = set(lote.dias_anomalos())
        piso = piso_para(len(lote.dias) - len(anomalos))
        for termo in lote.termos:
            d = lote.distintos(termo, ignorar=anomalos)
            if d > piso and d / piso > folga.get(termo, 0):
                folga[termo] = d / piso
                dono[termo] = (lote.nome, d, piso)
    return dono


def conferir_pares_ab(lotes: list[Lote]) -> tuple[list[str], list[str]]:
    """Para cada lote `b`, os termos-dono do `a` par sobreviveram? (ok, perdidos)

    A discrepância entre termos dentro de um lote `b` é o funcionamento correto: o
    vizinho esmagado ali tem dono em outro arquivo. O que importa é se o dono daquele
    arquivo sobreviveu na metade `b`. Sem este check, a avaliação visual conta quantos
    termos do lote passaram, e acusa problema onde não há.
    """
    dono = donos_da_janela_a(lotes)
    ok: list[str] = []
    perdidos: list[str] = []
    for lote in lotes:
        if janela_do_lote(lote.nome) != "b" or not lote.dias:
            continue
        par_a = lote.nome.replace("b.csv", "a.csv")
        anomalos = set(lote.dias_anomalos())
        piso = piso_para(len(lote.dias) - len(anomalos))
        for termo in lote.termos:
            if dono.get(termo, ("",))[0] != par_a:
                continue
            d_b = lote.distintos(termo, ignorar=anomalos)
            _arq, d_a, piso_a = dono[termo]
            linha = (f"{lote.nome}: {termo} — a={d_a}/{piso_a}, b={d_b}/{piso}")
            (ok if d_b > piso else perdidos).append(linha)
    return ok, perdidos


def conferir_janela_c(lotes: list[Lote]) -> dict[str, list[str]]:
    """Quem tinha série até 06/09 ganhou série na janela `c`? (o experimento 2 só lê a `c`)

    Devolve três listas de termos: `com_c` (tinham série antes e resolveram na `c`),
    `sem_c` (tinham série antes e não resolveram em arquivo `c` nenhum) e `so_c` (não tinham
    série antes e resolveram agora). "Série antes" é dono na `a` ou resolução na `b`: os
    10 termos que só abriram na metade recente contam.
    `sem_c` não é, por si, defeito de download: é termo que a fonte não exibiu na janela
    nova com aquela vizinhança, da mesma família do "limite da fonte", e datado.
    """
    if not any(janela_do_lote(l.nome) == "c" and l.dias for l in lotes):
        return {"com_c": [], "sem_c": [], "so_c": []}
    antes = set(donos_da_janela(lotes, "a")) | set(donos_da_janela(lotes, "b"))
    agora = set(donos_da_janela(lotes, "c"))
    return {
        "com_c": sorted(antes & agora),
        "sem_c": sorted(antes - agora),
        "so_c": sorted(agora - antes),
    }


def conferir(pasta: Path) -> int:
    arquivos = sorted(pasta.glob("trends_lote*.csv"))
    if not arquivos:
        print(f"[!!] Nenhum trends_lote*.csv em {pasta}")
        return 1

    contaminados: list[str] = []
    mal_configurados: list[str] = []
    sem_dados_fonte: list[tuple[str, str]] = []
    solo_nao_serve: list[tuple[str, str, int]] = []
    ilegiveis: list[str] = []
    uteis: list[tuple[str, int]] = []
    refazer: list[tuple[str, int, str]] = []
    anomalos_global: dict[str, set[str]] = defaultdict(set)
    zeros_global: dict[str, set[str]] = defaultdict(set)
    janelas: dict[tuple[str, str], set[str]] = defaultdict(set)

    print(f"Lotes lidos: {len(arquivos)}  (pasta: {pasta})\n")

    # Duas passadas de propósito: julgar o lote vazio exige saber o que aquele termo
    # rendeu nos outros lotes, e isso não existe enquanto se lê um arquivo por vez.
    lidos = [Lote(caminho) for caminho in arquivos]
    melhor = melhor_resolucao_por_termo(lidos)

    for lote in lidos:
        if not lote.dias:
            if not lote.termos:
                ilegiveis.append(lote.nome)
                print(f"[!!] {lote.nome}: ILEGÍVEL — nem o cabeçalho `Dia,` está lá. "
                      f"Refazer o download.")
                continue
            termo = lote.termos[0]
            alhures = melhor.get(termo, 0)
            if alhures >= PISO_MINIMO:
                solo_nao_serve.append((lote.nome, termo, alhures))
                print(f"[!?] {lote.nome}: SEM SÉRIE, mas `{termo}` já rendeu "
                      f"{alhures} distintos ACOMPANHADO.\n"
                      f"       Não é limite da fonte: é o SOLO que não serve para ele. "
                      f"Refazer em par, não sozinho.")
            else:
                sem_dados_fonte.append((lote.nome, termo))
                print(f"[--] {lote.nome}: SEM SÉRIE — a fonte respondeu "
                      f"'não há dados suficientes' para `{termo}`.\n"
                      f"       NÃO refazer: o download funcionou (o cabeçalho traz o termo "
                      f"e a região).")
            continue

        problemas = []
        if lote.categoria != CATEGORIA_ESPERADA:
            problemas.append(f"categoria = {lote.categoria!r}")
        fora = {r for r in lote.regioes if r != REGIAO_ESPERADA}
        if fora:
            problemas.append(f"região = {sorted(fora)}")
        if janela_do_lote(lote.nome) == "c" and (lote.dias[0], lote.dias[-1]) != JANELA_C:
            problemas.append(f"janela c = {lote.dias[0]} a {lote.dias[-1]}, "
                             f"e a fixada é {JANELA_C[0]} a {JANELA_C[1]}")
        if problemas:
            mal_configurados.append(lote.nome)

        janelas[(lote.dias[0], lote.dias[-1])].add(lote.nome)

        anomalos = lote.dias_anomalos()
        for dia, motivos in anomalos.items():
            anomalos_global[dia].update(motivos)
        for dia, termos_zerados in lote.zeros_suspeitos().items():
            zeros_global[dia].update(f"{lote.nome}: {t}" for t in termos_zerados)

        maximo = lote.dia_do_maximo()
        contaminado = maximo is not None and maximo[0] in anomalos

        marca = "[!!]" if (contaminado or problemas) else "[ok]"
        print(f"{marca} {lote.nome}  {len(lote.dias)} dias "
              f"({lote.dias[0]} a {lote.dias[-1]})")
        for p in problemas:
            print(f"       CONFIGURAÇÃO: {p}")
        if maximo:
            print(f"       máximo do lote: {maximo[1]} em {maximo[0]}")
        if contaminado:
            contaminados.append(lote.nome)
            print(f"       [x] CONTAMINADO — o máximo cai num DIA ANÔMALO, então a escala "
                  f"do lote inteiro\n"
                  f"          foi definida por um valor que não existe. Os 5 termos "
                  f"morrem juntos.")

        piso = piso_para(len(lote.dias) - len(anomalos))
        for termo in lote.termos:
            n = lote.distintos(termo, ignorar=set(anomalos))
            rasos = sum(1 for v in lote.valores[termo] if v in ("0", "<1", "1"))
            if n > piso:
                uteis.append((termo, n))
                print(f"       [ok] {termo:34s} distintos={n:3d}")
            else:
                causa = "lote contaminado" if contaminado else "esmagado pelo vizinho"
                refazer.append((termo, n, causa))
                print(f"       [refazer] {termo:34s} distintos={n:3d}  "
                      f"rasos={rasos}/{len(lote.dias)}  ({causa})")
        print()

    print("=" * 74)
    print("DIAS ANÔMALOS DA FONTE")
    print("=" * 74)
    for dia in sorted(anomalos_global):
        novo = "" if dia in DIAS_QUEBRADOS_CONHECIDOS else "  🆕 NÃO estava na lista"
        print(f"  {dia}{novo}")
        for motivo in sorted(anomalos_global[dia])[:6]:
            print(f"      {motivo}")
        if len(anomalos_global[dia]) > 6:
            print(f"      ... e mais {len(anomalos_global[dia]) - 6}")

    print()
    print("=" * 74)
    print("JANELAS PEDIDAS — misturar janela em silêncio é o defeito mais caro daqui")
    print("=" * 74)
    for (ini, fim), nomes in sorted(janelas.items()):
        risco = "  [atencao] CONTÉM 2026-08-16" if ini <= "2026-08-16" <= fim else ""
        print(f"  {ini} a {fim}   {len(nomes)} lote(s){risco}")
        print(f"      {', '.join(sorted(nomes))}")
    if len(janelas) > 1:
        print("\n  [atencao] Há MAIS DE UMA janela na pasta. Isso é legítimo desde 03/09 — a janela")
        print("     encurtou para excluir o 16/08 —, mas só é legítimo se for DELIBERADO.")
        print("     *Séries de comprimentos diferentes não impedem lead-lag dentro do termo;")
        print("     impedem qualquer comparação de nível entre termos de janelas distintas.*")

    print()
    print("=" * 74)
    print("ZEROS ISOLADOS — dia sem dado disfarçado de queda (viram NULO no carregador)")
    print("=" * 74)
    for dia in sorted(zeros_global):
        print(f"  {dia}   {len(zeros_global[dia])} termo(s)")
        for quem in sorted(zeros_global[dia])[:5]:
            print(f"      {quem}")
        if len(zeros_global[dia]) > 5:
            print(f"      ... e mais {len(zeros_global[dia]) - 5}")

    print()
    print("=" * 74)
    print("RESUMO")
    print("=" * 74)
    # Contagem por termo, não por ocorrência. Os dois números podem coincidir enquanto
    # nenhum termo passa do piso em dois lotes, o que esconde a diferença; quando um
    # passar, `len(uteis)` contaria o mesmo termo duas vezes. Do outro lado, um termo
    # pode estar abaixo do piso em quatro lotes e resolvido no quinto: contar ocorrências
    # transforma 32 pendências em 123 e a lista deixa de ser acionável.
    resolvidos = {t for t, _n in uteis}
    pendentes = {t for t, _n, _c in refazer} - resolvidos
    print(f"  [ok] termos com resolução útil ..................... {len(resolvidos)}")
    print(f"     *piso proporcional à janela: {PISO_DISTINTOS} distintos em "
          f"{DIAS_DA_CALIBRACAO} dias, a mesma taxa nas outras*")
    print(f"  [refazer] termos SEM resolução em lote nenhum ........... {len(pendentes)}")
    print(f"     *({len(refazer)} ocorrências termo×lote — o número acionável é o de cima)*")
    pares_ok, pares_perdidos = conferir_pares_ab(lidos)
    if pares_ok or pares_perdidos:
        print(f"  [pares] PARES a↔b — termos-DONO que sobreviveram na metade `b` .. "
              f"{len(pares_ok)}/{len(pares_ok) + len(pares_perdidos)}")
        print(f"     *só o dono conta: o vizinho esmagado num `b` tem dono em outro arquivo*")
        for linha in pares_perdidos:
            print(f"     [x] PERDEU A METADE b — {linha}")
    c = conferir_janela_c(lidos)
    if c["com_c"] or c["sem_c"] or c["so_c"]:
        antes = len(c["com_c"]) + len(c["sem_c"])
        print(f"  🆕 JANELA c ({JANELA_C[0]} a {JANELA_C[1]}) — termos com série até 06/09 "
              f"que resolveram na c .. {len(c['com_c'])}/{antes}")
        print(f"     *é a única janela que o experimento 2 lê; o dono na c é o arquivo de "
              f"maior folga*")
        for termo in c["sem_c"]:
            print(f"     [--] sem série na c — {termo}")
        if c["so_c"]:
            print(f"     [+] resolveram SÓ na c ({len(c['so_c'])}): {', '.join(c['so_c'])}")

    print(f"  [x] lotes CONTAMINADOS (refazer o lote inteiro) ... {len(contaminados)}")
    for nome in contaminados:
        print(f"        {nome}")
    if mal_configurados:
        print(f"  [x] lotes MAL CONFIGURADOS ........................ "
              f"{len(mal_configurados)}")
        for nome in mal_configurados:
            print(f"        {nome}")
    if ilegiveis:
        print(f"  [x] lotes ILEGÍVEIS (refazer o download) .......... {len(ilegiveis)}")
        for nome in ilegiveis:
            print(f"        {nome}")
    if solo_nao_serve:
        print(f"  [atencao] SEM SÉRIE, mas o termo TEM série acompanhado .. {len(solo_nao_serve)}")
        print(f"        *refazer EM PAR — sozinho, a fonte não o exibe*")
        for nome, termo, alhures in solo_nao_serve:
            print(f"        {nome}: {termo} ({alhures} distintos em outro lote)")
    if sem_dados_fonte:
        print(f"  [--] LIMITE DA FONTE (não refazer) ................. "
              f"{len(sem_dados_fonte)}")
        print(f"        *a fonte respondeu 'não há dados suficientes'; "
              f"nenhum download muda isso*")
        for nome, termo in sem_dados_fonte:
            print(f"        {nome}: {termo}")

    print()
    print("  [atencao] LIMITE: este script NÃO consegue conferir se o termo foi pedido como")
    print("     'Termo de pesquisa' ou como 'Tópico' — o CSV não carrega a distinção.")

    return 1 if (contaminados or mal_configurados or ilegiveis) else 0


if __name__ == "__main__":
    raiz = Path(__file__).resolve().parent.parent
    destino = Path(sys.argv[1]) if len(sys.argv) > 1 else raiz / "02_Dados" / "trends"
    sys.exit(conferir(destino))

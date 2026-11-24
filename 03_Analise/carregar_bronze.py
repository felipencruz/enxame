# -*- coding: utf-8 -*-
"""Loader do Bronze: dos CSV exportados do n8n até o pandas.

Este módulo lê os CSV gerados pelos workflows de export do n8n, com `coletado_em`
preservado por linha, uma linha por leitura de cada coletor. Exports com `distinct`
não servem à EDA, porque destroem a série temporal.

## Dois regimes de export: a série é a união dos dois

Até 29/07/2026 o export era cumulativo. O workflow `TCC — [util] Exportar Bronze`
(`6dAtB1xEFBjL0wRp`, só leitura, manual) lia a data table inteira, que nunca era limpa:
cada arquivo continha a série completa até aquele momento, e carregar o mais recente
bastava. Nome: `tcc_bronze_<tabela>_<AAAA-MM-DD>.csv`.

Desde 29/07 a política é rotacionar, porque a cota das data tables chegou a 40,41 de
50 MB e estourá-la significa perder coleta. O workflow `pliN9f1zwIhClN2M` (Backup diário
da camada bronze, agendado às 15:00 BRT) exporta as 7 tabelas para o Google Drive
(uma pasta da conta do projeto) e purga as 5 Bronze, preservando só o
snapshot mais recente de cada uma. Nome: `<apelido>_<AAAAMMDD>_<HH-mm>Z.csv`, carimbo
em UTC. Três consequências, todas medidas:

1. Um export diário não tem a série inteira, só a janela viva. O export de
   29/07 19:01Z é o último cumulativo: ele saiu antes da purga, na mesma execução.
2. A série completa é aquele export mais cada export diário. Por isso este loader
   concatena e deduplica por `id` em vez de pegar o mais recente.
3. Exports consecutivos se sobrepõem por um snapshot, porque o corte da purga é
   `id <= id_corte` e o `id_corte` preserva a última rodada de propósito (tabela zerada
   faria o alerta de coletor parado disparar alarme falso nas 5 fontes). A sobreposição
   é esperada e é resolvida pelo dedup.

## Por que o `id` é a espinha dorsal do loader

O `id` da data table é insert-only, numérico e contíguo de 1 até N por tabela
(medido nas 7 tabelas em 29/07). Isso dá três garantias que o loader usa como guarda:

- Dedup por `id` é seguro: a mesma linha nunca é reescrita, então `id` repetido em
  dois exports é a mesma leitura, não duas.
- Buraco no `id` é assinatura de export perdido. É o risco que a rotação criou: a
  reprodutibilidade da série depende de não perder nenhum export. O guarda transforma
  isso em erro em vez de silêncio.
- `id` mínimo maior que 1 significa que falta o começo da série, tipicamente o
  export cumulativo de 29/07. Sem esse guarda, baixar só o export do dia devolveria uma
  série de um dia com aparência de série inteira.

O hiato do Mercado Livre (23 a 28/07) não produz buraco de `id` e não deve ser
confundido com um: durante o hiato nenhuma linha foi gravada, e o `id` só avança em
inserção. O buraco aparece quando linhas existiram e foram purgadas sem que o export
que as guardava esteja presente.

Tudo aqui fica como veio do Bronze (`dtype=str`, exceto `coletado_em`): tratamentos de
tipo, `\xa0` no preço, parsing de `rank`/`avaliacao` etc. são da Silver
(`preparar_silver.py`), não deste loader.
"""
from __future__ import annotations

import glob
import os
import re
import warnings
from pathlib import Path

import pandas as pd

RAW_DIR = Path(__file__).resolve().parent.parent / "02_Dados" / "raw"

TABELAS = [
    "tcc_bronze_google_suggest",
    "tcc_bronze_youtube",
    "tcc_bronze_shopee",
    "tcc_bronze_ml",
    "tcc_bronze_amazon",
]

# Apelido do arquivo no Drive -> nome da tabela. O mapa é explícito porque nenhum dos
# dois lados é derivável do outro: `yt` != `youtube` e `ml` != `tcc_bronze_ml`.
# Também porque `amazon_vitrines_*.csv` fica na mesma pasta do Drive: um casamento por
# prefixo `amazon_` engoliria a tabela de vitrines (amostra viva, não série, com
# outras colunas) dentro do Bronze da Amazon. `seeds_*` está no mesmo caso.
APELIDO_DRIVE = {
    "google_suggest": "tcc_bronze_google_suggest",
    "yt": "tcc_bronze_youtube",
    "shopee": "tcc_bronze_shopee",
    "ml": "tcc_bronze_ml",
    "amazon": "tcc_bronze_amazon",
}

# Quanto tempo o dado local pode ter antes de o loader recusar-se a servi-lo. O export
# é diário; além disto, número apresentado como "de hoje" seria enganoso. O valor é
# julgamento, não medição; `idade_maxima_dias=None` desliga o guarda.
IDADE_MAXIMA_DIAS = 3

# Fontes encerradas por decisão do projeto. O Mercado Livre parou de gravar em 06/10 (a
# fonte passou a pedir verificação de conta ao crachá honesto; desde 19/10 devolve HTTP 500)
# e o coletor seguiu tentando. Em 20/10 optou-se por tirá-lo do projeto: o Bronze fica como
# exemplo e a análise, da Silver em diante, não o usa mais. Duas consequências justificam
# esta constante:
# (1) a tabela não passa pelo guarda de idade: ela é histórica por decisão, e a mensagem do
#     guarda mandaria baixar um export que não traria nada novo;
# (2) linha com `coletado_em` a partir do `fim_exclusivo` é descartada na carga, com aviso:
#     o coletor segue publicado para testar se a fonte volta, e o que for gravado depois da
#     decisão não entra em análise nenhuma, nem nas datadas, que medem até 06/10.
# O Bronze não é tocado: o corte é da leitura, declarado aqui e no aviso.
PARADAS_DECLARADAS = {
    "tcc_bronze_ml": {
        "fim_exclusivo": "2026-10-07T00:00:00Z",
        "ultima_rodada_gravada": "2026-10-06T03:00Z (00:00 BRT)",
        "decidido_em": "2026-10-20",
        "motivo": ("a fonte pede verificacao de conta ao cracha honesto desde 06/10 e devolve "
                   "HTTP 500 desde 19/10; os Termos de Uso proibem a coleta automatizada; "
                   "em 20/10 o ML saiu do projeto"),
    },
    # O Google Suggest saiu em 02/11 pelo mesmo caminho, por outra razão: a fonte não parou,
    # mas não carrega volume (medido em 01/09), e a busca do trabalho é o Trends. Sai da
    # análise e o coletor foi despublicado (não fica testando, como o ML). Vale para o Suggest
    # o mesmo corte de fim da coleta das demais tabelas: a rodada de 02/11 03:00 UTC sai.
    "tcc_bronze_google_suggest": {
        "fim_exclusivo": "2026-11-02T00:00:00Z",
        "ultima_rodada_gravada": "2026-11-02T03:00Z (00:00 BRT)",
        "decidido_em": "2026-11-02",
        "motivo": ("o Suggest nao carrega volume (teto de 10 sugestoes, conjunto parado em 71,6% "
                   "dos termo-dia, medido em 01/09); a busca do trabalho e o Google Trends; "
                   "em 02/11 o Suggest saiu do projeto e o coletor foi despublicado"),
    },
}

# Fim da coleta do TCC. Em 02/11 a coleta foi encerrada, com uso dos dados até 01/11, e
# coletores, alertas e backup foram despublicados. O corte: todos os dias UTC até 01/11
# inclusive. Sai a rodada de 02/11 03:00 UTC (00:00 BRT), que deixaria o dia pela metade.
# As três fontes que seguem na análise entram em `PARADAS_DECLARADAS` com o mesmo corte e
# pela mesma razão do ML: série histórica por decisão não passa pelo guarda de idade, cuja
# mensagem mandaria baixar um export que não vai mais existir (o último é o de 02/11 04:51 UTC).
FIM_DA_COLETA = "2026-11-02T00:00:00Z"
for _tabela in ("tcc_bronze_shopee", "tcc_bronze_amazon", "tcc_bronze_youtube"):
    PARADAS_DECLARADAS[_tabela] = {
        "fim_exclusivo": FIM_DA_COLETA,
        "ultima_rodada_gravada": "2026-11-02T03:00Z (00:00 BRT)",
        "decidido_em": "2026-11-02",
        "motivo": ("a coleta do TCC acabou em 02/11: a analise usa as coletas ate 01/11 e "
                   "coletores, alertas e backup foram despublicados; o export de 02/11 04:51 UTC "
                   "e o ultimo"),
    }
del _tabela

# `tcc_bronze_<tabela>_<AAAA-MM-DD>.csv`: o export cumulativo, até 29/07.
_PADRAO_LEGADO = re.compile(r"^(?P<tabela>tcc_bronze_[a-z_]+)_(?P<data>\d{4}-\d{2}-\d{2})\.csv$")
# `<apelido>_<AAAAMMDD>_<HH-mm>Z.csv`: o export do Drive, desde 29/07. O `$` logo
# depois do carimbo é o que impede `amazon_vitrines_...` de casar como `amazon`.
_PADRAO_DRIVE = re.compile(r"^(?P<apelido>[a-z_]+)_(?P<data>\d{8})_(?P<hora>\d{2}-\d{2})Z\.csv$")

_INSTRUCAO_DOWNLOAD = (
    "A série vivia no Google Drive (pasta da conta do projeto, apagada depois da coleta), "
    "exportada pelo workflow n8n pliN9f1zwIhClN2M (Backup diário da camada bronze).\n"
    "  O QUE BAIXAR: o export cumulativo de 29/07 19:01Z (é o último que traz a série "
    "inteira) MAIS todos os exports diários posteriores.\n"
    "  PARA ONDE: {raw_dir} — sem renomear; este loader entende o nome do Drive.\n"
    "  Os arquivos seeds_*.csv e amazon_vitrines_*.csv não são série e são ignorados."
)


def _carimbo_ordenavel(nome: str) -> tuple[str, str] | None:
    """Devolve `(tabela, carimbo)` de um export, ou `None` se o arquivo não for série.

    O carimbo é normalizado para `AAAAMMDD_HH-mm` para que os dois regimes de nome
    ordenem juntos: o legado, que só tem data, entra como `00-00`.
    """
    m = _PADRAO_DRIVE.match(nome)
    if m:
        tabela = APELIDO_DRIVE.get(m.group("apelido"))
        if tabela is None:  # seeds, amazon_vitrines, ou arquivo alheio
            return None
        return tabela, f"{m.group('data')}_{m.group('hora')}"
    m = _PADRAO_LEGADO.match(nome)
    if m:
        return m.group("tabela"), f"{m.group('data').replace('-', '')}_00-00"
    return None


def _exports_da_tabela(tabela: str, raw_dir: Path = RAW_DIR) -> list[Path]:
    """Todos os exports de uma tabela, em ordem de carimbo.

    Nenhum é descartado: desde a rotação de 29/07 a série é a união deles. Pegar só o
    arquivo mais recente estaria correto no regime cumulativo, mas devolve apenas a
    janela viva no regime de rotação.
    """
    achados: list[tuple[str, Path]] = []
    for caminho in glob.glob(os.path.join(str(raw_dir), "*.csv")):
        par = _carimbo_ordenavel(os.path.basename(caminho))
        if par and par[0] == tabela:
            achados.append((par[1], Path(caminho)))
    achados.sort(key=lambda p: p[0])
    return [caminho for _, caminho in achados]


def _conferir_id(tabela: str, df: pd.DataFrame, arquivos: list[Path]) -> None:
    """Cobra do `id` as três garantias que tornam o dedup e a série confiáveis."""
    if "id" not in df.columns:
        raise ValueError(
            f"{tabela}: o export não tem coluna 'id'. Sem ela não há como deduplicar "
            f"exports sobrepostos nem detectar export perdido. Arquivos lidos: "
            f"{[a.name for a in arquivos]}"
        )
    ids = pd.to_numeric(df["id"], errors="coerce")
    if ids.isna().any():
        raise ValueError(
            f"{tabela}: {int(ids.isna().sum())} linha(s) com 'id' não numérico — "
            f"o mesmo defeito que o nó 'Conferir' do workflow de backup recusa antes de purgar."
        )
    ids = ids.astype("int64")
    if ids.min() != 1:
        raise ValueError(
            f"{tabela}: a série começa no id {ids.min()}, não em 1 — falta o export que "
            f"guarda o início dela (o cumulativo de 29/07 19:01Z).\n"
            f"  Sem ele, isto é a janela recente com cara de série inteira.\n  "
            + _INSTRUCAO_DOWNLOAD.format(raw_dir=arquivos[0].parent)
        )
    esperado = ids.max() - ids.min() + 1
    if len(ids) != esperado:
        faltando = sorted(set(range(int(ids.min()), int(ids.max()) + 1)) - set(ids.tolist()))
        trechos = _agrupar_faixas(faltando)
        raise ValueError(
            f"{tabela}: buraco no 'id' — faltam {len(faltando)} linha(s) em "
            f"{len(trechos)} trecho(s): {trechos[:5]}{' ...' if len(trechos) > 5 else ''}.\n"
            f"  O 'id' é contíguo de 1 a N por construção, então isto é EXPORT PERDIDO, "
            f"não hiato de coleta (hiato não consome id).\n  "
            + _INSTRUCAO_DOWNLOAD.format(raw_dir=arquivos[0].parent)
        )


def _agrupar_faixas(numeros: list[int]) -> list[str]:
    """`[3, 4, 5, 9]` -> `['3-5', '9']`, para que a mensagem de erro seja legível."""
    faixas: list[str] = []
    inicio = anterior = None
    for n in numeros:
        if inicio is None:
            inicio = anterior = n
        elif n == anterior + 1:
            anterior = n
        else:
            faixas.append(str(inicio) if inicio == anterior else f"{inicio}-{anterior}")
            inicio = anterior = n
    if inicio is not None:
        faixas.append(str(inicio) if inicio == anterior else f"{inicio}-{anterior}")
    return faixas


def _conferir_idade(tabela: str, df: pd.DataFrame, idade_maxima_dias: int, raw_dir: Path) -> None:
    """Recusa dado velho em voz alta.

    Sem este guarda, um export antigo é carregado sem aviso, e Silver, EDA e alvo da H1
    produzem números de dias atrás com aparência de números de hoje. Nenhuma etapa falha:
    o instrumento não sabe que envelheceu.
    """
    ultima = df["coletado_em"].max()
    if pd.isna(ultima):
        return  # o parse de `coletado_em` é conferido por outro caminho
    # Dias fracionários de propósito: com `idade.days`, que é inteiro, um dado de 3,9
    # dias passaria por um limite de 3; o limite valeria quase 4, não 3.
    idade_dias = (pd.Timestamp.now(tz="UTC") - ultima).total_seconds() / 86400
    if idade_dias > idade_maxima_dias:
        raise ValueError(
            f"{tabela}: a coleta mais recente aqui é de {ultima.date()} "
            f"({idade_dias:.1f} dias atrás), acima do limite de {idade_maxima_dias}.\n"
            f"  Analisar isto produziria número velho com cara de número de hoje.\n  "
            + _INSTRUCAO_DOWNLOAD.format(raw_dir=raw_dir)
            + f"\n  (Para analisar dado histórico de propósito: idade_maxima_dias=None.)"
        )


def carregar_tabela(
    tabela: str,
    raw_dir: Path = RAW_DIR,
    *,
    conferir_integridade: bool = True,
    idade_maxima_dias: int | None = IDADE_MAXIMA_DIAS,
) -> pd.DataFrame:
    """Carrega a série completa de uma tabela Bronze: concatena os exports e dedup por `id`.

    `conferir_integridade=False` desliga os guardas do `id` (série que começa depois do 1,
    buraco por export perdido). Use só quando a janela parcial for intencional e declarada.
    `idade_maxima_dias=None` desliga a recusa de dado velho.

    Tabela em `PARADAS_DECLARADAS` não passa pelo guarda de idade e chega cortada no
    `fim_exclusivo`; o que passar desse limite sai com `UserWarning`.
    """
    if tabela not in TABELAS:
        raise ValueError(f"Tabela desconhecida: {tabela!r}. Use uma de {TABELAS}.")
    arquivos = _exports_da_tabela(tabela, raw_dir)
    if not arquivos:
        raise FileNotFoundError(
            f"Nenhum export de '{tabela}' em {raw_dir}.\n  "
            + _INSTRUCAO_DOWNLOAD.format(raw_dir=raw_dir)
        )
    partes = [pd.read_csv(a, dtype=str, keep_default_na=False, na_values=[""]) for a in arquivos]
    df = pd.concat(partes, ignore_index=True)
    if "id" in df.columns:
        # `keep="first"` e não "last": o Bronze é insert-only, então as cópias são
        # idênticas; ficar com a primeira preserva a ordem do export mais antigo.
        df = df.drop_duplicates(subset=["id"], keep="first").reset_index(drop=True)
    if conferir_integridade:
        _conferir_id(tabela, df, arquivos)
    df["coletado_em"] = pd.to_datetime(df["coletado_em"], utc=True, errors="coerce")
    parada = PARADAS_DECLARADAS.get(tabela)
    if parada is not None:
        fim = pd.Timestamp(parada["fim_exclusivo"])
        depois = df["coletado_em"] >= fim
        if depois.any():
            warnings.warn(
                f"{tabela}: {int(depois.sum())} linha(s) coletada(s) a partir de "
                f"{fim.date()} ficaram FORA da carga — a fonte foi encerrada por decisão em "
                f"{parada['decidido_em']} (PARADAS_DECLARADAS); o Bronze não foi tocado.",
                UserWarning, stacklevel=2,
            )
            df = df[~depois]
    elif idade_maxima_dias is not None:
        _conferir_idade(tabela, df, idade_maxima_dias, raw_dir)
    return df.sort_values("coletado_em", kind="stable").reset_index(drop=True)


def carregar_todas(raw_dir: Path = RAW_DIR, **kwargs) -> dict[str, pd.DataFrame]:
    """Carrega as 5 tabelas Bronze num dicionário {nome_tabela: DataFrame}."""
    return {tabela: carregar_tabela(tabela, raw_dir, **kwargs) for tabela in TABELAS}


def cobertura(df: pd.DataFrame) -> dict[str, object]:
    """O que a série carregada de fato cobre, para o pipeline imprimir e não deduzir.

    Número velho sem etiqueta não é erro de código e passa despercebido. Toda etapa que
    consome o Bronze deve declarar qual janela leu.
    """
    ids = pd.to_numeric(df["id"], errors="coerce") if "id" in df.columns else pd.Series(dtype=float)
    return {
        "linhas": len(df),
        "id_min": None if ids.empty or ids.isna().all() else int(ids.min()),
        "id_max": None if ids.empty or ids.isna().all() else int(ids.max()),
        "primeira_coleta": df["coletado_em"].min(),
        "ultima_coleta": df["coletado_em"].max(),
        "snapshots": int(df["coletado_em"].nunique()),
    }


if __name__ == "__main__":
    for tabela in TABELAS:
        arquivos = _exports_da_tabela(tabela)
        print(f"\n{tabela}: {len(arquivos)} export(s) — {[a.name for a in arquivos]}")
        c = cobertura(carregar_tabela(tabela))
        print(
            f"  {c['linhas']} linhas · id {c['id_min']}..{c['id_max']} · "
            f"{c['snapshots']} snapshots · {c['primeira_coleta']} -> {c['ultima_coleta']}"
        )

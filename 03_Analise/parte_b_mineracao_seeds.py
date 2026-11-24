# -*- coding: utf-8 -*-
"""
TCC Enxame: Parte B da amostragem de sementes (seeds)
Mineração data-driven de termos de produto a partir dos títulos dos
bestsellers da camada Bronze (tcc_bronze_shopee, sortType=2 = top-vendas).

Fecha a amostragem híbrida: Parte A (frame = Google Product Taxonomy pt-BR)
+ Parte B (termos operacionais emergem do próprio mercado: Inteligência
Coletiva de Lévy, disc. 10).

Método (reprodutível, disc. 01 / Data Understanding do CRISP-DM, disc. 15):
  1. Deduplicação por item_id (já feita na extração do Bronze; snapshot 2026-07-10).
  2. Normalização do título (minúsculas, remoção de acentos e ruído).
  3. Classificador baseado em regras documentadas: cada tipo de produto é um
     padrão (regex) que mapeia para um (termo canônico, categoria da taxonomia).
     Para títulos com múltiplos produtos (bundles), vence o produto de menor
     posição no título (o "carro-chefe"); no empate, o padrão mais específico
     (match mais longo).
  4. Agregação por termo: suporte (nº de produtos campeões), vendas_total
     (força de mercado) e exemplos de títulos (rastreabilidade).

Saídas:
  - 02_Dados/processado/tcc_bronze_shopee_distinct_2026-07-10.csv   (snapshot legível)
  - 02_Dados/processado/tcc_seeds_candidatos_bestseller_shopee.csv
  - 02_Dados/processado/parte_b_classificacao_por_produto.csv (auditoria linha a linha)
"""
import csv
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
RAW_JSON = BASE / "02_Dados" / "raw" / "tcc_bronze_shopee_distinct_2026-07-10.json"
OUT_RAW_CSV = BASE / "02_Dados" / "processado" / "tcc_bronze_shopee_distinct_2026-07-10.csv"
OUT_CAND = BASE / "02_Dados" / "processado" / "tcc_seeds_candidatos_bestseller_shopee.csv"
OUT_AUDIT = BASE / "02_Dados" / "processado" / "parte_b_classificacao_por_produto.csv"
DATA_INCLUSAO = "2026-07-10"


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def norm(s: str) -> str:
    s = strip_accents(s.lower())
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


# ------------------------------------------------------------------------------
# Regras de classificação: (regex, termo canônico, categoria da taxonomia pt-BR)
# Ordem só importa para leitura; o algoritmo escolhe por posição+especificidade.
# ------------------------------------------------------------------------------
REGRAS = [
    # --- Eletrônicos ---
    (r"\bfones? de ouvido\b|\bheadset\b|\bearpods\b|\bfone\b",          "fone de ouvido bluetooth",        "Eletrônicos"),
    (r"\bpower bank\b|\bbateria portatil\b|\bcarregador portatil\b",     "power bank",                      "Eletrônicos"),
    (r"\bmicrofone\b",                                                   "microfone de lapela",             "Eletrônicos"),
    (r"\bcaix\w* de som\b|\bcaixinha de som\b",                          "caixa de som bluetooth",          "Eletrônicos"),
    (r"\bsmartwatch\b|\bsmart watch\b|\brelogio inteligente\b",          "smartwatch",                      "Eletrônicos"),
    (r"\bcampainha\b|\bvideo porteiro\b",                                "campainha com camera wifi",       "Eletrônicos"),
    (r"\bcarregador de bateria automotivo\b|\bcarregador\b.*\bautomotivo\b", "carregador de bateria automotivo", "Veículos e peças"),
    (r"\bcarregador\b|\bfonte tipo c\b",                                 "carregador de celular",           "Eletrônicos"),
    # --- Câmeras e óptica ---
    (r"\bring light\b|\biluminador\b",                                   "ring light",                      "Câmeras e óptica"),
    # --- Infantil ---
    (r"\bbaba eletronica\b|\bmonitor infantil\b",                        "baba eletronica",                 "Infantil"),
    (r"\bconjunto\b.*\b(menina|infantil|bebe)\b|\binfantil\b",           "conjunto infantil menina",        "Infantil"),
    # --- Ferragens (ferramentas) ---
    (r"\bparafusadeira\b|\bfuradeira\b",                                 "parafusadeira e furadeira",       "Ferragens"),
    (r"\bchave de impacto\b",                                            "chave de impacto",                "Ferragens"),
    (r"\bcatraca\b|\bjogo de chave\b|\bjogo chave\b|\bkit de ferramentas\b|\bkit chaves\b|\bsoquetes\b", "jogo de chaves e soquetes", "Ferragens"),
    (r"\blavadora\b.*\bpress\w*|\balta pressao\b",                       "lavadora de alta pressao",        "Ferragens"),
    # --- Veículos e peças ---
    (r"\bmacaco hidraulico\b",                                           "macaco hidraulico",               "Veículos e peças"),
    (r"\bbomba de ar\b|\bcompressor\b|\bcalibrador\b",                   "compressor de ar automotivo",     "Veículos e peças"),
    (r"\bkit lavagem\b|\bv-floc\b|\bvonixx\b|\bshampoo\b.*\bcera\b|\bcera\b.*\bautomotiv",  "kit de lavagem automotiva", "Veículos e peças"),
    (r"\bpatinete\b|\bscooter\b",                                        "patinete eletrico",               "Veículos e peças"),
    # --- Casa e jardim (cozinha, utilidades) ---
    (r"\bair fryer\b|\bfritadeira\b",                                    "air fryer",                       "Casa e jardim"),
    (r"\bpanela\b.*\bpress\w*|\bpanela de pressao\b",                    "panela de pressao",               "Casa e jardim"),
    (r"\bconjunto de panelas\b|\bpanelas\b",                             "conjunto de panelas",             "Casa e jardim"),
    (r"\bliquidificador\b|\bespremedor\b|\bbatedeira\b",                 "liquidificador",                  "Casa e jardim"),
    (r"\bprocessador de alimentos\b|\btriturador\b",                     "processador de alimentos",        "Casa e jardim"),
    (r"\bchaleira\b",                                                    "chaleira eletrica",               "Casa e jardim"),
    (r"\bsanduicheira\b",                                                "sanduicheira",                    "Casa e jardim"),
    (r"\bpotes?\b|\bmarmita\b|\bmantimentos\b",                          "potes hermeticos",                "Casa e jardim"),
    (r"\bcanecas?\b",                                                    "caneca de vidro",                 "Casa e jardim"),
    (r"\butensilios\b|\bfouet\b|\bpegador\b",                            "utensilios de cozinha",           "Casa e jardim"),
    (r"\bespelho\b",                                                     "espelho com led",                 "Casa e jardim"),
    (r"\bventilador\b",                                                  "ventilador",                      "Casa e jardim"),
    (r"\bgalao de agua\b|\bbebedor\b|\bbebedouro\b",                     "bebedouro de galao",              "Casa e jardim"),
    (r"\bprotetor de colchao\b|\bcapa\b.*\bcolchao\b",                   "protetor de colchao",             "Casa e jardim"),
    # --- Móveis ---
    (r"\bmesa portatil\b|\bmesa para notebook\b|\bmesa\b.*\bnotebook\b", "mesa para notebook",              "Móveis"),
    (r"\barara\b",                                                       "arara de roupas",                 "Móveis"),
    # --- Vestuário e acessórios ---
    (r"\blegging\b",                                                     "legging fitness",                 "Vestuário e acessórios"),
    (r"\bconjunto\b.*\bfitness\b|\bconjunto\b.*\bacademia\b|\bconjunto esportivo\b|\btop com bojo\b", "conjunto fitness feminino", "Vestuário e acessórios"),
    (r"\btenis\b",                                                       "tenis esportivo",                 "Vestuário e acessórios"),
    (r"\bdry fit\b|\bcamisa\b.*\bbermuda\b",                             "conjunto dry fit masculino",      "Vestuário e acessórios"),
    (r"\bshort tactel\b|\bshort\b.*\bmasculino\b",                       "short masculino",                 "Vestuário e acessórios"),
    (r"\bmoletom\b",                                                     "calca de moletom",                "Vestuário e acessórios"),
    (r"\bcropped\b|\bblusa top\b",                                       "cropped feminino",                "Vestuário e acessórios"),
    (r"\balfaiataria\b|\bshort social\b|\bcolete e short\b",             "conjunto de alfaiataria feminino", "Vestuário e acessórios"),
    # --- Saúde e beleza ---
    (r"\bperfume\b",                                                     "perfume masculino",               "Saúde e beleza"),
    (r"\bprancha\b.*\bcabelo\b|\bchapinha\b",                            "prancha de cabelo",               "Saúde e beleza"),
    (r"\bmagnesio\b|\bmelatonina\b|\binositol\b|\bsuplemento\b",         "suplemento (magnesio e melatonina)", "Saúde e beleza"),
    # --- Animais e pet ---
    (r"\barranhador\b|\bpara gatos\b|\bgatos\b",                         "arranhador para gatos",           "Animais e pet"),
]
REGRAS_COMP = [(re.compile(rx), termo, cat) for rx, termo, cat in REGRAS]


def classificar(titulo_norm: str):
    """Retorna (termo, categoria, regex) do produto carro-chefe do título."""
    melhor = None  # (start_pos, -match_len, termo, cat, rx)
    for rx, termo, cat in REGRAS_COMP:
        m = rx.search(titulo_norm)
        if m:
            cand = (m.start(), -(m.end() - m.start()), termo, cat, rx.pattern)
            if melhor is None or cand < melhor:
                melhor = cand
    if melhor is None:
        return (None, None, None)
    return (melhor[2], melhor[3], melhor[4])


def main():
    produtos = json.loads(RAW_JSON.read_text(encoding="utf-8"))

    # snapshot legível
    OUT_RAW_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_RAW_CSV.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["item_id", "product_name", "sales", "price", "rating_star", "commission_rate"])
        w.writeheader()
        w.writerows(produtos)

    # classificação por produto (auditoria)
    OUT_CAND.parent.mkdir(parents=True, exist_ok=True)
    agg = defaultdict(lambda: {"categoria": None, "suporte": 0, "vendas_total": 0, "exemplos": []})
    nao_classificados = []
    audit_rows = []
    for p in produtos:
        tnorm = norm(p["product_name"])
        termo, categoria, _ = classificar(tnorm)
        audit_rows.append({
            "item_id": p["item_id"], "product_name": p["product_name"],
            "sales": p["sales"], "termo": termo or "", "categoria": categoria or "",
        })
        if termo is None:
            nao_classificados.append(p["product_name"])
            continue
        a = agg[termo]
        a["categoria"] = categoria
        a["suporte"] += 1
        a["vendas_total"] += int(p["sales"])
        if len(a["exemplos"]) < 3:
            a["exemplos"].append(p["product_name"][:60])

    with OUT_AUDIT.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["item_id", "product_name", "sales", "termo", "categoria"])
        w.writeheader()
        w.writerows(audit_rows)

    # tabela de candidatos (formato tcc_seeds + métricas de suporte)
    linhas = []
    for termo, a in agg.items():
        linhas.append({
            "termo": termo,
            "categoria": a["categoria"],
            "origem": "bestseller_shopee",
            "justificativa": f"Termo de produto emergente de {a['suporte']} bestseller(s) do Shopee "
                             f"(top-vendas sortType=2); vendas acumuladas={a['vendas_total']}. "
                             f"Ex.: {' | '.join(a['exemplos'])}",
            "ativo": "true",
            "data_inclusao": DATA_INCLUSAO,
            "suporte": a["suporte"],
            "vendas_total": a["vendas_total"],
        })
    linhas.sort(key=lambda r: (-r["vendas_total"], -r["suporte"]))

    with OUT_CAND.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["termo", "categoria", "origem", "justificativa", "ativo", "data_inclusao", "suporte", "vendas_total"])
        w.writeheader()
        w.writerows(linhas)

    # ---- relatório no console ----
    print(f"Produtos distintos (Bronze snapshot): {len(produtos)}")
    print(f"Classificados: {len(produtos) - len(nao_classificados)} | Nao classificados: {len(nao_classificados)}")
    print(f"Termos-semente candidatos (distintos): {len(linhas)}")
    cats = defaultdict(int)
    for r in linhas:
        cats[r["categoria"]] += 1
    print("\nCandidatos por categoria:")
    for c, n in sorted(cats.items(), key=lambda x: -x[1]):
        print(f"  {n:2d}  {c}")
    print("\nRanking de termos (por vendas acumuladas):")
    print(f"  {'termo':<34} {'categoria':<24} {'sup':>3} {'vendas':>8}")
    for r in linhas:
        print(f"  {r['termo']:<34} {r['categoria']:<24} {r['suporte']:>3} {r['vendas_total']:>8}")
    if nao_classificados:
        print("\nNao classificados:")
        for t in nao_classificados:
            print(f"  - {t}")


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""
TCC Enxame: Parte B3, refresh da amostragem sobre o Bronze atual (21/07/2026)

Motivação
---------
A Parte B2 (15/07) minerou os termos sobre uma foto de 257 produtos (67 Shopee +
154 ML + 36 Amazon, esta última da rota GERAL aposentada em 16/07). Desde então a
Amazon trocou de rota (16/07) e passou a servir 22 vitrines por departamento, e o
universo de produtos distintos saltou de 36 para cerca de 1.583. Medido em 21/07: as
regras de 15/07 cobrem só cerca de 48% dos bestsellers atuais da Amazon e 66% dos da
Shopee.

Os órfãos são bens físicos legítimos com termo óbvio que as regras nunca viram
(caneta, café, sabonete, fralda, panela, tapete, câmera de segurança, mouse, echo/
alexa, depurador, cortina, toalha, garrafa térmica...), não o caso Kindle-livro/gift-
card que a Parte A corretamente exclui. Este script estende o classificador para
cobri-los, com o alvo declarado de sustentar a H1 Shopee+Amazon (a demanda da Amazon
entra pelo movimento de `rank_percentil`, e cada produto precisa de um termo para
cruzar com a série de busca do Suggest).

O que não muda
--------------
- As Partes B e B2 ficam intactas: o resultado de 10/07 e de 15/07 continua
  reproduzível byte a byte. Este script importa as regras de lá (v1+v2) e apenas
  acrescenta REGRAS_V3.
- Invariante aditiva (checada no main): nenhuma regra nova pode reclassificar um
  produto que a B2 já classificava, nem nos 67 de 10/07 nem nos 257 de 15/07. Regra
  nova só pega órfão. Se a invariante quebrar, o main aborta apontando o produto.
- O escopo continua o da Parte A (só bens de consumo físicos). Livro Kindle e gift
  card digital seguem órfãos, como manda a metodologia.

Limite do método
----------------
As regras são escritas à mão pelo pesquisador, e a superfície de julgamento cresce
(cerca de 60 regras novas sobre as 120 anteriores). A defesa é a mesma das partes
anteriores: a seleção dos produtos é ditada pelo mercado (campeões de venda reais);
só a nomeação do termo canônico é regra, auditável linha a linha aqui. Cada regra
nasceu de um bestseller real órfão de 21/07 (ver a auditoria emitida).

Entradas (snapshots datados e reproduzíveis, congelados de tcc_silver por
`snapshot_e_orfaos`, distintos por item_id):
  - 02_Dados/raw/tcc_bronze_amazon_distinct_2026-07-21.json
  - 02_Dados/raw/tcc_bronze_shopee_distinct_2026-07-21.json

Saídas:
  - 02_Dados/processado/parte_b3_termos_novos.csv           (termos a inserir na tcc_seeds)
  - 02_Dados/processado/parte_b3_classificacao_por_produto.csv (auditoria linha a linha)
"""
import csv
import json
import re
from collections import defaultdict
from pathlib import Path

from parte_b_mineracao_seeds import REGRAS as REGRAS_V1
from parte_b_mineracao_seeds import norm
from parte_b2_mineracao_multi_fonte import REGRAS_V2
from parte_b2_mineracao_multi_fonte import classificar as classificar_b2

BASE = Path(__file__).resolve().parent.parent
DATA_INCLUSAO = "2026-07-21"

FONTES = [
    ("amazon", BASE / "02_Dados" / "raw" / "tcc_bronze_amazon_distinct_2026-07-21.json"),
    ("shopee", BASE / "02_Dados" / "raw" / "tcc_bronze_shopee_distinct_2026-07-21.json"),
]
SNAP_10 = BASE / "02_Dados" / "raw" / "tcc_bronze_shopee_distinct_2026-07-10.json"
SNAP_15 = BASE / "02_Dados" / "processado" / "parte_b2_classificacao_por_produto.csv"
OUT_NOVOS = BASE / "02_Dados" / "processado" / "parte_b3_termos_novos.csv"
OUT_AUDIT = BASE / "02_Dados" / "processado" / "parte_b3_classificacao_por_produto.csv"

# ------------------------------------------------------------------------------
# Regras novas (v3): cada uma nasceu de um bestseller órfão real de 21/07.
# Formato: (regex, termo canônico, categoria da Parte A).
# Categorias válidas, as 15 que já aparecem em v1/v2: Eletrônicos, Câmeras e óptica,
# Casa e jardim, Móveis, Saúde e beleza, Alimentos e bebidas, Vestuário e acessórios,
# Malas e bolsas, Artigos esportivos, Brinquedos e jogos, Infantil,
# Veículos e peças, Ferragens, Materiais de escritório, Animais e pet.
#
# A 16ª categoria ativa da Parte A, Artes e entretenimento, ganhou regra em 30/09:
# é a `REGRAS_ARTES`, no fim deste bloco. Até então não havia regra para ela, aqui nem
# na v1/v2, e a vitrine `musical-instruments` (Instrumentos Musicais, 50
# produtos/rodada desde 16/07) tinha órfãos e erros.
# ------------------------------------------------------------------------------
REGRAS_V3 = [
    # --- ANIMAIS E PET ---
    # A posição na lista não dá precedência: `classificar` decide por posição no
    # título, depois por comprimento do match. "tapete higienico" ganha de "tapete"
    # porque o match é maior, não porque vem antes (a ordem só importa para leitura).
    (r"\btapete higienico\b", "tapete higienico para caes", "Animais e pet"),
    # Ração e petisco são separados por espécie (desde 28/08). Nos 44 itens da Amazon
    # que caíam no antigo `racao e petisco para pet`, 40 eram comida (ração, petisco,
    # sachê, biscoito) e se separam sem ambiguidade em 29 gato e 11 cachorro; 4 eram
    # coleira antiparasitária (Seresto, Scalibor), que foram para o termo já existente
    # `antipulgas para pet`, onde estão 17 itens do mesmo tipo (Bravecto, NexGard,
    # Simparic). Por isso `\bcoleira\b` não está aqui e as marcas estão lá.
    # A marca decide a espécie quando o título não diz: `Friskies`/`Whiskas` são gato e
    # `Pedigree` é cão. Sem isso, `Pack Ração Friskies Filhotes` e `Ração Special Dog`
    # ficariam órfãos.
    # `\bareia\b` fica de fora: com a geometria atual do match, ele tiraria 5 areias
    # higiênicas do termo `arranhador para gatos`, onde já estão classificadas, e areia
    # não é ração. A regra foi medida nos dois sentidos: quem passa a entrar e quem
    # deixa de sair.
    (r"(\bracao\b|\bpetisco\b|\bsache\b|\bbiscoito\b).*(\bgatos?\b|felin)|"
     r"(\bgatos?\b|felin).*(\bracao\b|\bpetisco\b|\bsache\b|\bbiscoito\b)|"
     r"\bwhiskas\b|\bfriskies\b", "racao para gato", "Animais e pet"),
    (r"(\bracao\b|\bpetisco\b|\bsache\b|\bbiscoito\b).*(\bcao\b|\bcaes\b|cachorr|canin|\bdog\b)|"
     r"(\bcao\b|\bcaes\b|cachorr|canin|\bdog\b).*(\bracao\b|\bpetisco\b|\bsache\b|\bbiscoito\b)|"
     r"\bpedigree\b", "racao para cachorro", "Animais e pet"),
    # --- INFANTIL ---
    (r"\bfralda\b", "fralda descartavel", "Infantil"),
    (r"\blencos? umedecidos?\b", "lenco umedecido", "Infantil"),
    (r"\bmamadeira\b|\bchupeta\b", "mamadeira", "Infantil"),
    (r"\bpelucia\b|\bbrinquedo\b.*\bbebe\b", "pelucia", "Brinquedos e jogos"),
    # --- ELETRÔNICOS ---
    (r"\becho (dot|show|studio|pop|hub|spot|buds)\b|\bamazon echo\b|\bsmart speaker\b|\balexa\b", "smart speaker alexa", "Eletrônicos"),
    (r"\bkindle\b.*\b(paperwhite|scribe|colorsoft|oasis|\d+ ?gb|tela)\b|\bpaperwhite\b|\bcolorsoft\b", "leitor de ebook kindle", "Eletrônicos"),
    (r"\bmouse\b", "mouse", "Eletrônicos"),
    (r"\bteclado\b", "teclado", "Eletrônicos"),
    (r"\bcamera\b.*\b(seguranca|ip|wi ?fi|externa|vigilancia|monitoramento)\b|\bcamera de seguranca\b", "camera de seguranca", "Eletrônicos"),
    (r"\bcr2032\b|\bbateria\b.*\b(litio|recarregavel|cr\d)\b", "bateria de litio", "Eletrônicos"),
    (r"\badaptador\b.*\b(usb|energia|tomada|tipo c)\b", "adaptador usb", "Eletrônicos"),
    (r"\btablet\b", "tablet", "Eletrônicos"),
    # --- SAÚDE E BELEZA ---
    (r"\bsabonete\b", "sabonete", "Saúde e beleza"),
    (r"\bgel de limpeza\b|\blimpeza facial\b|\bagua micelar\b|\bacido hialuronico\b|\bhialuronico\b", "gel de limpeza facial", "Saúde e beleza"),
    (r"\bescova de dentes\b|\bcreme dental\b|\bpasta de dente\b|\bfio dental\b|\benxaguante\b", "escova de dentes", "Saúde e beleza"),
    (r"\bdesodorante\b|\bantitranspirante\b", "desodorante", "Saúde e beleza"),
    (r"\babsorvente\b", "absorvente", "Saúde e beleza"),
    # --- CASA E JARDIM: limpeza e lavanderia ---
    (r"\blava loucas?\b|\bdetergente\b|\bfinish\b", "detergente lava loucas", "Casa e jardim"),
    (r"\bsabao\b.*\b(liquido|po|roupa)\b|\bomo\b|\bariel\b", "sabao de roupa", "Casa e jardim"),
    (r"\bamaciante\b|\bcomfort\b|\bdowny\b", "amaciante de roupa", "Casa e jardim"),
    (r"\bmop\b|\bvassoura\b|\brodo\b|\besfregao\b", "mop de limpeza", "Casa e jardim"),
    (r"\bescova\b.*\blimpeza\b|\bescova de limpeza\b", "escova de limpeza", "Casa e jardim"),
    (r"\blixeira\b", "lixeira", "Casa e jardim"),
    # --- CASA E JARDIM: cozinha e eletrodomésticos ---
    (r"\bdepurador\b|\bcoifa\b|\bexaustor\b", "depurador de ar", "Casa e jardim"),
    (r"\bmicro ?ondas\b", "micro ondas", "Casa e jardim"),
    (r"\bforno eletrico\b|\bforno\b.*\beletrico\b", "forno eletrico", "Casa e jardim"),
    (r"\bgeladeira\b|\brefrigerador\b|\bfrigobar\b", "geladeira", "Casa e jardim"),
    (r"\bfrigideira\b", "frigideira", "Casa e jardim"),
    (r"\bpanela de arroz\b", "panela eletrica de arroz", "Casa e jardim"),
    (r"\bpanela\b", "panela", "Casa e jardim"),
    (r"\bfaqueiro\b|\btalheres\b", "faqueiro", "Casa e jardim"),
    (r"\bgarrafa termica\b|\bcopo termico\b", "garrafa termica", "Casa e jardim"),
    (r"\bforma\b.*\b(bolo|pudim|silicone|airfryer|forno)\b|\bassadeira\b|\btravessa\b|\brefratario\b", "forma de bolo", "Casa e jardim"),
    (r"\bxicara\b", "xicara", "Casa e jardim"),
    (r"\btorneira\b", "torneira", "Casa e jardim"),
    (r"\bpapel toalha\b", "papel toalha", "Casa e jardim"),
    # --- CASA E JARDIM: casa, cama, banho, decoração ---
    (r"\borganizador\b|\bcesto\b", "organizador", "Casa e jardim"),
    (r"\btapete\b", "tapete", "Casa e jardim"),
    (r"\bcortina\b|\bpersiana\b", "cortina", "Casa e jardim"),
    (r"\btoalha\b.*\b(banho|rosto|algodao)\b|\btoalha de banho\b", "toalha de banho", "Casa e jardim"),
    (r"\bcobertor\b|\bmanta\b|\bedredom\b|\bcoberdrom\b", "cobertor e manta", "Casa e jardim"),
    (r"\blencol\b|\bjogo de cama\b|\bfronha\b", "jogo de cama", "Casa e jardim"),
    (r"\balmofada\b", "almofada", "Casa e jardim"),
    (r"\bcabides?\b", "cabide", "Casa e jardim"),
    (r"\bluminaria\b|\blustre\b|\blampada\b|\barandela\b", "luminaria", "Casa e jardim"),
    (r"\bumidificador\b|\bdifusor\b.*\bambiente\b|\baromatizador\b.*\bambiente\b", "umidificador de ar", "Casa e jardim"),
    (r"\bclimatizador\b", "climatizador de ar", "Casa e jardim"),
    # --- CASA E JARDIM: jardim ---
    (r"\badubo\b|\bfertilizante\b|\bsubstrato\b", "adubo e fertilizante", "Casa e jardim"),
    (r"\bmangueira\b.*\bjardim\b|\bmangueira de jardim\b", "mangueira de jardim", "Casa e jardim"),
    (r"\bvaso\b.*\b(planta|decorativo|flor)\b|\bcachepot\b", "vaso de planta", "Casa e jardim"),
    # --- MÓVEIS ---
    (r"\bsofa\b", "sofa", "Móveis"),
    (r"\brack\b|\bestante\b", "rack para tv", "Móveis"),
    (r"\bguarda ?roupa\b|\bsapateira\b|\barmario\b", "guarda roupa", "Móveis"),
    (r"\bprateleira\b", "prateleira", "Móveis"),
    (r"\bcolchao\b", "colchao", "Móveis"),
    (r"\bbanqueta\b|\bpuff\b|\bpoltrona\b", "poltrona", "Móveis"),
    # --- VESTUÁRIO E ACESSÓRIOS ---
    (r"\brelogio\b", "relogio de pulso", "Vestuário e acessórios"),
    (r"\bblusa\b.*\b(termica|frio)\b|\bsueter\b|\btricot\b|\bcasaco\b|\bjaqueta\b", "blusa de frio", "Vestuário e acessórios"),
    (r"\bpantufas?\b|\bpijama\b|\bcamisola\b|\bbaby doll\b", "pijama", "Vestuário e acessórios"),
    (r"\bpulseira\b|\bcolar\b|\bbrinco\b|\banel\b.*\b(prata|aco|ouro)\b|\bcorrente\b.*\b(prata|aco|ouro)\b", "pulseira e colar", "Vestuário e acessórios"),
    (r"\boculos\b", "oculos", "Vestuário e acessórios"),
    (r"\bshort\b.*\b(couro|saia)\b|\bshort saia\b", "short feminino", "Vestuário e acessórios"),
    # --- MALAS E BOLSAS ---
    (r"\bbolsa\b|\bcarteira\b.*\b(feminina|masculina|couro)\b", "bolsa feminina", "Malas e bolsas"),
    # --- MATERIAIS DE ESCRITÓRIO ---
    (r"\bcaneta\b", "caneta", "Materiais de escritório"),
    (r"\blapis\b", "lapis", "Materiais de escritório"),
    (r"\bpapel sulfite\b|\bpapel a4\b|\bsulfite\b|\bchamex\b", "papel sulfite", "Materiais de escritório"),
    (r"\bcaderno\b", "caderno", "Materiais de escritório"),
    (r"\bcola\b.*\b(madeira|branca|isopor|quente|super|instantanea)\b|\bcascola\b|\bsuper bonder\b", "cola", "Materiais de escritório"),
    (r"\bapontador\b|\bmarca ?texto\b|\bcanetinha\b", "material escolar", "Materiais de escritório"),
    # --- ALIMENTOS E BEBIDAS ---
    (r"\bcafe\b.*\b(torrado|moido|graos|capsula|gourmet|soluvel|\dg|kg)\b|\bcafe torrado\b|\bcafe em po\b", "cafe", "Alimentos e bebidas"),
    (r"\benergetico\b|\bred bull\b|\bmonster energy\b", "energetico", "Alimentos e bebidas"),
    (r"\bwhisky\b|\bvodka\b|\bcerveja\b|\bgin\b|\btequila\b|\bvinho\b|\bwhiskey\b", "bebida alcoolica", "Alimentos e bebidas"),
    # --- VEÍCULOS E PEÇAS ---
    (r"\bcheirinho\b.*\bcarro\b|\baromatizante\b.*\b(carro|automotivo)\b", "aromatizante automotivo", "Veículos e peças"),
    # --- FERRAGENS ---
    (r"\bchave de fenda\b|\bchave philips\b", "chave de fenda", "Ferragens"),
    (r"\bbrocas?\b|\bkit de bits\b", "kit de brocas", "Ferragens"),

    # === Segunda passada (21/07): tipos frequentes que sobraram no resíduo ===
    # Saúde e beleza
    (r"\baparelho de barbear\b|\bbarbeador\b|\bgillette\b|\bprestobarba\b|\blamina\b.*\bbarbear\b", "aparelho de barbear", "Saúde e beleza"),
    (r"\bcreme de tratamento\b|\boleo\b.*\bcabelo\b|\bfinalizador\b.*\bcabelo\b|\bumidificacao capilar\b", "creme de tratamento capilar", "Saúde e beleza"),
    # Casa e jardim
    (r"\bdesinfetante\b|\bpinho sol\b|\bagua sanitaria\b|\bcandida\b", "desinfetante", "Casa e jardim"),
    (r"\binseticida\b|\brepelente\b|\bmata barata\b|\braid\b|\bdedetizacao\b|\boleo de neem\b", "inseticida e repelente", "Casa e jardim"),
    (r"\bsacos? de lixo\b|\bsaco lixo\b", "saco de lixo", "Casa e jardim"),
    (r"\bferro\b.*\bpassar\b", "ferro de passar roupa", "Casa e jardim"),
    (r"\bcoador\b|\bfiltro\b.*\bcafe\b", "coador de cafe", "Casa e jardim"),
    (r"\bralo\b.*\b(pia|cozinha|banheiro)\b", "ralo de pia", "Casa e jardim"),
    # Eletrônicos
    (r"\bimpressora\b", "impressora", "Eletrônicos"),
    (r"\bsuporte\b.*\btv\b|\bsuporte de parede\b.*\b(tv|monitor)\b", "suporte de parede para tv", "Eletrônicos"),
    (r"\bfiltro de linha\b|\bextensao\b.*\btomada\b|\bregua\b.*\btomada\b|\bpowercube\b|\bmultiplicador\b.*\btomada\b", "filtro de linha", "Eletrônicos"),
    (r"\bcabo de rede\b|\bpatch cord\b|\bcabo ethernet\b", "cabo de rede", "Eletrônicos"),
    # Ferragens
    (r"\bfechadura\b", "fechadura digital", "Ferragens"),
    (r"\bluva\b.*\b(latex|nitrilica|procedimento|seguranca|descartavel)\b", "luva de seguranca", "Ferragens"),
    # Animais e pet
    # `seresto` e `scalibor` (desde 28/08) são as coleiras antiparasitárias. As 2
    # Seresto já casariam por `carrapatos`; as 2 Scalibor dizem "Antiparasitária
    # contra mosquitos" e não casavam nada, por isso a marca. Acréscimo aditivo:
    # nenhum item já classificado muda de termo.
    (r"\bantipulgas\b|\bcarrapatos?\b|\bvermifugo\b|\bbravecto\b|\bnexgard\b|\bsimparic\b|\bseresto\b|\bscalibor\b", "antipulgas para pet", "Animais e pet"),
    # Alimentos e bebidas
    (r"\bketchup\b|\bmaionese\b|\bmostarda\b|\bmolho\b.*\b(tomate|shoyu|barbecue|ingles)\b", "condimento e molho", "Alimentos e bebidas"),
    # Materiais de escritório
    (r"\bfaber ?castell\b|\bgiz\b|\bhidrocor\b|\bpastel oleoso\b|\bcanetinha\b|\bborracha\b.*\b(escolar|apagar|faber)\b|\blapis de cor\b", "material escolar", "Materiais de escritório"),
    # Brinquedos e jogos
    (r"\bpokemon\b|\btcg\b|\bcartas colecionaveis\b|\bjogo educativo\b|\bjogo pedagogico\b", "jogo educativo e cartas", "Brinquedos e jogos"),
    # Artigos esportivos
    # `squeeze` sozinho não decide o termo. Em PT-BR a palavra designa tanto a
    # garrafa de academia quanto o formato do frasco: medido em 26/08, dos 27 itens da
    # Amazon que caíam no termo esportivo, 8 eram embalagem (`Cif Multiuso - Limpador
    # +Antibac Squeeze 500ml`), 30% de falso positivo no alvo da H1. O achado veio de
    # listar os títulos classificados, não de ler o regex: regra de classificação se
    # audita pelo que ela classificou.
    #
    # Em 28/08 a mesma listagem foi feita para os 19 itens restantes, por ramo:
    # 11 touca, 6 óculos, 2 garrafa. Um nome único (`touca de natacao`) deixaria 6
    # óculos com o termo errado. A regra virou duas, cada uma nomeada pelo que pega.
    # Os ramos `garrafa`/`squeeze` saíram porque pertencem ao `garrafa termica`, que já
    # tinha outros 16 itens iguais; o corte junta os 18 num termo só.
    # `\bnatacao\b` sozinho também saiu: o único item que ele pegava sem touca nem
    # óculos era `Mochila Mala T60 Para Academia Natação Camping`, uma mochila. Tirar o
    # ramo removeu um falso positivo sem custar cobertura.
    # `oculos de natacao` convive com a regra `\boculos\b` (Vestuário): as duas casam
    # na posição 0, e o desempate por match mais longo entrega o item certo.
    (r"\btouca\b.*\bnatacao\b|\bnatacao\b.*\btouca\b", "touca de natacao", "Artigos esportivos"),
    (r"\boculos\b.*\bnatacao\b|\bnatacao\b.*\boculos\b", "oculos de natacao", "Artigos esportivos"),
    # Vestuário e acessórios
    (r"\bmeia\b.*\b(termica|cano|esportiva|soquete)\b", "meias", "Vestuário e acessórios"),
    # Infantil
    (r"\bpomada\b.*\bassadura\b|\bassadura\b", "pomada para assadura", "Infantil"),
]

# --- Artes e entretenimento (30/09/2026) ------------------------------------------
# Cada ramo abaixo nasceu de títulos reais da vitrine `musical-instruments` da Amazon,
# listados antes de o padrão existir.
#
# A listagem mudou o diagnóstico de 24/09: dos 168 itens distintos da vitrine, 118
# caem em "fone de ouvido bluetooth" e estão certos (a Amazon põe áudio dentro de
# "Instrumentos Musicais"), e os microfones também. O erro real era pequeno e
# localizado: amplificadores e pedais de guitarra em "bateria de litio" (7) e
# "smartphone" (2), um suporte de teclado musical em "teclado", um karaokê infantil em
# "conjunto infantil menina", e 27 órfãos (cordas, pedais, capotraste, suportes...).
#
# Medida nos dois sentidos, sobre os 8.658 títulos distintos do Bronze das três
# fontes: 38 títulos mudam, todos da vitrine de instrumentos, e nenhum de outra
# vitrine, da Shopee ou do ML é capturado. Invariante aditiva: 0 quebras em 10/07 e 15/07.
# Os termos são novos e não estão nas sementes: entram no alvo da H1 sem série de
# busca (não pareiam), e o que muda no alvo é a saída dos itens dos termos errados.
# O karaokê vai para Eletrônicos, não para Artes: na taxonomia do Google, sistema de
# karaokê é Electronics > Audio.
_AE = "Artes e entretenimento"
REGRAS_ARTES = [
    # `\bencordoamento` sem fronteira no fim: "ENCORDOAMENTO011-052" cola o calibre
    (r"\bencordoamento|\bcordas?\b.{0,20}\b(violao|guitarra|baixo|cavaquinho|ukulele|viola)\b"
     r"|\b(guitar|bass) strings\b", "encordoamento", _AE),
    (r"\bpedal(eira)?\b.{0,40}\b(guitarra|baixo|efeitos?)\b|\bpedaleira\b|\bmulti.?efeitos?\b"
     r"|\bmodelador de amp\b", "pedaleira para guitarra", _AE),
    (r"\bamplificador\b.{0,40}\b(guitarra|baixo|violao)\b|\b(guitarra|baixo)\b.{0,20}\bamplificador\b",
     "amplificador de guitarra", _AE),
    (r"\bsuporte\b.{0,40}\b(guitarra|violao|baixo|violino|cavaquinho|teclado musical|instrumentos?)\b",
     "suporte para instrumento musical", _AE),
    # três ramos pequenos num termo só; o nome do termo cobre os três
    (r"\bcapotraste\b|\bafinador\b.{0,20}\b(clip|cromatico|violao|guitarra)\b|\bafinador clip\b"
     r"|\bcabo\b.{0,20}\binstrumentos?\b", "acessorio para instrumento musical", _AE),
    (r"\bflauta\b", "flauta doce", _AE),
    (r"\bluz (para|de) festa\b", "luz de festa", _AE),
    (r"\bkaraoke\b", "karaoke", "Eletrônicos"),
]

# --- O termo "microfone de lapela" (30/09/2026) ---------------------------------------
# A regra da Parte B (10/07) é `\bmicrofone\b` sozinho, e mandava para "microfone de
# lapela" qualquer título com a palavra. Medido nas três fontes: dos 25 itens distintos
# do termo, só 12 eram microfone de lapela. Os outros: headphones com microfone, webcams
# com microfone, suportes de microfone, microfones USB e de mão, e um kit de estúdio. O
# nome do termo não cobria os ramos do padrão.
# A regra de 10/07 não se edita, porque a Parte B garante reprodução byte a byte. A
# correção vem por regras mais longas ou mais cedo no título, que vencem pela lógica do
# `classificar`. Medido nos dois sentidos sobre os 8.658 títulos distintos do Bronze:
# 16 mudam (13 saem de "microfone de lapela" e 3 headphones órfãos ganham termo),
# nenhum sai de outro termo, e os 12 que ficam são todos de lapela; invariante
# aditiva: 0 quebras.
_NAO_LAPELA = r"(?!.*\b(lapela|hollyland|lark)\b)"   # os Hollyland Lark são de lapela sem dizer
REGRAS_MICROFONE = [
    # o fone de 10/07 não conhece a palavra "headphone"
    (r"\bheadphones?\b", "fone de ouvido bluetooth", "Eletrônicos"),
    (r"\bweb ?cam\b", "webcam", "Câmeras e óptica"),
    (r"\b(suporte|braco|pedestal)\b.{0,30}\bmicrofones?\b", "suporte para microfone", "Eletrônicos"),
    (r"\bkit\b.{0,30}\b(estudio|live|vlog)\b", "kit para live e vlog", "Câmeras e óptica"),
    (r"\bmicrofones?\b" + _NAO_LAPELA
     + r".{0,40}\b(usb|xlr|condensador|gamer|dinamico|podcast|podcasting|jogos|streaming)\b",
     "microfone usb", "Eletrônicos"),
    (r"\bmicrofones?\b" + _NAO_LAPELA + r".{0,40}\b(karaoke|de mao|uhf|partybox)\b",
     "microfone sem fio de mao", "Eletrônicos"),
]

REGRAS_B3 = REGRAS_V1 + REGRAS_V2 + REGRAS_V3 + REGRAS_ARTES + REGRAS_MICROFONE
REGRAS_COMP = [(re.compile(rx), termo, cat) for rx, termo, cat in REGRAS_B3]
# O classificador como era até 29/09, sem as duas regras de 30/09 (artes e microfone).
# Mantém o experimento 1 do lead-lag (08/09) e a reanálise de 17/09 reproduzíveis, via
# `alvo_h1.construir_alvo(..., com_regras_artes=False)`, como a §8b fez com o ML
# (`com_mercado_livre=False`). O nome diz "artes" por origem; a mesma chave cobre as
# duas regras do dia (§8g do protocolo).
REGRAS_COMP_SEM_ARTES = REGRAS_COMP[: len(REGRAS_COMP) - len(REGRAS_ARTES) - len(REGRAS_MICROFONE)]


def classificar(titulo_norm: str, regras=None):
    """Mesma lógica de B/B2: vence o match de menor posição; no empate, o mais longo.

    `regras=None` é o classificador vigente; `REGRAS_COMP_SEM_ARTES` reproduz o de antes
    de 30/09."""
    melhor = None
    for rx, termo, cat in (REGRAS_COMP if regras is None else regras):
        m = rx.search(titulo_norm)
        if m:
            cand = (m.start(), -(m.end() - m.start()), termo, cat, rx.pattern)
            if melhor is None or cand < melhor:
                melhor = cand
    return (None, None, None) if melhor is None else (melhor[2], melhor[3], melhor[4])


def _checar_invariante_aditiva():
    """Aborta se alguma regra v3 reclassificou um produto que a B2 ja classificava.
    Confere contra os 67 de 10/07 e os 257 de 15/07 (a auditoria congelada da B2)."""
    quebras = []
    # 10/07 (Shopee)
    for p in json.loads(SNAP_10.read_text(encoding="utf-8")):
        t = norm(p["product_name"])
        antes, agora = classificar_b2(t)[0], classificar(t)[0]
        if antes is not None and antes != agora:
            quebras.append(("10/07", p["product_name"][:55], antes, agora))
    # 15/07 (auditoria congelada da B2: fonte, termo)
    with SNAP_15.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            antes = row["termo"] or None
            if antes is None:
                continue
            agora = classificar(norm(row["product_name"]))[0]
            if antes != agora:
                quebras.append(("15/07", row["product_name"][:55], antes, agora))
    return quebras


def main():
    quebras = _checar_invariante_aditiva()
    if quebras:
        print(f"!!! INVARIANTE ADITIVA QUEBRADA em {len(quebras)} produto(s) — regra v3 reclassificou algo antigo:")
        for data, nome, antes, agora in quebras[:30]:
            print(f"   [{data}] {nome!r}: {antes!r} -> {agora!r}")
        raise SystemExit("Corrija as REGRAS_V3 (torne-as mais especificas/ancoradas) antes de prosseguir.")
    print("OK: invariante aditiva preservada (0 reclassificacoes de 10/07 e 15/07).\n")

    produtos = []
    for fonte, caminho in FONTES:
        for p in json.loads(caminho.read_text(encoding="utf-8")):
            nome = p.get("product_name")
            if nome and str(nome).strip():
                produtos.append({"fonte": fonte, "item_id": p.get("item_id"), "product_name": nome})

    agg = defaultdict(lambda: {"categoria": None, "suporte": 0, "fontes": set(), "exemplos": []})
    audit, orfaos = [], []
    novos_v3 = 0
    for p in produtos:
        termo, categoria, patt = classificar(norm(p["product_name"]))
        audit.append({"fonte": p["fonte"], "item_id": p["item_id"], "product_name": p["product_name"],
                      "termo": termo or "", "categoria": categoria or ""})
        if termo is None:
            orfaos.append(p)
            continue
        a = agg[termo]
        a["categoria"] = categoria
        a["suporte"] += 1
        a["fontes"].add(p["fonte"])
        if len(a["exemplos"]) < 2:
            a["exemplos"].append(p["product_name"][:60])

    OUT_AUDIT.parent.mkdir(parents=True, exist_ok=True)
    with OUT_AUDIT.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["fonte", "item_id", "product_name", "termo", "categoria"])
        w.writeheader(); w.writerows(audit)

    # termos que não existiam antes da v3 (só aparecem porque a v3 os criou)
    termos_v3 = {t for _, t, _ in REGRAS_V3}
    novos = []
    for termo, a in agg.items():
        if termo not in termos_v3:
            continue
        fontes = ",".join(sorted(a["fontes"]))
        novos.append({
            "termo": termo, "categoria": a["categoria"],
            "origem": f"bestseller_{fontes}" if len(a["fontes"]) == 1 else "bestseller_multi",
            "justificativa": (f"Termo emergente de {a['suporte']} bestseller(s) [{fontes}] "
                              f"(Parte B3, 21/07/2026: refresh da amostragem apos a troca de rota da "
                              f"Amazon, que triplicou o universo de produtos). Ex.: {' | '.join(a['exemplos'])}"),
            "ativo": "true", "data_inclusao": DATA_INCLUSAO, "suporte": a["suporte"], "fontes": fontes,
        })
    novos.sort(key=lambda r: (-r["suporte"], r["termo"]))
    with OUT_NOVOS.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["termo", "categoria", "origem", "justificativa", "ativo", "data_inclusao", "suporte", "fontes"])
        w.writeheader(); w.writerows(novos)

    # ---- relatório ----
    n = len(produtos)
    cls = n - len(orfaos)
    for fonte, _ in FONTES:
        tot = sum(1 for p in produtos if p["fonte"] == fonte)
        orf = sum(1 for p in orfaos if p["fonte"] == fonte)
        print(f"{fonte:8s}: {tot-orf}/{tot} classificados = {100*(tot-orf)//tot}%  (orfaos: {orf})")
    print(f"TOTAL   : {cls}/{n} = {100*cls//n}%  | termos distintos: {len(agg)} | termos NOVOS (v3): {len(novos)}")
    print(f"\nTermos NOVOS por suporte:")
    for r in novos:
        print(f"  {r['termo']:32s} {r['categoria']:24s} sup={r['suporte']:4d} [{r['fontes']}]")
    print(f"\nResiduo de orfaos: {len(orfaos)} (amostra):")
    for p in orfaos[:60]:
        print(f"  [{p['fonte']:6s}] {p['product_name'][:66]}")


if __name__ == "__main__":
    main()

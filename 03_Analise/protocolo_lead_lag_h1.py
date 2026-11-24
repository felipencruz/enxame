# -*- coding: utf-8 -*-
"""PROTOCOLO do primeiro experimento de lead-lag da H1, escrito ANTES de rodar.

═══════════════════════════════════════════════════════════════════════════════
ESTE ARQUIVO É O PRÉ-REGISTRO. Ele existe para ser datado pelo git antes de
qualquer resultado aparecer. Regra escolhida depois de ver o resultado é
racionalização, não método.
═══════════════════════════════════════════════════════════════════════════════

A prova de "escrito antes" não é este texto: é o commit. Enquanto este arquivo não
estiver commitado, a afirmação de que as regras foram escritas antes é apenas anotação,
sem prova verificável. Commitar antes de rodar é o que a torna verificável, porque a data
passa a ser carimbada por algo que o autor não controla.

-------------------------------------------------------------------------------
1. O QUE ESTE EXPERIMENTO É, E O QUE ELE NÃO É
-------------------------------------------------------------------------------

É exploratório (definido em 08/09): este é apenas o primeiro experimento, e haverá novo
teste adiante.

Consequência, e ela é a proteção mais valiosa deste documento:

* Este experimento gera a hipótese específica: qual operacionalização, qual lag, qual
  sinal. Ele não a confirma, e nenhum resultado dele se reporta como confirmação.
* O experimento 2 (confirmatório) a testa em dado que ainda não existe, com a
  operacionalização e o lag fixados por este, sem nova busca.

Qualquer p-valor que sair daqui é descritivo. Escolher o melhor de três
operacionalizações × quinze lags e depois reportar a significância dele é o defeito que a
banca cobra primeiro. A defesa não é estatística, é de desenho: o achado se sustenta na
replicação, e é por isso que a §5 abaixo existe.

A condição de reabertura, em forma verificável, tem um problema que precisa estar
escrito: o alvo (venda) cresce todo dia, mas a série do Trends é estática: a coleta
manual encerrou em 07/09 e termina em `2026-09-06`. Logo o experimento 2 não acontece só
esperando; ele exige busca nova.

    O experimento 2 pode rodar quando houver ≥ 30 dias de Trends posteriores a
    2026-09-06 para ≥ 60 termos do alvo, por qualquer via: nova coleta manual
    (`PLANO_TRENDS.md`) ou a API oficial do Google Trends.

Sem essa condição, "testar de novo adiante" envelheceria como razão de adiar sem prazo.

-------------------------------------------------------------------------------
2. AS TRÊS OPERACIONALIZAÇÕES DO MOMENTUM
-------------------------------------------------------------------------------

Notação: `x_t` = índice Trends do termo no dia `t`, dentro de um bloco (o arquivo-dono
de uma metade). `MM7_t` = média trailing dos 7 dias que terminam em `t`.

    A. MÉDIA MÓVEL ............ A_t = MM7_t / MM7_{t-7} - 1
    B. VARIAÇÃO PERCENTUAL .... B_t = x_t / x_{t-7} - 1
    C. DESVIO SOBRE A BASE .... C_t = (MM7_t - média(MM7_{t-14..t-1}))
                                      / desvio(MM7_{t-14..t-1})

Por que todas têm passo 7: é medição, não preferência. O passo 2 mediu que o dia da
semana explica 36% da variância (η² mediana, 158 de 208 séries acima de 0,20).
Qualquer definição com passo 1 mediria calendário e chamaria de demanda. Com passo 7:
* A e C usam MM7, que anula o ciclo por construção (média de 7 dias consecutivos);
* B compara `t` com `t-7`, ou seja, o mesmo dia da semana: o ciclo cancela na razão.

Nenhuma das três estima fator sazonal. Estimar sazonalidade sobre a série inteira
usaria o futuro para limpar o passado; estimá-la trailing gastaria 21 dias dos 38 da metade
`a`. Passo 7 resolve o calendário sem estimar nada, e essa é a razão de o desenho ter
esta forma e não outra.

Por que as três são comparáveis: o Trends é 0–100 relativo ao máximo do próprio
lote, então nível não é comparável entre termos. As três são invariantes a escala
multiplicativa (A e B são razões; C tem numerador e denominador escalando junto), o que
é o que permite pôr 129 termos no mesmo painel sem âncora.

Por que as três são diferentes, e por isso testá-las tem valor:
* A mede crescimento da base suavizada: explora o sinal lento, descarta o rápido.
* B mede crescimento ponto a ponto: preserva o rápido, e com ele o ruído.
* C mede anomalia contra a própria história recente: indiferente ao nível.

Custo em observações, medido e não estimado (`momentum_busca.custo_das_operacionalizacoes`),
em mediana de pontos por termo e total de observações:

    operacionalizacao   metade  termos   obs   mediana pts/termo
    A_media_movel         a       105    2046        25
    A_media_movel         b       115     731         8
    B_variacao_pct        a       119    3465        31
    B_variacao_pct        b       116    1493        14
    C_desvio_base         a        97    1291        18
    C_desvio_base         b        87      87         1

Esta tabela foi medida depois de a primeira redação deste bloco ter estimado os custos
sem medir, e a estimativa errou dois valores: C na metade `a` foi estimado em ~17 pts
(são 18) e C na metade `b` em 0 pts (é 1). Estimativa dentro de um pré-registro é
afirmação sem verificação, e a correção foi rodar o código antes de commitar, não depois.

C é, na prática, um teste só da metade `a`: 1 ponto por termo na `b` não é série.
Isso é resultado do desenho, não defeito: se C ficar sem poder, a conclusão honesta
é "a série atual não sustenta esta operacionalização", e isso é um achado, não uma falha a
ser contornada. A metade `b` também contribui pouco para todas: 8 pontos por termo em A,
14 em B. O peso do experimento está na metade `a`, e isso se declara no relatório.

-------------------------------------------------------------------------------
3. AS REGRAS QUE VALEM PARA TODAS AS TRÊS
-------------------------------------------------------------------------------

R1. Toda janela é trailing. Nenhuma média, desvio ou suavização usa o dia corrente
para além de `t`, e `center=True` está proibido. Reparo que preenche o passado com o
futuro é vazamento, e num teste de lead-lag ele invalida o resultado. O projeto já teve
esse caso no backfill do título, que tinha 85,3% de recuperação e 99,2% de estabilidade
e ainda assim era não-causal.

R2. Nenhuma janela atravessa a emenda. O `16/08/2026` está quebrado na fonte e as duas
metades têm escalas próprias. Toda janela vive dentro de um bloco; os primeiros k-1 dias
de cada bloco ficam nulos. Mecanizado pela coluna `bloco` do
`momentum_busca.carregar_trends`, não por checagem de data espalhada.

R3. Nulo nunca vira zero. Dia anômalo e zero suspeito entram como nulo, pelas réguas do
`conferir_trends.py`. Zero falso vira queda falsa e contamina a correlação (a armadilha
do `sales`).

R4. O alvo não é suavizado. Suavizar os dois lados infla a autocorrelação de ambos e
espalha a correlação cruzada por vários lags (efeito Slutsky-Yule): a correlação sobe sem
que nada tenha melhorado. Só a variável líder é suavizada, e só porque a medição do passo
2 mostrou que o delta diário dela é ruído (autocorrelação lag-1 = -0,44 depois de tirar o
calendário). Suavizar o alvo seria experimento novo, não variante.

R5. O alvo é `alvo_unificado` do `alvo_h1.py`, por (termo, dia), sem imputação: as 8
regras da §3.4 da especificação da Silver, que já existiam antes deste protocolo.

-------------------------------------------------------------------------------
4. O TESTE
-------------------------------------------------------------------------------

Unidade: o termo. Para cada termo e cada lag `k`, a correlação de Spearman entre
`momentum(t-k)` e `alvo(t)`, calculada dentro do bloco e agrupando os blocos do mesmo
termo (pares, não séries concatenadas: a emenda não gera par).

Spearman porque o alvo é percentil e o momentum tem cauda pesada; sem scipy no venv de
análise, ele é Pearson sobre os postos.

Grade de lags: `k = 0, 1, ..., 14`. Quinze lags, cobrindo duas semanas: o horizonte em
que "a busca antecipa a venda" é economicamente interpretável para e-commerce.

Agregação entre termos: a mediana das correlações por termo, e a fração de termos
com correlação positiva. Mediana porque a distribuição entre termos é assimétrica; a
fração porque ela é o teste de sinal, que não assume forma nenhuma.

Estatística primária: `max_k mediana(ρ_k)` para `k >= 1`, na operacionalização A.

Por que A é a primária, e a razão é a medição do passo 2: o sinal que existe nesta
série é lento (`desvio(MM7)/desvio(bruto) = 0,469` contra 0,378 do ruído puro) e o
delta diário é ruído (-0,44). A é a definição que explora a parte que tem sinal.
B e C são robustez. Se as três concordarem, o achado é robusto; se divergirem, a
divergência é o achado, e nos dois casos se reportam as três.

Exclusão declarada: `k = 0` não conta para a primária, porque correlação contemporânea
não é lead-lag e não sustenta "antecipa". Mas ele não é descartável: `k = 0` é o desenho
de Choi & Varian, ou seja, o benchmark da literatura (§7). Reporta-se sempre, como a
régua contra a qual se lê o resto: o que este trabalho acrescenta é o que sobra depois
de k = 0.

-------------------------------------------------------------------------------
5. OS PLACEBOS, e é aqui que este experimento se defende
-------------------------------------------------------------------------------

P1. Lags invertidos. O mesmo pipeline com `k = -1, ..., -7` (a venda antecedendo a
busca). Se o efeito for igual nos dois sentidos, não há direção, e "antecipa" cai.

P2. Alvo embaralhado entre termos. Reatribuir as séries de alvo a termos errados,
mantendo cada série intacta, e rodar tudo de novo: 1.000 permutações.

P2 faz duas coisas ao mesmo tempo, e a segunda é a que resolve o problema difícil:

1. diz se o "achado" sobrevive quando o pareamento termo↔termo é destruído: se sobreviver,
   ele é artefato de calendário comum, não demanda;
2. resolve a multiplicidade sem Bonferroni. A estatística primária é um máximo
   sobre 15 lags, e comparar cada lag contra um p-valor nominal acharia significância por
   acaso. Com a permutação, compara-se o máximo observado contra a distribuição do
   máximo sob o nulo, que já embute a busca pelos 15 lags.

Critério, escrito agora: o achado é considerado digno de replicação se o máximo
observado ficar acima do percentil 95 da distribuição permutada e o lag do máximo
for `k >= 1`. Nada aqui é "confirmado": o experimento é exploratório por decisão, e a
confirmação é o experimento 2.

-------------------------------------------------------------------------------
6. O QUE SE REGISTRA ANTES DE OLHAR O RESULTADO
-------------------------------------------------------------------------------

Registrar a predição é o que distingue previsão de narrativa depois do fato.

* Direção esperada: correlação positiva, com o máximo em `k` entre 1 e 7.
* O que refutaria a H1 neste dado: máximo dentro do envelope permutado (P2), ou efeito
  simétrico entre `k` e `-k` (P1), ou máximo em `k = 0`.
* O que não refuta: as três operacionalizações discordarem; isso é informação sobre
  qual escala do sinal carrega a antecipação, e se reporta como tal.
* Limitação que já se sabe e vai no relatório: 59 dias em dois blocos, um deles de 21;
  C sem observação na metade `b`; e o alvo com churn de item alto (Shopee: mediana de 3
  dias por item), que o torna ruidoso: custa poder, e já está entre as limitações
  declaradas do trabalho.

-------------------------------------------------------------------------------
7. A ÂNCORA TEÓRICA, CONFERIDA NA FONTE em 08/09, e ela muda o que se pode afirmar
-------------------------------------------------------------------------------

O que foi lido: o working paper de 18/12/2011 (`people.ischool.berkeley.edu/
~hal/Papers/2011/ptp.pdf`, 14 páginas), que é a versão pré-publicação do artigo de 2012 no
Economic Record. A citação do TCC é a de 2012: o conteúdo é o mesmo, mas paginação e
frase exata não foram conferidas contra o publicado, que está atrás de paywall. Isso
fica declarado.

O desenho deles, com a equação do próprio texto:

    y_t = b1·y_{t-1} + b12·y_{t-12} + e_t         (baseline: AR-1 sazonal)
    y = LOG do nível (vendas mensais); Trends entra em NÍVEL, contemporâneo

* variável dependente em log, dado mensal, sazonalidade por lag 12;
* o índice do Trends entra em nível e no mesmo período ("the searches from the first
  Sunday-Saturday contained in the month"), ou seja, k = 0;
* avaliação por rolling window out-of-sample, com MAE: 6,34% no baseline contra
  5,66% com Trends (melhora de 10,6%; 21,4% durante a recessão).
* Nenhum momentum, nenhuma média móvel, nenhuma taxa de variação do índice.

A frase que mais importa, literal do abstract/introdução:

    "We are not claiming that Google Trends data can help in predicting the future.
     Rather we are claiming that Google Trends may help in predicting the present."

    "It may also be true that June queries help to predict July sales, but we leave
     that question for future research."

Logo: Choi & Varian fazem nowcasting (k = 0), não lead-lag, e deixam o lead-lag
explicitamente como trabalho futuro.

Isso é posicionamento de contribuição, não fragilidade: a H1 deste trabalho faz
exatamente a pergunta que a referência declarou em aberto. O que não se pode é atribuir a
eles a constatação de que a busca antecipa: eles a recusam por escrito. O apoio que
existe, e é qualificado, é esta frase: "queries can be useful leading indicators for
subsequent consumer purchases in situations where consumers start planning purchases
significantly in advance of their actual purchase decision": compra planejada, que é o
caso do e-commerce, mas não é a tese do paper.

AS TRÊS CONSEQUÊNCIAS PARA ESTE PROTOCOLO:

(a) `k = 0` deixa de ser nota de rodapé e vira benchmark. A §4 o exclui da primária,
e isso continua certo, porque contemporâneo não sustenta "antecipa". Mas k = 0 é
precisamente o que a literatura estabeleceu, então ele se reporta como a comparação:
o que este trabalho acrescenta é o que sobra depois do que já se sabia.

(b) O passo 7 ganha ancoragem na referência. Eles tratam sazonalidade mensal com
`lag 12`; este protocolo trata sazonalidade semanal com passo 7. Mesma lógica, outra
frequência, e agora isso é analogia com a fonte aberta, não invenção nossa.

(c) O desenho deles é mais forte que o nosso num ponto, e isso vai declarado: eles
põem AR na própria variável dependente antes de creditar qualquer ganho ao Trends, e
julgam por erro out-of-sample, não por ajuste. Este experimento usa correlação +
permutação: a permutação cobre multiplicidade e correlação espúria entre séries
autocorrelacionadas (embaralhar preserva a autocorrelação de cada uma e quebra só o
pareamento), mas não controla a inércia do próprio alvo.
O desenho fiel à referência (alvo com AR sazonal de passo 7 como baseline, contra
baseline + momentum de busca, avaliado por MAE em rolling window) é o EXPERIMENTO 2.
Ele é mais caro e exige série maior; registrá-lo aqui é o que impede que "usamos
correlação" vire a escolha permanente por inércia.

-------------------------------------------------------------------------------
7b. O QUE O ARTIGO JÁ ENTREGUE DIZ, conferido no `.docx`, não de memória
-------------------------------------------------------------------------------

O artigo foi aprovado em 07/09 e não se reabre; isto fica registrado para a monografia.

A §2.1 está correta e usa o termo certo: "consagrado por Choi e Varian (2012) sob o
conceito de nowcasting (prever o presente), é aqui adaptado do escopo de séries
agregadas para o recorte específico do e-commerce brasileiro". Nomeia nowcasting e
declara a adaptação, que é exatamente a leitura que a fonte sustenta.

A Introdução é imprecisa, e diz o oposto no mesmo documento: "a constatação de que o
volume de busca antecipa a demanda real (CHOI; VARIAN, 2012)". Eles recusam essa
constatação por escrito. Sustenta-se só na frase qualificada sobre leading indicators em
compra planejada, não na tese do paper. Na monografia, a Introdução se alinha à §2.1,
que já está certa. Não é erro de número: é atribuição de afirmação, que nenhuma
verificação automática do projeto detecta.

-------------------------------------------------------------------------------
8. EMENDAS AO PRÉ-REGISTRO: 08/09/2026, ANTES DE QUALQUER RESULTADO EXISTIR
-------------------------------------------------------------------------------

Isto é uma emenda, e ela se declara em vez de ser editada em silêncio. As duas
lacunas abaixo apareceram ao escrever o runner, e as duas foram fechadas antes de o
experimento rodar uma única vez: o commit desta emenda precede o primeiro resultado,
pelo mesmo motivo que o commit original precedia: a data é carimbada pelo git, não pelo
texto. Se elas tivessem sido fechadas depois de ver o resultado, o experimento inteiro
perderia a prova de anterioridade.

E8.1. Faltava o mínimo de pares por termo, e sem ele a mediana engana.
A §4 manda agregar pela "mediana das correlações por termo" e não dizia quantos pares
um termo precisa ter para entrar nessa mediana. Um termo com 4 pares produz uma
correlação instável, muitas vezes ±1, e ela entra com o mesmo peso de um termo com 40:
é ruído puxando a mediana.

    MINIMO_PARES_POR_TERMO = 10

Escolhido por desenho e não por resultado: 10 é o menor N em que uma correlação de
Spearman tem alguma estabilidade, e é folgadamente menor que a mediana de dias do painel
(51), então ele corta cauda sem escolher população. O mesmo piso vale nos placebos:
aplicar o filtro só no observado e não no permutado inflaria o observado contra um nulo
mais frouxo, que é viés a favor da hipótese.

E8.2. R5 contradiz o artigo aprovado, e prevalece o artigo.
A R5 diz "o alvo é `alvo_unificado`". O artigo entregue diz o contrário, e é ele a
referência deste projeto: "o alvo unificado tornou-se apenas uma conveniência de leitura,
exigindo que a hipótese central reporte as duas fontes lado a lado", porque a
correlação entre Shopee e Amazon é indistinguível de zero (achado ⑤). O projeto já
registrava isso desde 01/09; o protocolo não acompanhou.

Resolução, escrita antes de olhar: a primária continua no `alvo_unificado`, como
o pré-registro commitado manda, e `alvo_shopee` e `alvo_amazon` são reportadas sempre, ao
lado, como o artigo exige.

    ALVOS = ("alvo_unificado", "alvo_shopee", "alvo_amazon")
    ALVO_PRIMARIO = "alvo_unificado"

As duas fontes não são candidatas a "melhor alvo". Elas são reporte obrigatório:
escolher entre três alvos pelo resultado seria triplicar a busca que a permutação existe
para controlar. A permutação (P2) roda sobre a primária. Se as fontes divergirem
entre si, isso é o achado ⑤ aparecendo de novo, e se reporta como tal.

(Anotação de 23/09, sem mudar a regra acima: o texto desta §8 é de 08/09 e fala em "duas
fontes" porque eram duas. Desde 15/09 são três (o ML entrou na §8b), e desde 22/09
o reporte das três é obrigatório, R8d.2. A constante que vale é a do fim do arquivo,
com os quatro alvos.)

-------------------------------------------------------------------------------
§8b. EMENDA DE 15/09/2026: o Mercado Livre entra como TERCEIRA fonte de alvo
     (numerada 8b, e nao 9, de proposito: a §9 ja existia e e citada em outros
      documentos, e renumerar quebraria a citacao)
-------------------------------------------------------------------------------

Motivação, registrada em 15/09: o ML entrava somente no confronto oferta × demanda, e
agora deve entrar no mesmo patamar de Amazon e Shopee.

E9.1. `ALVOS` passa a incluir `alvo_ml`; a primária continua o `alvo_unificado`.

    ALVOS = ("alvo_unificado", "alvo_shopee", "alvo_amazon", "alvo_ml")
    ALVO_PRIMARIO = "alvo_unificado"      # inalterado

Esta emenda é posterior ao experimento 1, e isso precisa ser dito explicitamente.
Mudar o alvo depois de ver um resultado é exatamente o que um pré-registro existe
para impedir; então a declaração vem com as duas leituras, e quem julga é quem lê:

* O que defende a emenda: ela não escolhe uma especificação entre as que já existiam;
  ela acrescenta uma fonte que não existia como dado até 15/09. A posição no carrossel
  do ML sempre esteve no Bronze, mas não estava recuperada: ela foi derivada da ordem de
  inserção e provada contra o HTML bruto de 29/07. Um alvo novo nasceu; nenhum alvo
  antigo foi trocado por render mais.
* O que a acusa, e continua de pé: o experimento 1 deu negativo, e qualquer
  mudança no alvo depois disso é legível como "mexer até dar certo". A defesa não é
  retórica, é procedimento: (a) o resultado de 08/09 não se reescreve; o artefato
  `02_Dados/resultado_lead_lag_h1.json` fica como está; (b) `construir_alvo(...,
  com_mercado_livre=False)` reproduz o alvo que ele usou, e há teste travando isso;
  (c) o experimento 1 refeito com três fontes, se for feito, é reanálise exploratória
  e se reporta com esse nome, nunca no lugar do resultado original.

O custo, medido antes de aplicar: cada fonte que entra reduz a variância do unificado
por composição, não por mercado. Nos termo-dia em que as três observam, o desvio-padrão
cai de 0,1519 para 0,1256. E a série passa a ter três composições: Shopee sozinha até
14/07, +ML em 15/07, +Amazon em 16/07. O painel balanceado corta as três na data comum,
que continua sendo 16/07 porque a Amazon é a última a entrar.

O unificado também fica menos interpretável, o que é argumento a favor da alternativa da
Q1: com três fontes, só 943 de 11.715 termo-dia têm as três, e 7.265 têm uma só.
A média de "fontes disponíveis" é, na maior parte do painel, uma fonte só, e agora isso
é medido, não impressão. A saída oposta (abandonar o unificado e ter uma primária por
fonte) segue escrita na Q1 e passou a ter três candidatas em vez de duas.

-------------------------------------------------------------------------------
§8c. 17/09/2026: A REANALISE COM TRES FONTES FOI AUTORIZADA, e esta secao e
     escrita ANTES de ela rodar (mesma ordem do experimento 1, em 08/09)
-------------------------------------------------------------------------------

Decisão de 17/09: refazer todo o cálculo e a análise feitos até então com o ML no novo
patamar; o artigo pode ser atualizado para a monografia.

Isto fecha a pergunta aberta desde 15/09 (refazer agora ou esperar o experimento 2?),
e a resposta é: refazer agora, como reanálise. A cláusula (c) da §8b previa exatamente
este caso; o que segue é a ativação dela, com o que não se negocia escrito antes de
existir resultado.

R8c.1. A reanálise não é o experimento 1, e não ocupa o lugar dele.
  O artefato `02_Dados/resultado_lead_lag_h1.json` (08/09, duas fontes) fica como está.
  A reanálise grava `resultado_lead_lag_h1_reanalise_3fontes.json` e
  `comparacao_lead_lag_h1_reanalise_3fontes.csv`. Os dois artefatos coexistem, e cada um
  declara `fontes_do_alvo` no próprio corpo.
  Desde 17/09 isto não depende de disciplina: o gravador é fail-closed. Até aquele dia o
  runner escrevia em caminho fixo, e rodá-lo teria apagado a prova do experimento 1, que
  está commitada.

R8c.2. A primária não muda, e isso é o que separa reanálise de garimpo.
  Continua `A_media_movel | alvo_unificado`, com `k >= 1`, os mesmos 15 lags, o mesmo
  `MINIMO_PARES_POR_TERMO = 10` e os mesmos dois placebos. A única coisa que muda é a
  composição do alvo, que é o objeto da emenda §8b, não uma escolha feita agora.
  A Q2 da §9 (trocar a primária de A para B) continua aberta e não se resolve aqui:
  decidir isso depois de ver a reanálise seria escolher pelo resultado.

R8c.3. O que se prediz antes de olhar, para que a leitura depois não seja livre.
  O experimento 1 deu p empírico 0,573 com o placebo acima do observado. A entrada do ML
  acrescenta séries de alvo, não de busca: o painel de termos cresce pouco e o alvo fica
  menos ruidoso onde há mais de uma fonte. Predição: o resultado continua negativo, com
  `p` empírico da primária acima de 0,10. A condição que tornaria isto um achado,
  escrita agora: `p` empírico < 0,05 na primária com lag >= 1 e o placebo P1
  (lags invertidos) não produzindo efeito da mesma ordem. Se isso acontecer, ainda é
  exploratório: vira hipótese para o experimento 2, nunca confirmação.

R8c.4. O controle positivo é obrigatório e se reporta junto.
  Toda medida refeita se reporta com o par: o valor no alvo de duas fontes,
  recalculado pelo caminho de hoje, e o valor com três. Sem isso, "o valor mudou" e
  "o instrumento mudou" são indistinguíveis, e o primeiro é publicável.

R8c.5. O artigo aprovado não se reescreve; a monografia herda.
  O artigo pode ser atualizado para a monografia. O `.docx` entregue em `01/09` e
  aprovado em `02/09` é registro datado e continua como está: o que muda é o texto da
  monografia, e cada número que se mover entra lá com a data da medição nova, não
  substituindo em silêncio o que a banca leu.

-------------------------------------------------------------------------------
§8d. 22/09/2026: AS QUATRO PERGUNTAS RESTANTES DA §9 FORAM RESPONDIDAS
      (numerada 8d pela mesma razao da 8b: a §9 e citada em outros documentos)
-------------------------------------------------------------------------------

Esta seção fixa a especificação do experimento 2, e ela é escrita antes de o dado
novo existir. A série do Trends termina em `2026-09-06` e a janela nova só começa a
ser baixada em 06/10 (§9, Q3). Tudo abaixo está fixado com quinze dias de antecedência
sobre o primeiro byte do dado que vai testá-lo, que é a condição que dá valor ao
confirmatório. As decisões são de 22/09, tomadas sobre as medições e recomendações
registradas abaixo.

Nada aqui toca no experimento 1 nem na reanálise de 17/09. Os dois estão fechados,
com artefato, e seguem reproduzíveis pelas constantes originais: `PRIMARIA` continua
`A_media_movel` de propósito. O experimento 2 tem constantes próprias, abaixo.

R8d.1 (Q1a). O piso de pares por termo fica em 10. Confirmado em 22/09.
  `MINIMO_PARES_POR_TERMO = 10`, como na E8.1. Nenhuma alternativa foi adotada.

R8d.2 (Q1b). A primária continua o `alvo_unificado`, e o reporte das fontes deixa de
ser escolha. Definido em 22/09: em tudo o que for feito não há escolha de quais fontes
mostrar; tudo é feito e mostrado nas três (Shopee, Amazon e Mercado Livre). À pergunta
se as duas emendas se mantêm, a resposta foi sim.
  Duas coisas, e elas não são a mesma: (a) a E8.2 fica como está: uma primária,
  no unificado, e não duas ou três primárias por fonte (a alternativa que a §9 punha
  na mesa foi recusada); (b) o reporte lado a lado passa a ser obrigatório nas três
  fontes, em tudo que o trabalho produzir, não só neste experimento. `ALVOS` já traz
  `alvo_unificado`, `alvo_shopee`, `alvo_amazon` e `alvo_ml` desde a E9.1; o que muda é o
  status: mostrar as três deixou de ser uma opção do relator e virou regra.
  Consequência: toda lista que enumere fontes (filtro, corte, tabela, figura, texto) tem
  de ser varrida atrás das que ainda estejam escritas para duas, porque uma seleção por
  lista fixa continua correta sobre uma população menor. Já aconteceu três vezes: em
  15/09 (filtro por rótulo e corte do painel balanceado), em 17/09 (`mudanca_de_regime` e
  `perfil_das_series`) e em 22/09 (a trava do achado ⑤, que vigiava um par de três).

R8d.3 (Q2). A primária do experimento 2 é `B_variacao_pct`, e o lag é uma faixa.
  B foi escolhida com a recomendação à vista, incluindo o contra-argumento.
  `PRIMARIA_EXPERIMENTO_2 = "B_variacao_pct"` e `FAIXA_LAG_EXPERIMENTO_2 = (8, 12)`.
  A estatística primária do experimento 2 é `max_k mediana(ρ_k)` para `k` em `8..12`,
  e o placebo P2 compara esse máximo contra a distribuição do máximo dentro da mesma
  faixa sob permutação, nunca contra o máximo sobre a grade inteira. Trocar o alcance do
  máximo observado sem trocar o do nulo compararia coisas diferentes: cada estatística
  tem de ser comparada com o nulo do seu próprio alcance.
  As três razões da escolha são de desenho, não de p-valor (escolher pelo melhor p
  é garimpo de especificação): o nulo de B é metade do de A (0,035 contra 0,069 na
  reanálise), logo A precisaria de quase o dobro de efeito para se destacar do próprio
  fundo · B rende ~35% mais observações (perde 7 dias iniciais por bloco contra 13 de
  A; numa janela nova de 30 dias, ~23 pontos por termo contra ~17), e a janela do
  experimento 2 é curta · e a justificativa original de A ("o delta diário é ruído, logo
  suavize") não se aplica a B, que compara `t` com `t-7`, mesmo dia da semana, e
  neutraliza o calendário igual. O que separa as duas não é lento contra rápido: é
  suavizado contra ponto a ponto, ambas com passo 7.
  O que pesa contra, registrado porque a decisão foi tomada com isso à vista: a curva de
  A é bem mais reprodutível entre as duas rodadas: Spearman +0,811 contra +0,504. A de
  A sobe, faz platô em `k=5..8` e cai nas duas; a de B acerta o lag 8 numa e 11 na outra.
  Parte dessa suavidade é construção (lags vizinhos de A compartilham 6 dos 7 dias da
  média móvel), mas não tudo. É exatamente essa fraqueza que a faixa cobre: se B
  localiza mal o lag e a H1 pergunta se a busca antecipa, e não em quantos dias, fixar
  `8..12` compra a detecção sem depender de acertar o ponto.
  A faixa é o desenho previsto, não garimpo: a §1 deste arquivo diz que o
  experimento 1 gera a hipótese específica (qual operacionalização, qual lag) e que
  o 2 a testa com elas fixadas. Fixar a faixa a partir do 1 é o que o pré-registro
  mandava fazer; o que seria garimpo é mexer nela depois de ver o 2.
  A leitura registrada, declarada porque a pergunta formulada dizia só "B": a
  recomendação aceita era, literalmente, "B, procurando o efeito numa faixa de 8
  a 12 dias", e é assim que ficou escrito. Se a intenção era B com o máximo sobre a
  grade inteira, isso se troca em uma linha, e antes de 06/10, que é quando o dado novo
  aparece.
  Predição do experimento 2, escrita agora: correlação positiva, com o máximo
  dentro de `8..12`. A predição do experimento 1 (máximo em `k` entre 1 e 7, §6) era de A
  e não se transporta.

R8d.4 (Q4). A grade fica em `k = 0..14`, e a razão não é a leitura de mercado: é o
calendário. Esta é a única das quatro em que a resposta mudou depois da aritmética, e
as duas metades vão escritas.
  À pergunta se 14 dias bastam ou se o mercado tem ciclo maior, a resposta foi "ciclo
  maior". Com o custo de calendário na mesa, optou-se por manter `0..14`.
  A aritmética que produziu a escolha: todo lag `k` exige que a venda exista `k` dias
  depois do fim da janela de busca, e o download é em 06/10; logo `0..14` roda por
  volta de 20/10 (16 dias de folga até a monografia, ~05/11), `0..21` por volta de
  27/10 (9 dias) e `0..28` por volta de 03/11 (2 dias, sem margem para qualquer
  atraso). Havia um segundo custo, menor: a primária é um máximo, então mais lags elevam o
  nulo; mas quem decidiu foi o calendário.
  Consequência que vira limitação declarada, e ela tem de ir para o relatório e para a
  monografia (Cap. 4): o horizonte testado (14 dias) é, por decisão consciente, menor
  que o ciclo que o autor lê no mercado, e um efeito que só apareça em 3 ou 4 semanas
  não seria detectado por este desenho. Isso não é omissão: é restrição de calendário,
  escrita antes do teste. Se o cronograma abrir (download antes de 06/10 pela API
  oficial, por exemplo), subir a grade passa a caber; e aí a mudança se declara aqui,
  antes de olhar o dado, nunca depois.

R8d.5 (Q5). O corte fica no percentil 95, e o rótulo continua "digno de replicação".
  Confirmado em 22/09, com as alternativas à vista.
  As três razões: o corte aqui não declara significância, declara que vale repetir, e
  errar para o lado de repetir é barato, enquanto descartar um sinal real não é · com 1.000
  permutações, um p99 se apoia nos 10 valores da ponta da cauda e é instável · e a proteção
  forte do desenho é a replicação pré-registrada, não a altura da barra.
  O rótulo é parte da decisão, não enfeite: se "digno de replicação" virar
  "significativo" em qualquer documento, o desenho inteiro perde a proteção, e essa
  troca de palavra não seria detectada por nenhuma verificação automática do projeto: a
  promessa está na palavra funcional.

-------------------------------------------------------------------------------
§8e. 30/09/2026: EMENDA: A ROBUSTEZ COM A COMPOSIÇÃO DESCONTADA
      Posterior à especificação da §8d, ANTERIOR ao dado do experimento 2
      (o download da janela nova do Trends é em 06/10 ou depois). O commit
      que carimba esta seção precede qualquer execução dela.
-------------------------------------------------------------------------------

Isto é uma emenda, e ela se declara. A §8d fixou o experimento 2 em 22/09; esta seção
acrescenta a ele uma robustez, e não toca em nada da §8d: a primária continua
`B_variacao_pct | alvo_unificado`, com a estatística `max_k mediana(ρ_k)` em `k = 8..12` e o
nulo do máximo na mesma faixa (R8d.3). O que muda é o que se reporta ao lado dela, e como
isso se lê.

Por que ela existe: a composição, medida. O alvo de um termo num dia é a média dos
percentis dos itens dele, e o `alvo_unificado` é a média das fontes presentes. As duas
médias mudam de composição de um dia para o outro sem que a demanda mude: item que
entra no termo entra embaixo e puxa a média (Amazon: mediana da correlação dentro do termo
−0,26 com o nº de itens), e fonte que entra ou sai do dia muda o nível (presença da
Shopee: +0,20). A H1 compara cada termo consigo mesmo no tempo, que é exatamente essa
variação; então, se o nº de itens andar junto com a busca defasada, a composição pode
fabricar ou esconder lead-lag. A medição exploratória de 24–25/09 (sobre o dado do
experimento 1, já visto) deu o elo nulo na faixa `8..12` e mostrou o desconto mudando o
que a faixa enxerga na Amazon. Nada dali é resultado da H1; foi o que motivou a emenda.

R8e.1. O desenho do desconto: por fonte, depois a média. Escolhido em 30/09, entre duas
alternativas.
  Para cada fonte `s` e cada termo, o alvo da fonte é substituído pelo resíduo da
  regressão linear dele no nº de itens da fonte, dentro do termo
  (`composicao_alvo_h1.descontar_composicao`); o `alvo_unificado_sem_composicao` é a
  média dos resíduos das fontes presentes naquele termo-dia.
  A razão é uma propriedade do desconto, medida sobre o alvo e sem olhar a busca:
  dentro do termo, a correlação mediana do unificado com cada canal de composição vai a
  ~0 com este desenho (nº de itens da Shopee +0,01, da Amazon −0,02, do ML 0,00; presença
  das três fontes +0,01, −0,01, 0,00). A alternativa recusada (descontar o nº total de
  itens do unificado numa regressão só) zera apenas a correlação com o total e deixa a
  da Shopee (+0,15) e a da presença das fontes (+0,20, −0,08, −0,12) praticamente onde
  estavam. Centrar cada fonte dentro do termo é o que remove também o canal da entrada e
  saída de fontes, que a alternativa nem enxerga.
  O ajuste se estima sobre os mesmos termo-dias que entram no painel do experimento 2,
  não sobre a série inteira: a composição muda com o churn, e a correlação é lida só
  naquela janela. Termo sem variação no nº de itens de uma fonte fica com o alvo da fonte
  apenas centrado.
  Declarado, e não é vazamento da variável líder: o coeficiente de cada termo usa
  todos os dias da janela, inclusive os posteriores a `t`. Ele relaciona alvo e nº de
  itens do mesmo dia (a busca não entra nele), e o nulo da permutação usa as mesmas
  séries descontadas, então qualquer efeito do ajuste aparece dos dois lados.

R8e.2. O que se reporta: a primária e a robustez, nas quatro séries. A mesma
estatística e o mesmo placebo da R8d.3 (faixa `8..12`, nulo do máximo na mesma faixa, 1.000
permutações, piso de 10 pares), aplicados a `alvo_unificado_sem_composicao` e a cada
fonte descontada (`alvo_shopee_sem_composicao`, `alvo_amazon_sem_composicao`,
`alvo_ml_sem_composicao`), cada uma contra o próprio nulo, porque o N difere entre elas;
o reporte das três fontes é obrigatório (R8d.2), e isso vale também para a robustez.

R8e.3. Como a robustez se lê, escrito antes de ela existir. Escolhido em 30/09: a
robustez que falha rebaixa o achado. O veredito continua sendo o da primária; a
robustez decide o que o veredito pode afirmar:
  * primária digna E robustez digna: o achado se reporta como digno de replicação e
    sobrevivente ao desconto da composição;
  * primária digna E robustez NÃO digna: o achado se reporta como não sobrevivente
    ao desconto da composição: pode ser efeito mecânico do nº de itens e não sustenta
    "a busca antecipa a demanda";
  * primária NÃO digna E robustez digna: não resgata nada. Fica descritivo, como
    hipótese para trabalho futuro; trocar a primária pela versão que passou seria
    escolher a especificação pelo desfecho, que é o que este arquivo existe para impedir;
  * nenhuma das duas: negativo, como o experimento 1.
  "Digno" é o critério da R8d.5: acima do p95 do próprio nulo, com lag na faixa.

R8e.4. Nada disto toca no experimento 1 nem na reanálise de 17/09. Os dois estão
fechados, com artefato, e seguem reproduzíveis pelas constantes originais.

-------------------------------------------------------------------------------
§8f. 30/09/2026: DECLARAÇÃO: O ALVO MUDOU POR UMA REGRA DE CLASSIFICAÇÃO
      Antes do dado do experimento 2, e commitada junto da regra.
-------------------------------------------------------------------------------

O objeto medido mudou, e isso se declara, não se edita em silêncio. Decisão de 29/09:
escrever a regra de "Artes e entretenimento", a 16ª categoria ativa da Parte A, que não
tinha regra de classificação. A regra (`parte_b3_refresh_multi_fonte.REGRAS_ARTES`)
foi escrita a partir dos títulos reais da vitrine `musical-instruments` da Amazon e medida
nos dois sentidos antes de entrar.

R8f.1. O que muda no alvo, medido sobre o Bronze até 29/09 (alvo com e sem a regra, termo-dia a
termo-dia):
  * 160 termo-dias mudam, todos no alvo da Amazon, em quatro termos que perdem itens que
    estavam neles por engano: `bateria de litio` (amplificadores e pedais de guitarra com
    "bateria" no título), `smartphone` (pedais), `teclado` (um suporte de teclado musical) e
    `conjunto infantil menina` (um karaokê infantil). Shopee e ML: zero. Os outros 213
    termos: intocados.
  * Oito termos novos (375 termo-dias): `encordoamento`, `pedaleira para guitarra`,
    `amplificador de guitarra`, `suporte para instrumento musical`, `acessorio para
    instrumento musical`, `flauta doce`, `luz de festa` e `karaoke`. Eles não têm série de
    busca e não entram no painel da H1: o painel é a interseção com os termos do Trends.
  * Na série inteira, 38 títulos distintos mudam de classificação, todos da vitrine
    de instrumentos; nenhum título de outra vitrine, da Shopee ou do ML.

R8f.2. O experimento 2 usa o alvo novo. Ele é a correção de um erro de classificação,
não uma escolha entre alvos: um amplificador de guitarra não é bateria de lítio. A mudança
foi feita e medida antes de o dado novo existir, e o que ela move está listado acima.

R8f.3. O experimento 1 e a reanálise continuam reproduzíveis, e agora exigem duas
chaves. O classificador de antes está preservado (`REGRAS_COMP_SEM_ARTES`) e
`alvo_h1.construir_alvo(..., com_regras_artes=False)` o usa, conferido em 30/09: o alvo
sai idêntico, linha a linha, ao de antes da regra. O experimento 1 exato é
`com_mercado_livre=False, com_regras_artes=False`; a reanálise de 17/09 é
`com_regras_artes=False`. No runner: `--duas-fontes --sem-regras-artes`. A §8b dizia que
`com_mercado_livre=False` bastava, e bastou até 29/09.

-------------------------------------------------------------------------------
§8g. 30/09/2026: DECLARAÇÃO: O ALVO MUDOU POR UMA SEGUNDA REGRA DE CLASSIFICAÇÃO
      Antes do dado do experimento 2, e commitada junto da regra.
-------------------------------------------------------------------------------

Em 30/09: o termo `microfone de lapela` juntava qualquer título com a palavra
"microfone"; a regra de 10/07 é `\bmicrofone\b` solto. Medido nas três fontes: dos 25
itens distintos do termo, só 12 eram microfone de lapela; os outros eram headphones com
microfone, webcams, suportes de microfone, microfones USB e de mão, e um kit de estúdio.
A regra nova (`parte_b3_refresh_multi_fonte.REGRAS_MICROFONE`) os manda para o termo
certo sem editar a regra de 10/07.

R8g.1. O que muda no alvo, medido sobre o Bronze até 29/09 (com a regra de Artes já aplicada,
com e sem esta):
  * 154 termo-dias do alvo unificado mudam, em dois termos: `microfone de lapela` (perde os
    13 itens que não eram de lapela) e `fone de ouvido bluetooth` (ganha os headphones). Na
    Amazon 151, na Shopee 5, no ML 3.
  * Diferente da §8f, esta mudança entra no painel da H1: os dois termos têm série do
    Trends. E ela vai na direção do teste: o alvo de `microfone de lapela` passa a medir o
    produto que a busca "microfone de lapela" mede, em vez de uma mistura de microfones,
    webcams e fones.
  * Cinco termos novos (232 termo-dias), sem série de busca, que não pareiam: `webcam`,
    `suporte para microfone`, `kit para live e vlog`, `microfone usb` e `microfone sem fio de mao`.
  * Na série inteira, 16 títulos distintos mudam de classificação, nenhum saído de outro
    termo que não `microfone de lapela` ou da condição de órfão; invariante aditiva: 0 quebras.

R8g.2. O experimento 2 usa o alvo novo, pela mesma razão da R8f.2: é correção de um erro
de classificação, medido e listado antes de o dado novo existir.

R8g.3. A chave de reprodução é a mesma da §8f. `REGRAS_COMP_SEM_ARTES` e
`com_regras_artes=False` passam a excluir as duas regras de 30/09 (Artes e microfone), e o
classificador que sobra é exatamente o de antes de 30/09 (v1 + v2 + v3, 222 regras). O nome da
chave diz "artes" porque nasceu com a regra de Artes; o que ela significa é "o classificador
de antes de 30/09".

-------------------------------------------------------------------------------
§8h. 20/10/2026: EMENDA: O MERCADO LIVRE SAI DO ALVO DO EXPERIMENTO 2
      Posterior às §8d–§8g, ANTERIOR ao dado do experimento 2: a janela `c` do Trends
      (07/09 → 19/10) ainda não foi baixada quando esta seção foi escrita e commitada.
-------------------------------------------------------------------------------

Decisão de 20/10: o ML parou em 06/10 e o coletor seguiu tentando; em 20/10 a fonte foi
retirada do projeto. Da Silver em diante a análise não o usa; o que ficou coletado no
Bronze fica como exemplo. O que aconteceu na fonte: a última rodada gravada do ML é a de
06/10 00:00 BRT (03:00 UTC); dali em diante a fonte mandou o crachá honesto para uma página
de verificação de conta (451, parada ética do `enxame-api`) e, desde 19/10 18:00 BRT, devolve
HTTP 500. O coletor seguiu publicado, tentando a cada 6 h, sem contornar nada. Os Termos de Uso
do ML proíbem a coleta automatizada.

R8h.1. O alvo do experimento 2 é Shopee + Amazon. `construir_alvo(com_mercado_livre=False)`,
com as duas regras de classificação de 30/09 (§8f e §8g). Tudo o mais da §8d fica: primária
B no `alvo_unificado` (agora a média de duas fontes), máximo na faixa `8..12` contra o
nulo do máximo na mesma faixa, grade `0..14`, piso de 10 pares, corte p95, a mesma semente.
A R8d.2 vale com as fontes que o alvo tem: as duas aparecem ao lado da primária; "mostrar
todas" deixou de significar três porque o objeto mudou, não por escolha de quais mostrar.

R8h.2. A robustez da §8e fica como está, sobre as duas fontes: desconto por fonte, depois a
média; a que falha rebaixa o achado (R8e.3).

R8h.3. O runner recusa outra composição. Se o alvo do experimento 2 carregar qualquer fonte
além de `FONTES_DO_ALVO_EXPERIMENTO_2`, ele para antes de medir. É o fail-closed da §8c aplicado
à composição: trocar a fonte depois de ver o desfecho seria escolher o objeto pelo resultado.

Por que isto não é escolher pelo desfecho, e por que é também melhor método:
  * O dado do experimento 2 não existe: a busca nova não foi baixada; nenhum termo-dia da
    janela foi olhado contra o alvo.
  * O ML cobriria só metade da janela. A venda que o experimento 2 lê vai de 07/09 a
    ~02/11; o ML tem dado até 06/10. Mantido, o `alvo_unificado` mudaria de composição no meio
    da janela (três fontes até 06/10, duas depois), que é exatamente a mudança de regime por
    composição (cada fonte que entra ou sai muda a variância do unificado), agora dentro do
    teste. Tirá-lo deixa a composição estável na janela inteira.

O que não muda: o experimento 1 (08/09, duas fontes) e a reanálise de 17/09 (três fontes)
estão fechados com artefato e não se reescrevem. Os dois seguem reproduzíveis: o de 17/09
com `com_mercado_livre=True`, que carrega a série do ML cortada em 06/10
(`carregar_bronze.PARADAS_DECLARADAS`). O padrão do `construir_alvo` voltou a ser
`com_mercado_livre=False` em 20/10, e a chave do experimento 1 continua a mesma.

-------------------------------------------------------------------------------
§8i. 04/11/2026: EMENDA: O CORTE DA VENDA EM 01/11 E OS DIAS ZERADOS DA JANELA c
      Posterior ao download da janela `c` (04/11, 51 arquivos, manifesto `f19a221`),
      ANTERIOR à execução do experimento 2: o runner não rodou, e nenhum termo-dia da
      busca nova foi olhado contra o alvo.
-------------------------------------------------------------------------------

Em 02/11 a coleta foi encerrada, com uso dos dados até 01/11, e os coletores foram
despublicados. Duas coisas que o experimento 2 lê mudam de definição, e as duas se
declaram antes de ele rodar:

R8i.1. A venda vai até 01/11 inclusive (dias UTC). A rodada de 02/11 03:00 UTC (00:00 BRT)
sai, porque deixaria o último dia pela metade. Implementado na leitura, não no runner:
`carregar_bronze.FIM_DA_COLETA = "2026-11-02T00:00:00Z"` corta Shopee e Amazon (e YouTube e
Suggest) com aviso, e o Bronze não é tocado. Efeito na grade: a busca vai até 19/10, então a
faixa primária `8..12` fica inteira (19/10 + 12 = 31/10), o lag 13 também (19/10 + 13 = 01/11),
e só o lag 14 perde um par por termo: o do último dia de busca (19/10 + 14 = 02/11 sai). A
grade, a faixa, o nulo e a semente não mudam.

R8i.2. Os dias 19, 20 e 21/09 seguem a regra de nulo que já existia, por lote. No download,
a consulta inteira zera nesses dias em 16, 22 e 17 dos 51 arquivos, os de pouco volume; os de
muito volume seguem normais. Não é apagão geral, e por isso nenhuma regra nova: vale
`conferir_trends.Lote.dias_anomalos()` (escrita antes do dado), que anula o dia no lote em que
pelo menos dois termos com volume zeram juntos. Os três dias entram em `DIAS_QUEBRADOS_CONHECIDOS`,
que é lista de relatório e não muda nenhum valor.
Limite declarado: os 5 arquivos de termo único (`53c`, `57c`, `58c`, `69c`, `73c`) não têm
vizinho que permita distinguir o dia zerado da fonte de um zero do termo; ali o zero fica como a
regra o trata desde julho. Anular esses três dias em todo arquivo seria regra nova escrita
depois de ver a busca, e não se faz.

-------------------------------------------------------------------------------
9. AS CINCO DECISÕES DE MÉTODO QUE ESTAVAM EM ABERTO
   AS CINCO ESTAO RESPONDIDAS: a Q3 em 22/09 (secao 9 abaixo) e as outras
      quatro em 22/09, na §8d acima. Esta secao fica como REGISTRO do que se
      decidiu e das alternativas que estavam na mesa: ela nao e pre-registro,
      e diz isso de si mesma no paragrafo seguinte.
-------------------------------------------------------------------------------

Esta seção não é pré-registro: é a lista de perguntas abertas. Ela existe porque a
revisão do protocolo exigia decisões, e "revise o protocolo" é instrução, não pergunta:
sem o que decidir escrito, a revisão reabriria tudo para chegar às mesmas cinco. Nada
abaixo muda o que já rodou: o experimento 1 está fechado, com artefato, e o que se decide
aqui vale para o experimento 2.

Q1. As duas emendas da §8 ficam como estão? (as duas foram redigidas durante a
implementação do runner e estão commitadas antes do experimento, mas, como decisões de
método, exigiam confirmação explícita.)
RESPONDIDA EM 22/09: sim, as duas, e a E8.2 ganhou um adendo: em tudo o que for feito não
há escolha de quais fontes mostrar; tudo é feito e mostrado nas três.
Ver R8d.1 e R8d.2 da §8d. O reporte das três fontes deixou de ser escolha do relator.
* E8.1, `MINIMO_PARES_POR_TERMO = 10`. Sem piso, termo com 4 pares entra na mediana
  com o mesmo peso de um com 40. 10 corta cauda sem escolher população, e é folgadamente
  menor que a mediana de dias do painel (51). Alternativas: 15 e 20 encolhem o painel;
  0 devolve o ruído.
* E8.2, primária no `alvo_unificado` com Shopee e Amazon ao lado. Aqui há
  tensão real, e ela é do trabalho, não do código: a R5 diz unificado, o artigo
  aprovado diz "reporte as duas fontes lado a lado", e o achado ⑤ diz que as duas não
  se correlacionam. A saída oposta seria abandonar o unificado e ter duas primárias,
  uma por fonte, o que dobra a família de testes e exige permutação em cada uma.

Q2. A primária do experimento 2 continua sendo A, ou passa a ser B?
RESPONDIDA EM 22/09: passa a ser B, com o lag em faixa `8..12`. Ver R8d.3 da §8d,
onde estão as três razões de desenho e o contra-argumento (a curva de A é mais
reprodutível) que estava na mesa quando a decisão foi tomada.
A pergunta precisou ser reaberta no mesmo dia, por uma descrição incompleta das opções.
A havia sido resumida como "média dos últimos 7 dias" e B como "hoje contra o mesmo dia
da semana passada", e a primeira está incompleta: A também é uma comparação de uma semana
com a anterior (`MM7_t / MM7_{t-7}`). A primeira resposta registrada (comparar sempre a
semana atual com a anterior) descreve A, o oposto da recomendação. Com as duas fórmulas
explícitas, a escolha foi B. A lição é de comunicação e vale para toda esta seção:
resumo de fórmula para decidir tem de distinguir as opções, não só descrevê-las;
descrição incompleta não é erro de valor, e por isso nenhuma verificação automática a
detectaria.
O pré-registro fixou A (média móvel) pela medição do sinal lento. O experimento 1
apontou levemente para B (ponto a ponto): p empírico 0,115 contra 0,580 de A.
Nenhuma das duas passou do próprio p95, então o dado não obriga a trocar, e é
justamente por isso que a decisão tem de ser tomada agora e por escrito. Trocar
depois de ver o resultado do experimento 2 seria escolher a especificação pelo desfecho,
que é o defeito que este arquivo inteiro existe para impedir.

Q3. O EXPERIMENTO 2 SERÁ FEITO? Esta é a única com prazo.
RESPONDIDA EM 22/09/2026: sim. Não será trabalho futuro: a monografia é para novembro,
e até lá o teste e outras alterações no projeto estarão feitos. O experimento 2 é
resultado da monografia, não trabalho futuro, e o Cap. 4 dela o recebe.
Consequência imediata, e ela é sobre este arquivo: as outras quatro perguntas
ganharam calendário. Enquanto o 2 era hipótese, elas podiam esperar; agora a Q2
precisa estar respondida antes de o dado novo ser olhado, porque escolher a primária
depois de ver o desfecho é exatamente o que este arquivo existe para impedir (R8c.2).
O que não muda com a decisão: a condição de dado. Querer o experimento 2 não
cria a série; ela continua exigindo o que está escrito abaixo.
A condição está na §1: ≥ 30 dias de Trends posteriores a `2026-09-06` para ≥ 60 termos.
Ela não se cumpre esperando: a série do Trends é estática, e a coleta manual
encerrou em 07/09. Só há dois caminhos, e os dois custam calendário:
* reabrir a coleta manual (o `02_Dados/trends/PLANO_TRENDS.md`, mais alguns dias de
  download como os de 02–07/09): é trabalho manual, e é o único caminho que depende só
  do projeto;
* a API oficial do Google Trends, que é alpha por aplicação, com acesso restrito, e
  pode não sair a tempo da monografia (~05/11).
Correção registrada em 22/09, conferida no `PLANO_TRENDS.md`: a afirmação de que, com a
resposta "sim", a coleta precisaria começar está errada sobre o instrumento. A coleta do
Trends é por período personalizado: pede-se uma janela histórica e a fonte devolve
a série dela no ato. Não há coleta diária a começar; há uma passada de download a
fazer, depois que a janela existir.
O que o experimento 2 exige, em forma executável: uma passada nos ~129 termos
(lotes de 5, como as de 02–07/09), pedindo a janela `07/09/2026` → data do download,
feita em 06/10 ou depois (antes disso a janela tem menos de 30 dias). Esperar mais
rende mais série (a monografia é ~05/11, então há folga), e o `conferir_trends.py`
continua sendo quem diz se algum arquivo precisa voltar.
Risco herdado: a fonte reescreve o passado. Um dia-lixo novo pode aparecer na janela
nova, como o `16/08` apareceu; quem o pega é o auditor, e a perda é por arredondamento,
irreversível. Por isso o manifesto de `sha256` se refaz no mesmo dia do download.
Se a resposta tivesse sido "não", o trabalho reportaria o experimento 1 como resultado
exploratório único e declararia o 2 como trabalho futuro, o que era honesto e já estava
sustentado pelo artigo aprovado, que declara a série curta.

Q4. A grade de lags `k = 0..14` cobre o horizonte certo?
RESPONDIDA EM 22/09: fica em `0..14`, por calendário e não por leitura de mercado.
Ver R8d.4 da §8d, com a aritmética (`0..21` roda ~27/10; `0..28`, ~03/11, dois dias antes
da monografia) e a limitação declarada que isso gera: o horizonte testado é menor que o
ciclo que o autor lê no mercado, e um efeito de 3–4 semanas não seria detectado.
Duas semanas foi escolhido como o horizonte em que "a busca antecipa a venda" é
economicamente interpretável para e-commerce. Se a leitura do mercado for de ciclo
maior (compra planejada de bem durável, por exemplo), a grade sobe, e isso muda o
custo do placebo, porque a primária é um máximo sobre a grade inteira: mais lags, nulo
mais alto, e o mesmo achado fica mais difícil de destacar. Não é de graça nos dois
sentidos.

Q5. O corte fica no percentil 95, e o rótulo continua "digno de replicação"?
RESPONDIDA EM 22/09: sim para os dois. Ver R8d.5 da §8d. As alternativas foram
apresentadas antes da decisão; p99 e p90 estão comparados lá, com a razão de p95 ficar.
É a régua que decide se um achado futuro merece o experimento 2. P95 é a convenção;
p99 é mais duro e faz sentido se se quiser que só um sinal forte mova o trabalho.
O rótulo importa tanto quanto o número: "digno de replicação" foi escolhido para
que nada daqui seja lido como confirmação. Se ele virar "significativo" em algum
documento, o desenho inteiro perde a proteção, e essa troca de palavra não seria
detectada por nenhuma verificação automática do projeto.

═══════════════════════════════════════════════════════════════════════════════
As constantes abaixo são o protocolo em forma executável. Mudá-las depois de
rodar é mudar o pré-registro, e isso se declara: não se edita em silêncio.
═══════════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

# --- §2. As três operacionalizações ----------------------------------------
PASSO_SAZONAL = 7           # o passo que neutraliza o calendário sem estimar nada
JANELA_MM = 7               # MM7: anula o ciclo semanal por construção
JANELA_BASE_C = 14          # a janela trailing do z-score da operacionalização C

OPERACIONALIZACOES = ("A_media_movel", "B_variacao_pct", "C_desvio_base")
PRIMARIA = "A_media_movel"  # justificada pela medição do passo 2, não por gosto
ROBUSTEZ = ("B_variacao_pct", "C_desvio_base")

# --- §4. O teste ------------------------------------------------------------
LAGS = tuple(range(0, 15))      # k = 0..14; k=0 é descritivo, não entra na primária
LAG_MINIMO_PRIMARIA = 1
METODO_CORRELACAO = "spearman"  # posto a posto; sem scipy no venv de análise

# --- §5. Os placebos --------------------------------------------------------
LAGS_PLACEBO_INVERTIDO = tuple(range(-7, 0))
N_PERMUTACOES = 1_000
PERCENTIL_CORTE = 95

# --- §8. Emendas de 08/09, commitadas antes do primeiro resultado ------------
MINIMO_PARES_POR_TERMO = 10           # E8.1: vale no observado e no permutado
ALVOS = ("alvo_unificado", "alvo_shopee", "alvo_amazon", "alvo_ml")  # E8.2 + E9.1
ALVO_PRIMARIO = "alvo_unificado"      # a primária segue o pré-registro original

# --- §8d. A especificação do experimento 2, fixada em 22/09 ------------------
# Constantes próprias, e não substituições: as de cima reproduzem o experimento
# 1 e a reanálise, que estão fechados com artefato. Escritas 15 dias antes de o
# primeiro byte do dado novo ser baixado (06/10), e é isso que as faz valer.
PRIMARIA_EXPERIMENTO_2 = "B_variacao_pct"   # R8d.3: nulo pela metade, ~35% mais obs
FAIXA_LAG_EXPERIMENTO_2 = (8, 12)           # R8d.3: faixa, não lag pontual
# O placebo P2 compara o máximo observado dentro da faixa contra o máximo
# permutado dentro da mesma faixa. Alcances diferentes não se comparam.
LAGS_EXPERIMENTO_2 = tuple(range(8, 13))
# R8d.4: a grade completa não muda: 0..14. A razão é calendário, não horizonte
# econômico, e a limitação disso vai declarada no relatório e na monografia.
GRADE_LIMITADA_POR_CALENDARIO = True
# R8d.2: mostrar as três fontes deixou de ser escolha do relator.
REPORTE_DAS_TRES_FONTES_E_OBRIGATORIO = True

# --- §8e. A robustez com a composição descontada, emenda de 30/09 -----------
# Commitada antes do download da janela nova (06/10) e antes de qualquer execução.
DESCONTO_COMPOSICAO = "por_fonte_depois_media"   # R8e.1: recusado "no_total"
ALVOS_ROBUSTEZ_COMPOSICAO = (                    # R8e.2: cada um contra o próprio nulo
    "alvo_unificado_sem_composicao",
    "alvo_shopee_sem_composicao",
    "alvo_amazon_sem_composicao",
    "alvo_ml_sem_composicao",
)
ROBUSTEZ_QUE_FALHA_REBAIXA_O_ACHADO = True       # R8e.3: e a que passa não resgata

# --- §8h. O ML sai do alvo do experimento 2, emenda de 20/10 ------------------
# Commitada antes do download da janela c (07/09 -> 19/10). O runner recusa
# qualquer outra composição (R8h.3). A R8d.2 vale com as fontes que o alvo tem.
FONTES_DO_ALVO_EXPERIMENTO_2 = ("shopee", "amazon")

# --- §8i. O corte da venda em 01/11, emenda de 04/11 ---------------------------
# Commitada depois do download da janela c e antes de o experimento 2 rodar. O corte
# fica no carregador (carregar_bronze.FIM_DA_COLETA); aqui fica o último dia de venda.
ULTIMO_DIA_DE_VENDA_EXPERIMENTO_2 = "2026-11-01"

# --- §1. A condição de reabertura, em forma verificável ---------------------
EXPERIMENTO = "exploratorio"
ULTIMO_DIA_DE_BUSCA = "2026-09-06"      # a coleta manual encerrou aqui e não cresce
DIAS_NOVOS_PARA_EXPERIMENTO_2 = 30
TERMOS_MINIMOS_PARA_EXPERIMENTO_2 = 60

# --- §3. As regras que não se negociam --------------------------------------
JANELA_CENTRADA_PROIBIDA = True   # R1: reparo com o futuro é vazamento
JANELA_CRUZA_EMENDA = False       # R2: o 16/08 está quebrado na fonte
NULO_VIRA_ZERO = False            # R3
SUAVIZAR_O_ALVO = False           # R4: Slutsky-Yule

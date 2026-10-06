# EV ChargeOps — Sprint 02

Protótipo de gestão e rateio de recargas de veículos elétricos em infraestruturas compartilhadas, como condomínios, edifícios corporativos e campi.

O projeto transforma registros de recarga em sessões vinculadas a usuários, valida os dados, identifica anomalias, calcula o valor individual de cada sessão e gera faturas mensais com informações para usuários e gestores.

## Equipe

| Nome | RM |
|---|---|
| Gabriel de Leão da Rocha | RM571330 |
| Guilherme Alves Nune | RM572754 |
| Pedro Henrique de Souza Elias | RM570487 |
| Maurício Furlan Rodrigues Chaves | RM572512 |

## Contexto do projeto

A Sprint 01 definiu o problema, a proposta de negócio, a arquitetura inicial e o modelo de dados do EV ChargeOps. A premissa era integrar o carregador GoodWe HCA G2 a uma plataforma capaz de:

- identificar cada sessão por usuário;
- substituir a dependência de cartões RFID por autenticação digital;
- aplicar um rateio proporcional ao consumo e ao horário de uso;
- cobrar ociosidade quando o veículo permanece conectado após o fim da carga;
- detectar sessões suspeitas antes da cobrança;
- prever consumo e sugerir horários mais econômicos;
- apresentar faturas individuais e indicadores consolidados ao gestor.

A Sprint 02 concentrou-se em tornar executável o núcleo dessa proposta. O resultado é um protótipo local que demonstra o fluxo completo a partir de sessões já encerradas: ingestão, validação, análise por IA, rateio, faturamento, revisão humana e visualização dos resultados.

## Solução implementada

O protótipo processa dados reais exportados do portal SEMS+ e dados simulados de moradores e visitantes. A cada mês de competência, o sistema executa o seguinte fluxo:

1. Valida e normaliza os registros recebidos.
2. Descarta sessões sem energia e retém sessões suspeitas para revisão.
3. Classifica os usuários por perfil de uso.
4. Divide o consumo pelas faixas tarifárias e gera as faturas.
5. Prevê o consumo do mês seguinte.
6. Sugere horários de menor custo e gera insights auditáveis.
7. Permite que o gestor aprove ou rejeite sessões retidas.

Somente sessões com status `validada` entram na cobrança. Uma sessão em revisão permanece fora da fatura até a decisão do gestor. Se for aprovada depois do fechamento do mês original, seu valor entra como ajuste na fatura aberta mais recente.

### Funcionalidades entregues

- ingestão de registros reais e simulados;
- validação de integridade e rastreabilidade de registros inválidos;
- detecção de anomalias por regras, Isolation Forest e z-score por veículo;
- agrupamento de perfis de uso com K-Means;
- previsão mensal com regressão Ridge;
- recomendação de faixa horária a partir de tarifa e ocupação histórica;
- rateio por usuário, sessão e faixa horária;
- modalidades mensal e avulsa;
- cobrança configurável de ociosidade;
- pré-autorização e cálculo de estorno para cargas avulsas;
- revisão manual de sessões suspeitas;
- relatórios em CSV, gráficos PNG e resumo textual;
- interface desktop para demonstração e análise;
- comandos de terminal para operação e consulta.

## Dados utilizados

O cenário de referência combina duas fontes:

- **Dados reais:** 97 sessões do carregador `57000HPA247L0002`, entre maio e setembro de 2026, totalizando 769,27 kWh. O total foi conferido com o relatório Charging Record exportado do SEMS+.
- **Dados simulados:** 285 registros de moradores e visitantes, gerados com semente fixa e comportamento calibrado a partir dos dados reais. O cenário inclui três carregadores adicionais e casos de teste como sessão longa, energia incompatível com a bateria, queda de potência, interrupção, registro corrompido e usuário sem consumo.

O relatório real possui um único cartão, por isso suas sessões foram associadas ao usuário `Energy Innovation Lab`. Como o Charging Record não contém telemetria intermediária, as leituras dessas sessões foram reconstruídas em intervalos de cinco minutos. Essa telemetria é marcada no banco como `estimada` e não deve ser confundida com medição real em tempo real.

## Rateio

O modelo mantém as duas modalidades definidas na Sprint 01:

```text
Plano mensal: F = soma(E × T) + C + P
Carga avulsa: V = soma[E × (T + M)] + P
```

Onde:

- `E` é a energia consumida em kWh;
- `T` é a tarifa da faixa horária;
- `C` é a contribuição fixa mensal;
- `M` é a margem por kWh da modalidade avulsa;
- `P` é o valor de ociosidade após a tolerância.

### Parâmetros do protótipo

| Parâmetro | Valor |
|---|---:|
| Tarifa de pico, das 17h às 22h | R$ 0,95/kWh |
| Tarifa intermediária, das 7h às 17h | R$ 0,75/kWh |
| Tarifa noturna, das 22h às 7h | R$ 0,55/kWh |
| Contribuição fixa mensal (`C`) | R$ 25,00/mês |
| Margem da carga avulsa (`M`) | R$ 0,40/kWh |
| Tolerância de ociosidade | 30 minutos |
| Ociosidade no pico | R$ 2,00/h |
| Ociosidade no período intermediário | R$ 1,00/h |
| Ociosidade no período noturno | R$ 0,00/h |
| Pré-autorização por carga avulsa | R$ 50,00 |

Todos esses valores ficam centralizados em `src/config.py`.

Quando uma sessão atravessa mais de uma faixa, cada intervalo de telemetria é classificado pelo ponto médio. O consumo total cobrado continua sendo o valor do medidor; a telemetria apenas determina a proporção destinada a cada tarifa.

## Inteligência artificial e regras de decisão

### Detecção de anomalias

A decisão ocorre antes do faturamento em duas camadas:

1. **Regras determinísticas:** sessão sem energia, duração acima de 12 horas, energia maior que 105% da bateria, divergência entre medidor e telemetria e queda brusca de potência.
2. **Modelos estatísticos:** Isolation Forest sobre duração, potência média, fração da bateria e ociosidade; e z-score do consumo em relação ao histórico do mesmo veículo.

O horário de início e o kWh absoluto foram retirados do Isolation Forest porque, nos testes, penalizavam usuários que carregavam de dia e veículos com baterias maiores sem indicar um problema real.

### Perfis, previsão e recomendações

- O **K-Means** agrupa usuários por frequência, consumo, participação no pico, horário médio e ociosidade.
- A **regressão Ridge** prevê o consumo do próximo mês usando histórico, quantidade de sessões, percentual no pico e comportamento do grupo.
- No primeiro mês, quando ainda não há histórico suficiente, a previsão usa a média entre o consumo do usuário e o de seu grupo.
- As mensagens exibidas são geradas por templates preenchidos com resultados calculados. Isso mantém os números rastreáveis e evita conteúdo não verificável.

## Arquitetura do protótipo

```text
Charging Record + simulação
            |
            v
  ingestão e validação
            |
            v
   análise de anomalias ----> revisão do gestor
            |
            v
 perfis -> rateio -> faturas -> previsão e insights
            |
            v
 SQLite + CSVs + gráficos + CLI + interface desktop
```

### Estrutura do repositório

| Caminho | Responsabilidade |
|---|---|
| `main.py` | comandos de execução e consulta |
| `src/config.py` | tarifas, valores do rateio e parâmetros dos modelos |
| `src/db/` | modelos SQLAlchemy e conexão SQLite |
| `src/ingestao/` | validação e normalização das sessões |
| `src/rateio/` | faixas horárias, fórmulas e geração de faturas |
| `src/ia/` | anomalias, perfis, previsão, horários e insights |
| `src/simulacao/` | cadastro do cenário e geração determinística dos dados |
| `src/pipeline.py` | coordenação do ciclo mensal completo |
| `src/relatorios.py` | exportação de CSVs, gráficos e relatório textual |
| `app/` | interface desktop em CustomTkinter |
| `scripts/` | extração do Charging Record em PDF |
| `tests/` | testes de rateio, IA e fluxo de ponta a ponta |
| `data/raw/` | dados de entrada do Charging Record |
| `outputs/` | banco, tabelas, gráficos e relatório gerados |

## Como executar

### Requisitos

- Python 3.10 ou superior;
- `pip` disponível;
- ambiente gráfico com Tkinter para abrir a interface desktop.

Execute os comandos a partir da raiz do repositório.

### 1. Criar e ativar um ambiente virtual

No Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

No Linux ou macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Instalar as dependências

```bash
python -m pip install -r requirements.txt
```

### 3. Executar o pipeline

```bash
python main.py executar
```

Esse comando recria o banco `outputs/ev_chargeops.db`, processa todos os meses e atualiza os CSVs, gráficos e o arquivo `outputs/relatorio_execucao.txt`.

> Atenção: uma nova execução recria o banco do zero e apaga decisões de revisão feitas anteriormente pelo gestor.

### 4. Abrir a interface desktop

```bash
python app/principal.py
```

A interface apresenta visão geral, faturas, sessões analisadas pela IA, revisão do gestor, simulação de rateio, perfis e previsões. Ela usa o mesmo banco e as mesmas regras de negócio da linha de comando.

### Comandos disponíveis

```bash
python main.py executar
python main.py pendencias
python main.py revisar 354 --aprovar
python main.py revisar 354 --rejeitar --obs "justificativa do gestor"
python main.py fatura 3
python main.py fatura 3 --mes 2026-09
python main.py gestor
python main.py gestor --mes 2026-09
python main.py usuarios
```

O identificador `354` é apenas um exemplo da execução de referência. Use `python main.py pendencias` para consultar os identificadores disponíveis no banco atual.

### Executar os testes

```bash
python -m pytest
```

A suíte atual possui 26 casos e cobre o rateio, as principais regras de anomalia e o fluxo integrado entre validação, IA, faturamento e revisão do gestor.

### Gerar novamente o CSV a partir do relatório SEMS+

```bash
python scripts/extrair_charging_record.py caminho/Charging_Record.pdf
```

O script extrai as sessões para `data/raw/charging_record.csv` e compara a soma encontrada com o total declarado no PDF.

## Saídas geradas

Após `python main.py executar`, a pasta `outputs/` contém:

- banco SQLite com todas as entidades processadas;
- sessões, faturas, itens, usuários, previsões e insights em CSV;
- relação das sessões retidas, descartadas ou inválidas;
- gráficos de consumo, anomalias, perfis, ocupação e previsão;
- relatório textual com o log de cada ciclo mensal.

Na execução de referência, a previsão Ridge apresentou erro médio absoluto de 50,7 kWh/mês em 28 previsões conferíveis. A linha de base que apenas repetia o mês anterior apresentou 57,8 kWh/mês. O ganho é positivo, mas ainda modesto, devido ao histórico de somente cinco meses e ao volume reduzido de dados reais.

## Decisões técnicas

- **SQLite com SQLAlchemy:** facilita a execução local sem servidor e mantém a camada de acesso preparada para outra URL de banco.
- **Competência pelo encerramento:** a sessão é faturada no mês em que terminou.
- **Tarifa híbrida por telemetria:** sessões que cruzam horários geram itens separados por faixa.
- **Medidor como fonte do total:** diferenças de arredondamento da telemetria não alteram o kWh total cobrado.
- **Revisão humana antes da cobrança:** a IA retém casos suspeitos, mas o gestor toma a decisão final.
- **Sessão interrompida é cobrada pelo registrado:** segue a regra definida na Sprint 01 e não é retida apenas por ter consumo parcial.
- **z-score por veículo:** evita comparar carros com capacidades de bateria diferentes pertencentes ao mesmo usuário.
- **Dados simulados determinísticos:** a semente fixa torna testes, demonstrações e resultados reproduzíveis.
- **Interface sem regra duplicada:** a aplicação desktop consulta o banco e chama os mesmos serviços de `src/` usados pela CLI.
- **Parâmetros centralizados:** tarifas, contribuição, margem, tolerâncias e limites podem ser alterados em `src/config.py`.

## Desvios em relação ao planejamento da Sprint 01

| Planejado na Sprint 01 | Implementado na Sprint 02 | Justificativa |
|---|---|---|
| PostgreSQL | SQLite via SQLAlchemy | Reduz a configuração necessária para a demonstração local. A abstração do SQLAlchemy preserva a possibilidade de migração futura. |
| Backend REST com FastAPI, CRUD e JWT | Pipeline e comandos locais em Python | A prioridade foi validar as regras centrais, o rateio e a IA antes de expor uma API. Autenticação ainda não faz parte do protótipo. |
| App mobile em React Native | Interface desktop em CustomTkinter | Permite demonstrar o fluxo completo com menor custo de integração e sem duplicar regras de negócio. Não substitui o app final planejado. |
| Dashboard web em React | Telas de gestão na aplicação desktop | Entrega os indicadores e a revisão de sessões em uma interface local adequada à prova de conceito. |
| Comandos `start/stop` via Modbus TCP | Processamento de sessões já encerradas | Não havia acesso de rede ao carregador durante a implementação. O protocolo permanece representado no cadastro, mas não há controle físico do equipamento. |
| Telemetria real via Modbus e SEMS+ | Charging Record real com telemetria reconstruída, somado a dados simulados | O relatório disponível contém início, fim, duração e energia, mas não leituras intermediárias. A reconstrução permite testar tarifa híbrida e ociosidade e fica identificada como estimada. |
| Insights por NLP ou templates | Templates auditáveis | Os textos usam resultados calculados pelos modelos e não geram números livres, o que facilita validação e rastreabilidade. |
| Regressão linear ou ARIMA | Regressão Ridge | Cinco meses são insuficientes para uma série temporal robusta. Ridge funciona com o conjunto tabular disponível e reduz instabilidade dos coeficientes. |
| Balanceamento dinâmico de carga | Recomendação de horário por tarifa e ocupação | O balanceamento exige telemetria e controle em tempo real dos carregadores, indisponíveis no protótipo local. |
| Entidade de método de pagamento e integração Pix/cartão | Pré-autorização e estorno apenas calculados | O protótipo valida a regra financeira, mas não opera um gateway nem armazena dados de pagamento. |
| Usuário sem sessão recebe fatura de R$ 0,00, conforme o diagrama | Plano mensal cobra apenas `C`; avulso não gera cobrança | A Sprint 01 continha uma contradição: a tabela de regras dizia que o plano mensal paga a contribuição fixa mesmo sem consumo. Foi adotada essa regra por ser coerente com a fórmula da modalidade mensal. |
| Deploy em Docker | Execução local com ambiente virtual | A entrega atual não possui serviços separados nem dependências externas que justifiquem a camada de contêiner para a demonstração. |

## Limites atuais

Este repositório demonstra a viabilidade funcional do núcleo da solução, mas ainda não é uma implantação de produção. Permanecem fora do escopo desta entrega:

- autenticação, autorização e gestão de credenciais;
- API pública e aplicação mobile;
- comunicação ao vivo com o GoodWe HCA G2;
- gateway de pagamento;
- balanceamento dinâmico de potência;
- operação multi-condomínio;
- migrações formais de banco, observabilidade e deploy;
- validação dos modelos com uma série histórica real mais longa.

Esses itens são as próximas evoluções naturais após a validação do rateio, da governança de anomalias e do fluxo de faturamento realizada nesta sprint.

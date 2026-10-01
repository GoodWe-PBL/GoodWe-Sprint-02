# Notas técnicas do protótipo (material para o README)

Este arquivo resume o que foi implementado, as decisões tomadas e os desvios em
relação à Sprint 01, para servir de base ao README.

## Como executar

```bash
pip install -r requirements.txt
python main.py executar            # roda o fluxo completo e gera tudo em outputs/
python main.py pendencias          # sessões que a IA reteve
python main.py revisar 354 --aprovar
python main.py fatura 3            # fatura detalhada do usuário 3 (último mês)
python main.py gestor              # visão do gestor
python -m pytest                   # 26 testes
```

Para regerar o CSV a partir do PDF exportado do SEMS+:
`python scripts/extrair_charging_record.py Charging_Record.pdf`

## Estrutura

| Pasta / arquivo | Conteúdo |
|---|---|
| `src/config.py` | tarifas, C, M, P, tolerâncias e parâmetros da IA |
| `src/db/` | modelo de dados (SQLAlchemy) e conexão |
| `src/ingestao/` | validação e normalização das sessões (etapa 4 da Sprint 01) |
| `src/rateio/` | faixas horárias, fórmulas das modalidades A e B, geração de faturas |
| `src/ia/` | anomalias, perfis, previsão, horários e insights |
| `src/simulacao/` | cenário (condomínio, usuários, veículos) e geração dos dados |
| `src/pipeline.py` | o ciclo mensal completo |
| `src/relatorios.py` | CSVs, gráficos e relatório de execução |
| `main.py` | linha de comando |
| `tests/` | testes do rateio, das regras da IA e do fluxo de ponta a ponta |

## Dados

- **Reais:** 97 sessões do carregador 57000HPA247L0002 (Charging Record de 05 a 09/2026,
  769,27 kWh, conferido contra o total do relatório). Todas pertencem a um único cartão,
  então foram atribuídas ao usuário "Energy Innovation Lab".
- **Telemetria dos dados reais:** o relatório não traz leituras intermediárias. Elas foram
  reconstruídas supondo carga a 3,5 kW (potência máxima desse carregador na API SEMS+,
  documentada na Sprint 01) e veículo parado depois disso. Ficam marcadas como `estimada`.
- **Simulados:** 9 usuários (7 moradores no plano mensal e 2 visitantes avulsos), 3
  carregadores adicionais e cerca de 280 sessões com telemetria a cada 5 min, calibradas
  pelo padrão dos dados reais. Casos excepcionais foram injetados de propósito: sessão
  acima de 12 h, energia maior que a bateria, queda brusca de potência, consumo fora do
  padrão, sessões interrompidas, registro corrompido e morador sem uso em um mês.

## Fluxo implementado (um ciclo por mês)

1. Ingestão e validação (sessões inválidas ficam com status `erro` e nunca são cobradas)
2. **IA – anomalias:** regras + Isolation Forest + z-score por veículo decidem se a sessão
   é `validada`, `em_revisao` ou `descartada`. **Só sessões validadas entram na fatura.**
3. **IA – perfis:** K-Means agrupa usuários pelo padrão de uso
4. Rateio: energia dividida por faixa horária a partir da telemetria; modalidades A e B;
   ociosidade com tolerância; contribuição fixa; pré-autorização e estorno no avulso
5. **IA – previsão:** regressão Ridge do kWh do mês seguinte (usa o perfil como variável)
6. **IA – horários e insights:** janela de início sugerida, economia estimada e textos
   anexados à fatura
7. O gestor revisa as sessões retidas; as aprovadas entram como ajuste na fatura aberta

## Decisões técnicas

- **Competência pelo horário de fim:** a sessão é faturada no mês em que terminou.
- **Tarifa híbrida:** a energia de cada intervalo de telemetria vai para a faixa do ponto
  médio do intervalo; o kWh cobrado é o do medidor, distribuído na proporção da telemetria.
- **Ociosidade (P):** tempo plugado após o fim da carga, menos 30 min de tolerância,
  cobrado pela `taxa_ocupacao_hora` da faixa onde ocorreu (zero no noturno).
- **Usuário sem consumo:** seguimos a tabela de regras da Sprint 01 (mensal paga C,
  avulso não paga nada). O diagrama de fluxo da Sprint 01 dizia "R$ 0,00 sem taxa mínima";
  as duas partes eram contraditórias e escolhemos a tabela de regras.
- **Valores assumidos** (não estavam fixados na Sprint 01): C = R$ 25,00/mês,
  M = R$ 0,40/kWh, tolerância de 30 min, pré-autorização avulsa de R$ 50,00.
- **Isolation Forest sem horário e sem kWh absoluto:** nos primeiros testes o modelo
  marcava quem carrega de dia e quem tem carro de bateria grande. Ficaram só grandezas
  físicas (duração, potência média, fração da bateria, ociosidade).
- **z-score por veículo, não por usuário:** quem tem dois carros era marcado indevidamente.
- **Sessões interrompidas** não são retidas pelo modelo: a regra da Sprint 01 já manda
  cobrar o que foi registrado.
- **Partida a frio:** no primeiro mês o Isolation Forest treina com o próprio mês e a
  previsão usa a média do cluster.

## Desvios em relação à Sprint 01

| Planejado | Implementado | Motivo |
|---|---|---|
| PostgreSQL | SQLite via SQLAlchemy | roda sem servidor; trocar é só mudar a URL de conexão |
| Comando start/stop via Modbus TCP | sessões chegam como registros já encerrados | sem acesso de rede ao carregador no protótipo |
| Backend FastAPI e app React Native | linha de comando (`main.py`) | o foco da sprint é a lógica central e a IA |
| Insights por NLP | templates preenchidos com as saídas dos modelos | auditável, não inventa números (a Sprint 01 já citava templates) |
| ARIMA como opção de previsão | Ridge com variáveis de histórico e perfil | apenas 5 meses de dados, insuficiente para série temporal |
| Balanceamento dinâmico de carga | não implementado | depende de controle em tempo real do carregador |
| Entidade MÉTODO_PAGAMENTO | omitida | não há gateway de pagamento no protótipo |

## Resultados da execução de referência

Ver `outputs/relatorio_execucao.txt`. Na execução de referência a previsão teve erro médio
absoluto de cerca de 51 kWh/mês, contra 58 kWh/mês de uma linha de base que repete o mês
anterior. Com só 5 meses de dados o ganho é modesto e isso deve ser dito com clareza.

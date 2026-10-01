"""
Parâmetros do EV ChargeOps.

Os valores de tarifa por faixa horária são os mesmos definidos na Sprint 01
(README, seção "Tarifas"). Os valores de C, M, tolerância de ociosidade e
pré-autorização não tinham número fixado na Sprint 01; foram assumidos aqui
e podem ser alterados sem mexer no restante do código.
"""
from datetime import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
CAMINHO_BANCO = RAIZ / "outputs" / "ev_chargeops.db"
CSV_REAL = RAIZ / "data" / "raw" / "charging_record.csv"
PASTA_SAIDA = RAIZ / "outputs"

# ---------------------------------------------------------------------------
# Tarifas por faixa horária (Sprint 01). Valor T já inclui impostos e bandeira.
# taxa_ocupacao_hora é a taxa cobrada por hora de ociosidade naquela faixa.
# ---------------------------------------------------------------------------
TARIFAS = [
    {"nome": "Tarifa Pico", "tipo_horario": "pico", "valor_kwh": 0.95,
     "taxa_ocupacao_hora": 2.00, "inicio": time(17, 0), "fim": time(22, 0)},
    {"nome": "Tarifa Intermediária", "tipo_horario": "intermediario", "valor_kwh": 0.75,
     "taxa_ocupacao_hora": 1.00, "inicio": time(7, 0), "fim": time(17, 0)},
    {"nome": "Tarifa Noturna", "tipo_horario": "fora_pico", "valor_kwh": 0.55,
     "taxa_ocupacao_hora": 0.00, "inicio": time(22, 0), "fim": time(7, 0)},
]

# ---------------------------------------------------------------------------
# Modelo de rateio (Sprint 01)
#   Modalidade A (mensal): F = Σ(E × T) + C + [P]
#   Modalidade B (avulsa): V = E × (T + M) + [P]
# ---------------------------------------------------------------------------
C_FIXO_MENSAL = 25.00          # R$ por mês (licenciamento + fundo de manutenção)
M_MARGEM_AVULSA = 0.40         # R$ por kWh somado à tarifa na carga avulsa
OCIOSIDADE_ATIVA = True        # o condomínio pode desligar a cobrança
TOLERANCIA_OCIOSIDADE_MIN = 30 # minutos plugado sem carregar antes de começar a cobrar
PRE_AUTORIZACAO_AVULSA = 50.00 # R$ reservados no Pix/cartão antes de liberar a carga

# ---------------------------------------------------------------------------
# Leitura de telemetria
# ---------------------------------------------------------------------------
INTERVALO_TELEMETRIA_MIN = 5   # granularidade das leituras (Sprint 01: 1 a 5 min)
POTENCIA_MINIMA_CARGA_KW = 0.1 # abaixo disso o veículo está plugado mas sem carregar

# ---------------------------------------------------------------------------
# Validação e IA
# ---------------------------------------------------------------------------
TOLERANCIA_DURACAO_MIN = 2         # diferença aceita entre duração informada e fim-início
ENERGIA_MINIMA_SESSAO_KWH = 0.05   # abaixo disso a sessão é considerada "fantasma"
LIMITE_SESSAO_LONGA_H = 12         # regra da Sprint 01: sessão > 12h é anômala
FATOR_MAX_BATERIA = 1.05           # energia acima de 105% da bateria é impossível
LIMITE_Z_VEICULO = 3.0             # desvio em relação ao histórico do próprio veículo
CONTAMINACAO_ISOLATION_FOREST = 0.02
MIN_AMOSTRAS_TREINO_IF = 40
N_CLUSTERS_PERFIL = 3
MIN_LINHAS_TREINO_PREVISAO = 8
SEMENTE = 42

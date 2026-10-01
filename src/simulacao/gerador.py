"""
Geração dos registros brutos de sessão, no formato em que o backend os receberia
do carregador (campos inspirados no getLastCharge da API SEMS+, Sprint 01) somados
às leituras de telemetria via Modbus TCP.

Duas fontes:
  1. carregar_registros_reais(): sessões do Charging Record (PDF -> CSV).
     O relatório não traz telemetria; ela é RECONSTRUÍDA supondo carga a 3,5 kW
     (potência máxima registrada para esse carregador) até atingir a energia
     informada, e veículo parado plugado depois disso. As leituras ficam marcadas
     como estimadas.
  2. gerar_registros_simulados(): sessões dos moradores/visitantes simulados,
     calibradas pelo padrão real (início à noite, 2–4 kW médios, 3–6 h plugado),
     com casos excepcionais injetados de propósito (anomalias, interrupção,
     registro inválido, usuário sem consumo no mês).
"""
import csv
import math
import random
from datetime import date, datetime, timedelta

import numpy as np

from src import config
from src.simulacao.cadastro import VEICULOS

PASSO = timedelta(minutes=config.INTERVALO_TELEMETRIA_MIN)
INICIO_PERIODO = date(2026, 5, 1)
FIM_PERIODO = date(2026, 9, 30)
POTENCIA_LAB_KW = 3.5


# ---------------------------------------------------------------------------
# Curva de carga
# ---------------------------------------------------------------------------
def curva_de_carga(inicio: datetime, energia_alvo: float, potencia_kw: float,
                   fim: datetime, bateria_kwh: float, soc_inicial: float | None,
                   rng: random.Random, queda: tuple[datetime, datetime] | None = None):
    """Gera as leituras de 5 em 5 min entre inicio e fim.

    Carrega em potência quase constante, reduz a potência no fim da carga
    (acima de 85% de SOC), e depois fica com potência zero (ociosidade).
    `queda` força um intervalo com potência quase nula no meio da carga.
    """
    leituras, energia, t = [], 0.0, inicio
    while True:
        restante = energia_alvo - energia
        if restante > 1e-6:
            p = potencia_kw * rng.uniform(0.96, 1.02)
            if soc_inicial is not None and bateria_kwh:
                soc = soc_inicial + energia / bateria_kwh
                if soc > 0.85:
                    p *= max(0.35, 1 - (soc - 0.85) / 0.15 * 0.65)
            if queda and queda[0] <= t < queda[1]:
                p = rng.uniform(0.05, 0.2)
            estado = "charging"
        else:
            p, estado = 0.0, "finished_idle"
        leituras.append({"timestamp": t, "potencia_kw": round(p, 3),
                         "energia_kwh": round(energia, 4), "work_state": estado})
        if t >= fim:
            break
        proximo = min(t + PASSO, fim)
        horas = (proximo - t).total_seconds() / 3600
        energia = min(energia_alvo, energia + p * horas)
        t = proximo
    return leituras


# ---------------------------------------------------------------------------
# 1. Dados reais
# ---------------------------------------------------------------------------
def _dur_para_min(txt: str) -> int:
    h, m, s = (int(x) for x in txt.split(":"))
    return h * 60 + m + round(s / 60)


def carregar_registros_reais(caminho=config.CSV_REAL) -> list[dict]:
    rng = random.Random(config.SEMENTE)
    registros = []
    with open(caminho, encoding="utf-8") as f:
        for linha in csv.DictReader(f):
            inicio = datetime.strptime(linha["inicio"], "%m/%d/%Y %H:%M")
            fim = datetime.strptime(linha["fim"], "%m/%d/%Y %H:%M")
            energia = float(linha["energia_kwh"])
            duracao = _dur_para_min(linha["duracao"])
            horas = max(duracao / 60, 1 / 60)
            potencia = max(POTENCIA_LAB_KW, energia / horas * 1.06)  # folga p/ a curva fechar a energia
            leituras = curva_de_carga(inicio, energia, potencia, fim, 38.0, None, rng)
            registros.append({
                "chargePileSN": linha["serial_carregador"],
                "chargeCardNumber": linha["card_id"],
                "usuario_id": 1,  # cartão do laboratório -> usuário "Energy Innovation Lab"
                "veiculo_id": 1,
                "inicio": inicio, "fim": fim,
                "chargeTimeLength": duracao,
                "currentChargeQuantity": energia,
                "maxCharP": round(max(l["potencia_kw"] for l in leituras), 2),
                "encerramento": "normal",
                "origem": "real",
                "telemetria_estimada": True,
                "leituras": leituras,
            })
    return registros


# ---------------------------------------------------------------------------
# 2. Dados simulados
# ---------------------------------------------------------------------------
def _hora(rng, media, desvio):
    """Sorteia um horário (em horas decimais) em torno da média, com volta no dia."""
    return (rng.gauss(media, desvio)) % 24


# Cada perfil diz: chance de carregar no dia, horário de chegada, quanto da
# bateria repõe e por quanto tempo o carro fica plugado depois de carregar.
PERFIS = {
    2: dict(chance=0.32, dias="todos", chegada=(22.6, 0.5), soc=(0.25, 0.55), alvo=0.9,
            saida_manha=(6.9, 0.4)),
    3: dict(chance=0.35, dias="uteis", chegada=(18.3, 0.5), soc=(0.30, 0.60), alvo=0.85,
            ocioso_medio_min=70),
    4: dict(chance=0.30, dias="todos", chegada=None, soc=(0.30, 0.60), alvo=0.9,
            ocioso_medio_min=90),
    5: dict(chance=0.50, dias="fds", chegada=(10.0, 1.2), soc=(0.25, 0.55), alvo=0.95,
            ocioso_medio_min=40),
    6: dict(chance=0.32, dias="uteis", chegada=(9.5, 1.0), soc=(0.30, 0.55), alvo=0.9,
            ocioso_medio_min=120),
    7: dict(chance=0.30, dias="todos", chegada=(21.0, 0.6), soc=(0.30, 0.60), alvo=0.85,
            ocioso_medio_min=45, sem_uso=(date(2026, 7, 1), date(2026, 7, 31))),
    8: dict(chance=0.32, dias="todos", chegada=(20.0, 1.0), soc=(0.30, 0.60), alvo=0.9,
            ocioso_medio_min=60, desde=date(2026, 8, 1)),
    9: dict(chance=0.07, dias="todos", chegada=(14.0, 2.0), soc=(0.40, 0.65), alvo=0.8,
            ocioso_medio_min=20),
    10: dict(chance=0.10, dias="todos", chegada=(19.0, 1.5), soc=(0.35, 0.60), alvo=0.8,
             ocioso_medio_min=25),
}


def _veiculos_do_usuario(uid):
    return [v for v in VEICULOS if v["usuario_id"] == uid]


def _dia_permitido(perfil, dia: date) -> bool:
    if perfil["dias"] == "uteis" and dia.weekday() >= 5:
        return False
    if perfil["dias"] == "fds" and dia.weekday() < 5:
        return False
    if "sem_uso" in perfil and perfil["sem_uso"][0] <= dia <= perfil["sem_uso"][1]:
        return False
    if "desde" in perfil and dia < perfil["desde"]:
        return False
    return True


class Agenda:
    """Ocupação dos carregadores simulados, para duas sessões não usarem o
    mesmo carregador ao mesmo tempo."""

    def __init__(self, carregadores=("SIM-HCA-0002", "SIM-HCA-0003", "SIM-HCA-0004")):
        self.ocupacao = {sn: [] for sn in carregadores}

    def reservar(self, inicio, fim, rng):
        livres = [sn for sn, ints in self.ocupacao.items()
                  if all(fim <= a or inicio >= b for a, b in ints)]
        if not livres:
            return None
        sn = rng.choice(livres)
        self.ocupacao[sn].append((inicio, fim))
        return sn


def _montar_sessao(uid, veiculo, inicio, perfil, rng, agenda, forcar=None):
    forcar = forcar or {}
    bateria = veiculo["capacidade_bateria_kwh"]
    soc0 = forcar.get("soc0", rng.uniform(*perfil["soc"]))
    energia_alvo = round(bateria * (perfil["alvo"] - soc0), 2)
    potencia = min(veiculo["potencia_obc_kw"], 7.0) * rng.uniform(0.9, 0.97)
    horas_carga = energia_alvo / potencia * 1.08  # margem pelo afunilamento final
    if "saida_manha" in perfil:
        saida = inicio.replace(hour=0, minute=0) + timedelta(days=1, hours=_hora(rng, *perfil["saida_manha"]))
        fim = max(saida, inicio + timedelta(hours=horas_carga))
    else:
        ocioso = rng.expovariate(1 / perfil["ocioso_medio_min"])
        fim = inicio + timedelta(hours=horas_carga, minutes=ocioso)
    if "duracao_h" in forcar:
        fim = inicio + timedelta(hours=forcar["duracao_h"])
    fim = fim.replace(second=0, microsecond=0)

    sn = agenda.reservar(inicio, fim, rng)
    tentativas = 0
    while sn is None and tentativas < 4:  # carregadores cheios: o morador volta 30 min depois
        inicio += timedelta(minutes=30)
        fim += timedelta(minutes=30)
        sn = agenda.reservar(inicio, fim, rng)
        tentativas += 1
    if sn is None:
        return None

    queda = None
    if forcar.get("queda"):
        q0 = inicio + timedelta(hours=1)
        queda = (q0, q0 + timedelta(minutes=45))
        fim += timedelta(minutes=45)
    leituras = curva_de_carga(inicio, energia_alvo, potencia, fim, bateria, soc0, rng, queda)

    encerramento = "normal"
    if forcar.get("interromper"):
        # perda de conexão no meio da carga: só existem leituras até o corte
        corte = max(2, int(len(leituras) * rng.uniform(0.3, 0.6)))
        leituras = leituras[:corte]
        fim = leituras[-1]["timestamp"]
        encerramento = "interrompida"

    energia_registrada = leituras[-1]["energia_kwh"]
    energia_informada = forcar.get("energia_informada", energia_registrada)
    return {
        "chargePileSN": sn, "chargeCardNumber": None,
        "usuario_id": uid, "veiculo_id": veiculo["id"],
        "inicio": inicio, "fim": fim,
        "chargeTimeLength": int((fim - inicio).total_seconds() // 60),
        "currentChargeQuantity": round(energia_informada, 2),
        "maxCharP": round(max(l["potencia_kw"] for l in leituras), 2),
        "encerramento": encerramento, "origem": "simulada",
        "telemetria_estimada": False, "leituras": leituras,
    }


# Casos excepcionais injetados (data, usuário, o que forçar). Servem para provar
# que as regras e a IA reagem a eles.
CASOS_INJETADOS = [
    # sessão > 12h com pouca energia (regra da Sprint 01)
    (datetime(2026, 8, 15, 8, 10), 5, {"duracao_h": 15.5, "soc0": 0.75}),
    # medidor informa mais energia do que cabe na bateria (e diverge da telemetria)
    (datetime(2026, 6, 10, 9, 40), 6, {"energia_informada": 58.0}),
    # queda brusca de potência no meio da carga
    (datetime(2026, 9, 8, 22, 40), 2, {"queda": True}),
    # consumo muito fora do padrão do usuário (repõe quase a bateria inteira no pico)
    (datetime(2026, 9, 16, 17, 50), 3, {"soc0": 0.03}),
    # sessões interrompidas por perda de conectividade
    (datetime(2026, 6, 23, 18, 20), 3, {"interromper": True}),
    (datetime(2026, 8, 4, 22, 50), 2, {"interromper": True}),
    (datetime(2026, 9, 12, 19, 5), 10, {"interromper": True}),
]


def gerar_registros_simulados(semente: int = config.SEMENTE) -> list[dict]:
    rng = random.Random(semente)
    np.random.seed(semente)
    agenda = Agenda()
    registros = []

    # 1) casos injetados primeiro, para garantir vaga na agenda
    for inicio, uid, forcar in CASOS_INJETADOS:
        veiculo = _veiculos_do_usuario(uid)[0]
        sessao = _montar_sessao(uid, veiculo, inicio, PERFIS[uid], rng, agenda, forcar)
        if sessao:
            sessao["caso_injetado"] = forcar
            registros.append(sessao)

    # 2) rotina normal de cada usuário simulado
    dia = INICIO_PERIODO
    while dia <= FIM_PERIODO:
        for uid, perfil in PERFIS.items():
            if not _dia_permitido(perfil, dia) or rng.random() > perfil["chance"]:
                continue
            veiculos = _veiculos_do_usuario(uid)
            veiculo = veiculos[0] if len(veiculos) == 1 or rng.random() < 0.6 else veiculos[1]
            if perfil["chegada"] is None:  # Ana: metade no começo da noite, metade tarde
                h = _hora(rng, 19.8, 0.6) if rng.random() < 0.5 else _hora(rng, 23.0, 0.4)
            else:
                h = _hora(rng, *perfil["chegada"])
            inicio = datetime.combine(dia, datetime.min.time()) + timedelta(hours=h)
            inicio = inicio.replace(second=0, microsecond=0)
            sessao = _montar_sessao(uid, veiculo, inicio, perfil, rng, agenda)
            if sessao and sessao["fim"].date() <= FIM_PERIODO:
                registros.append(sessao)
        dia += timedelta(days=1)

    # 3) um registro corrompido (fim antes do início) para testar a validação
    registros.append({
        "chargePileSN": "SIM-HCA-0002", "chargeCardNumber": None,
        "usuario_id": 8, "veiculo_id": 9,
        "inicio": datetime(2026, 8, 20, 21, 0), "fim": datetime(2026, 8, 20, 19, 0),
        "chargeTimeLength": 120, "currentChargeQuantity": 9.4, "maxCharP": 6.2,
        "encerramento": "normal", "origem": "simulada", "telemetria_estimada": False,
        "leituras": [], "caso_injetado": {"registro_invalido": True},
    })
    registros.sort(key=lambda r: r["fim"])
    return registros

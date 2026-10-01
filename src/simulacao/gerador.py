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

Os sorteios usam um gerador com semente fixa ("sorteio"), então toda execução
produz exatamente os mesmos dados. SOC = nível da bateria (0 a 1).
"""
import csv
import random
from datetime import date, datetime, time, timedelta

import numpy as np

from src import config
from src.simulacao.cadastro import VEICULOS

INTERVALO_ENTRE_LEITURAS = timedelta(minutes=config.INTERVALO_TELEMETRIA_MIN)
INICIO_PERIODO = date(2026, 5, 1)
FIM_PERIODO = date(2026, 9, 30)
POTENCIA_LAB_KW = 3.5
CARREGADORES_SIMULADOS = ("SIM-HCA-0002", "SIM-HCA-0003", "SIM-HCA-0004")


# ---------------------------------------------------------------------------
# Curva de carga
# ---------------------------------------------------------------------------
def curva_de_carga(inicio, energia_alvo, potencia_kw, fim, bateria_kwh, soc_inicial, sorteio,
                   queda=None):
    """Gera as leituras de 5 em 5 min entre inicio e fim.

    Carrega em potência quase constante, reduz a potência no fim da carga
    (acima de 85% de SOC), e depois fica com potência zero (ociosidade).
    queda (opcional) é um par (início, fim) de um intervalo em que a potência é
    forçada a ficar quase nula no meio da carga.
    """
    leituras = []
    energia = 0.0
    instante = inicio
    while True:
        ainda_falta_energia = energia_alvo - energia > 1e-6
        if ainda_falta_energia:
            potencia = potencia_kw * sorteio.uniform(0.96, 1.02)  # pequena oscilação natural
            if soc_inicial is not None and bateria_kwh:
                soc = soc_inicial + energia / bateria_kwh
                if soc > 0.85:
                    # bateria quase cheia: a potência cai aos poucos, até no mínimo 35%
                    potencia *= max(0.35, 1 - (soc - 0.85) / 0.15 * 0.65)
            if queda and queda[0] <= instante < queda[1]:
                potencia = sorteio.uniform(0.05, 0.2)
            estado = "charging"
        else:
            potencia = 0.0
            estado = "finished_idle"

        leituras.append({"timestamp": instante, "potencia_kw": round(potencia, 3),
                         "energia_kwh": round(energia, 4), "work_state": estado})
        if instante >= fim:
            break
        proximo_instante = min(instante + INTERVALO_ENTRE_LEITURAS, fim)
        horas = (proximo_instante - instante).total_seconds() / 3600
        energia = min(energia_alvo, energia + potencia * horas)  # energia = potência x tempo
        instante = proximo_instante
    return leituras


def potencia_maxima(leituras):
    return round(max(leitura["potencia_kw"] for leitura in leituras), 2)


# ---------------------------------------------------------------------------
# 1. Dados reais
# ---------------------------------------------------------------------------
def duracao_em_minutos(texto):
    """'03:25:40' -> 206 (os segundos são arredondados para o minuto)."""
    horas, minutos, segundos = (int(parte) for parte in texto.split(":"))
    return horas * 60 + minutos + round(segundos / 60)


def carregar_registros_reais(caminho=config.CSV_REAL):
    """Lê o CSV do Charging Record e monta um registro por sessão real."""
    sorteio = random.Random(config.SEMENTE)
    registros = []
    with open(caminho, encoding="utf-8") as arquivo:
        for linha in csv.DictReader(arquivo):
            inicio = datetime.strptime(linha["inicio"], "%m/%d/%Y %H:%M")
            fim = datetime.strptime(linha["fim"], "%m/%d/%Y %H:%M")
            energia = float(linha["energia_kwh"])
            duracao = duracao_em_minutos(linha["duracao"])
            horas = max(duracao / 60, 1 / 60)
            # 6% de folga na potência para a curva conseguir fechar a energia informada
            potencia = max(POTENCIA_LAB_KW, energia / horas * 1.06)
            leituras = curva_de_carga(inicio, energia, potencia, fim, 38.0, None, sorteio)
            registros.append({
                "chargePileSN": linha["serial_carregador"],
                "chargeCardNumber": linha["card_id"],
                "usuario_id": 1,  # cartão do laboratório -> usuário "Energy Innovation Lab"
                "veiculo_id": 1,
                "inicio": inicio, "fim": fim,
                "chargeTimeLength": duracao,
                "currentChargeQuantity": energia,
                "maxCharP": potencia_maxima(leituras),
                "encerramento": "normal",
                "origem": "real",
                "telemetria_estimada": True,
                "leituras": leituras,
            })
    return registros


# ---------------------------------------------------------------------------
# 2. Dados simulados
# ---------------------------------------------------------------------------
def sortear_hora(sorteio, media, desvio):
    """Sorteia um horário (em horas decimais) em torno da média, com volta no dia."""
    return sorteio.gauss(media, desvio) % 24


# Comportamento de cada usuário simulado (a chave é o id do usuário):
#   chance: probabilidade de carregar em um dia permitido
#   dias: "todos", "uteis" ou "fds"
#   chegada: (hora média, desvio) em que pluga o carro; None = caso especial da Ana
#   soc: (mínimo, máximo) do nível da bateria ao chegar
#   alvo: nível da bateria até onde carrega
#   ocioso_medio_min: tempo médio plugado depois de carregar
#   saida_manha: (hora média, desvio) em que tira o carro no dia seguinte
#   sem_uso: período sem nenhuma sessão; desde: data em que começou a usar
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


def veiculos_do_usuario(usuario_id):
    return [veiculo for veiculo in VEICULOS if veiculo["usuario_id"] == usuario_id]


def dia_permitido(perfil, dia):
    """O usuário deste perfil pode carregar neste dia?"""
    fim_de_semana = dia.weekday() >= 5  # 5 = sábado, 6 = domingo
    if perfil["dias"] == "uteis" and fim_de_semana:
        return False
    if perfil["dias"] == "fds" and not fim_de_semana:
        return False
    if "sem_uso" in perfil and perfil["sem_uso"][0] <= dia <= perfil["sem_uso"][1]:
        return False
    if "desde" in perfil and dia < perfil["desde"]:
        return False
    return True


def reservar_carregador(reservas, inicio, fim, sorteio):
    """Escolhe um carregador livre no período e anota a reserva, para duas
    sessões não usarem o mesmo carregador ao mesmo tempo.

    reservas é um dicionário: número de série -> lista de (início, fim) já ocupados.
    Devolve o número de série escolhido, ou None se todos estiverem ocupados.
    """
    livres = []
    for numero_de_serie, periodos in reservas.items():
        livre = True
        for inicio_ocupado, fim_ocupado in periodos:
            if not (fim <= inicio_ocupado or inicio >= fim_ocupado):
                livre = False  # os dois períodos se sobrepõem
        if livre:
            livres.append(numero_de_serie)
    if not livres:
        return None
    escolhido = sorteio.choice(livres)
    reservas[escolhido].append((inicio, fim))
    return escolhido


def montar_sessao(usuario_id, veiculo, inicio, perfil, sorteio, reservas, forcar=None):
    """Monta o registro de uma sessão simulada. forcar (opcional) impõe um caso
    excepcional: soc0, duracao_h, energia_informada, queda ou interromper.
    Devolve None se não houver carregador livre."""
    forcar = forcar or {}
    bateria = veiculo["capacidade_bateria_kwh"]
    # o sorteio do SOC é feito sempre, mesmo quando o valor é forçado, para a
    # sequência de números aleatórios (e portanto os dados gerados) não mudar
    soc_sorteado = sorteio.uniform(*perfil["soc"])
    soc_inicial = forcar.get("soc0", soc_sorteado)
    energia_alvo = round(bateria * (perfil["alvo"] - soc_inicial), 2)
    # 7 kW é o limite do carregador; o veículo pode aceitar menos que isso
    potencia = min(veiculo["potencia_obc_kw"], 7.0) * sorteio.uniform(0.9, 0.97)
    horas_de_carga = energia_alvo / potencia * 1.08  # margem pela redução de potência no final

    if "saida_manha" in perfil:
        # fica plugado a noite toda e sai de manhã (ou quando a carga terminar, se for depois)
        meia_noite = inicio.replace(hour=0, minute=0)
        saida = meia_noite + timedelta(days=1, hours=sortear_hora(sorteio, *perfil["saida_manha"]))
        fim = max(saida, inicio + timedelta(hours=horas_de_carga))
    else:
        minutos_ocioso = sorteio.expovariate(1 / perfil["ocioso_medio_min"])
        fim = inicio + timedelta(hours=horas_de_carga, minutes=minutos_ocioso)
    if "duracao_h" in forcar:
        fim = inicio + timedelta(hours=forcar["duracao_h"])
    fim = fim.replace(second=0, microsecond=0)

    # carregadores cheios: o morador volta 30 min depois (até 4 tentativas)
    numero_de_serie = reservar_carregador(reservas, inicio, fim, sorteio)
    tentativas = 0
    while numero_de_serie is None and tentativas < 4:
        inicio += timedelta(minutes=30)
        fim += timedelta(minutes=30)
        numero_de_serie = reservar_carregador(reservas, inicio, fim, sorteio)
        tentativas += 1
    if numero_de_serie is None:
        return None

    queda = None
    if forcar.get("queda"):
        # 45 min de potência quase nula, começando 1 h depois do início
        inicio_da_queda = inicio + timedelta(hours=1)
        queda = (inicio_da_queda, inicio_da_queda + timedelta(minutes=45))
        fim += timedelta(minutes=45)
    leituras = curva_de_carga(inicio, energia_alvo, potencia, fim, bateria, soc_inicial, sorteio, queda)

    encerramento = "normal"
    if forcar.get("interromper"):
        # perda de conexão no meio da carga: só existem leituras até o corte
        corte = max(2, int(len(leituras) * sorteio.uniform(0.3, 0.6)))
        leituras = leituras[:corte]
        fim = leituras[-1]["timestamp"]
        encerramento = "interrompida"

    energia_registrada = leituras[-1]["energia_kwh"]
    energia_informada = forcar.get("energia_informada", energia_registrada)
    return {
        "chargePileSN": numero_de_serie, "chargeCardNumber": None,
        "usuario_id": usuario_id, "veiculo_id": veiculo["id"],
        "inicio": inicio, "fim": fim,
        "chargeTimeLength": int((fim - inicio).total_seconds() // 60),
        "currentChargeQuantity": round(energia_informada, 2),
        "maxCharP": potencia_maxima(leituras),
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


def sortear_inicio(dia, perfil, sorteio):
    """Sorteia a data e hora em que o usuário pluga o carro neste dia."""
    if perfil["chegada"] is None:
        # Ana: metade das vezes no começo da noite, metade tarde da noite
        if sorteio.random() < 0.5:
            hora = sortear_hora(sorteio, 19.8, 0.6)
        else:
            hora = sortear_hora(sorteio, 23.0, 0.4)
    else:
        hora = sortear_hora(sorteio, *perfil["chegada"])
    inicio = datetime.combine(dia, time(0, 0)) + timedelta(hours=hora)
    return inicio.replace(second=0, microsecond=0)


def gerar_registros_simulados(semente=config.SEMENTE):
    """Gera as sessões dos usuários simulados para todo o período."""
    sorteio = random.Random(semente)
    np.random.seed(semente)
    reservas = {numero_de_serie: [] for numero_de_serie in CARREGADORES_SIMULADOS}
    registros = []

    # 1) casos injetados primeiro, para garantir vaga nos carregadores
    for inicio, usuario_id, forcar in CASOS_INJETADOS:
        veiculo = veiculos_do_usuario(usuario_id)[0]
        sessao = montar_sessao(usuario_id, veiculo, inicio, PERFIS[usuario_id], sorteio, reservas, forcar)
        if sessao:
            sessao["caso_injetado"] = forcar
            registros.append(sessao)

    # 2) rotina normal de cada usuário simulado, dia após dia
    dia = INICIO_PERIODO
    while dia <= FIM_PERIODO:
        for usuario_id, perfil in PERFIS.items():
            if not dia_permitido(perfil, dia):
                continue
            if sorteio.random() > perfil["chance"]:
                continue  # hoje este usuário não carregou
            veiculos = veiculos_do_usuario(usuario_id)
            # quem tem dois carros usa o primeiro em 60% das vezes
            if len(veiculos) == 1 or sorteio.random() < 0.6:
                veiculo = veiculos[0]
            else:
                veiculo = veiculos[1]
            inicio = sortear_inicio(dia, perfil, sorteio)
            sessao = montar_sessao(usuario_id, veiculo, inicio, perfil, sorteio, reservas)
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
    registros.sort(key=lambda registro: registro["fim"])  # ordem cronológica de encerramento
    return registros

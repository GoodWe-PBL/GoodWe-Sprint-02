"""
Funções puras de tarifação: em que faixa horária cai um instante, como dividir a
energia de uma sessão entre faixas e quanto tempo de ociosidade é cobrável.

"leituras" é sempre uma lista de dicts em ordem cronológica:
    {"timestamp": datetime, "potencia_kw": float, "energia_kwh": float}
onde energia_kwh é a energia acumulada até aquele instante.
"""
from datetime import datetime, timedelta

from src import config


def faixa_horaria(instante, tarifas=None):
    """Devolve a tarifa (dict) vigente no horário informado.

    instante pode ser um datetime (data e hora) ou um time (só a hora).
    """
    tarifas = tarifas or config.TARIFAS
    if isinstance(instante, datetime):
        horario = instante.time()
    else:
        horario = instante

    for tarifa in tarifas:
        inicio, fim = tarifa["inicio"], tarifa["fim"]
        if inicio < fim:
            dentro_da_faixa = inicio <= horario < fim
        else:
            # faixa que atravessa a meia-noite (22h -> 07h): vale do início até
            # o fim do dia e do começo do dia até o fim da faixa
            dentro_da_faixa = horario >= inicio or horario < fim
        if dentro_da_faixa:
            return tarifa
    raise ValueError(f"Nenhuma faixa tarifária cobre o horário {horario}")


def dividir_energia_por_faixa(leituras, tarifas=None):
    """Soma a energia entregue em cada faixa horária. Devolve {faixa: kWh}.

    A energia de cada intervalo entre duas leituras é atribuída à faixa do ponto
    médio do intervalo. Com leituras de 5 minutos o erro máximo é de 2,5 min de
    energia na virada de faixa. É isso que permite cobrar uma sessão que começou
    no pico e terminou de madrugada com duas tarifas diferentes (caso "tarifa
    híbrida" da Sprint 01).
    """
    energia_por_faixa = {}
    for posicao in range(1, len(leituras)):
        anterior, atual = leituras[posicao - 1], leituras[posicao]
        energia_do_intervalo = atual["energia_kwh"] - anterior["energia_kwh"]
        if energia_do_intervalo <= 0:
            continue
        meio_do_intervalo = anterior["timestamp"] + (atual["timestamp"] - anterior["timestamp"]) / 2
        faixa = faixa_horaria(meio_do_intervalo, tarifas)["tipo_horario"]
        energia_por_faixa[faixa] = energia_por_faixa.get(faixa, 0.0) + energia_do_intervalo

    for faixa in energia_por_faixa:
        energia_por_faixa[faixa] = round(energia_por_faixa[faixa], 4)
    return energia_por_faixa


def fim_da_carga(leituras):
    """Instante em que a energia parou de subir pela última vez."""
    ultimo_instante_carregando = leituras[0]["timestamp"]
    for posicao in range(1, len(leituras)):
        anterior, atual = leituras[posicao - 1], leituras[posicao]
        if atual["energia_kwh"] - anterior["energia_kwh"] > 1e-6:  # 1e-6: ignora ruído de arredondamento
            ultimo_instante_carregando = atual["timestamp"]
    return ultimo_instante_carregando


def minutos_ociosos(leituras):
    """Tempo plugado após a carga terminar (veículo parado ocupando a vaga)."""
    if len(leituras) < 2:
        return 0
    tempo_ocioso = leituras[-1]["timestamp"] - fim_da_carga(leituras)
    return int(tempo_ocioso.total_seconds() // 60)


def ociosidade_cobravel_por_faixa(leituras, tolerancia_min=None, tarifas=None):
    """Horas de ociosidade cobráveis em cada faixa, já descontada a tolerância.
    Devolve {faixa: horas}.

    A taxa de ociosidade (P) da Sprint 01 é por hora e depende do horário: a
    taxa_ocupacao_hora da faixa onde o carro ficou parado (no noturno ela é zero,
    no pico é a mais cara).
    """
    if tolerancia_min is None:
        tolerancia_min = config.TOLERANCIA_OCIOSIDADE_MIN
    if len(leituras) < 2:
        return {}

    inicio_da_cobranca = fim_da_carga(leituras) + timedelta(minutes=tolerancia_min)
    fim_da_sessao = leituras[-1]["timestamp"]

    # anda de minuto em minuto e soma 1/60 de hora na faixa de cada minuto
    horas_por_faixa = {}
    instante = inicio_da_cobranca
    while instante < fim_da_sessao:
        faixa = faixa_horaria(instante, tarifas)["tipo_horario"]
        horas_por_faixa[faixa] = horas_por_faixa.get(faixa, 0.0) + 1 / 60
        instante += timedelta(minutes=1)

    for faixa in horas_por_faixa:
        horas_por_faixa[faixa] = round(horas_por_faixa[faixa], 4)
    return horas_por_faixa

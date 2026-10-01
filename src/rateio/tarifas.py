"""
Funções puras de tarifação: em que faixa horária cai um instante, como dividir a
energia de uma sessão entre faixas e quanto tempo de ociosidade é cobrável.

"leituras" é sempre uma lista de dicts em ordem cronológica:
    {"timestamp": datetime, "potencia_kw": float, "energia_kwh": float}
onde energia_kwh é a energia acumulada até aquele instante.
"""
from collections import defaultdict
from datetime import datetime, time, timedelta

from src import config


def faixa_horaria(instante: datetime | time, tarifas=None) -> dict:
    """Devolve a tarifa (dict) vigente no horário informado.

    Faixas que atravessam a meia-noite (22h -> 07h) são tratadas pelo caso
    inicio > fim.
    """
    tarifas = tarifas or config.TARIFAS
    t = instante.time() if isinstance(instante, datetime) else instante
    for tarifa in tarifas:
        ini, fim = tarifa["inicio"], tarifa["fim"]
        if ini < fim:
            if ini <= t < fim:
                return tarifa
        elif t >= ini or t < fim:  # faixa que vira o dia
            return tarifa
    raise ValueError(f"Nenhuma faixa tarifária cobre o horário {t}")


def dividir_energia_por_faixa(leituras: list[dict], tarifas=None) -> dict[str, float]:
    """Soma a energia entregue em cada faixa horária.

    A energia de cada intervalo entre duas leituras é atribuída à faixa do ponto
    médio do intervalo. Com leituras de 5 minutos o erro máximo é de 2,5 min de
    energia na virada de faixa. É isso que permite cobrar uma sessão que começou
    no pico e terminou de madrugada com duas tarifas diferentes (caso "tarifa
    híbrida" da Sprint 01).
    """
    por_faixa: dict[str, float] = defaultdict(float)
    for anterior, atual in zip(leituras, leituras[1:]):
        delta = atual["energia_kwh"] - anterior["energia_kwh"]
        if delta <= 0:
            continue
        meio = anterior["timestamp"] + (atual["timestamp"] - anterior["timestamp"]) / 2
        por_faixa[faixa_horaria(meio, tarifas)["tipo_horario"]] += delta
    return {k: round(v, 4) for k, v in por_faixa.items()}


def fim_da_carga(leituras: list[dict]) -> datetime:
    """Instante em que a energia parou de subir pela última vez."""
    ultimo = leituras[0]["timestamp"]
    for anterior, atual in zip(leituras, leituras[1:]):
        if atual["energia_kwh"] - anterior["energia_kwh"] > 1e-6:
            ultimo = atual["timestamp"]
    return ultimo


def minutos_ociosos(leituras: list[dict]) -> int:
    """Tempo plugado após a carga terminar (veículo parado ocupando a vaga)."""
    if len(leituras) < 2:
        return 0
    return int((leituras[-1]["timestamp"] - fim_da_carga(leituras)).total_seconds() // 60)


def ociosidade_cobravel_por_faixa(leituras: list[dict],
                                  tolerancia_min: int | None = None,
                                  tarifas=None) -> dict[str, float]:
    """Horas de ociosidade cobráveis em cada faixa, já descontada a tolerância.

    A taxa de ociosidade (P) da Sprint 01 é por hora e depende do horário: a
    taxa_ocupacao_hora da faixa onde o carro ficou parado (no noturno ela é zero,
    no pico é a mais cara).
    """
    tolerancia_min = config.TOLERANCIA_OCIOSIDADE_MIN if tolerancia_min is None else tolerancia_min
    if len(leituras) < 2:
        return {}
    inicio_cobranca = fim_da_carga(leituras) + timedelta(minutes=tolerancia_min)
    fim = leituras[-1]["timestamp"]
    horas: dict[str, float] = defaultdict(float)
    instante = inicio_cobranca
    while instante < fim:
        horas[faixa_horaria(instante, tarifas)["tipo_horario"]] += 1 / 60
        instante += timedelta(minutes=1)
    return {k: round(v, 4) for k, v in horas.items()}

"""
IA — Otimização de horário (Etapa 6 da Sprint 01).

Combina duas coisas:
  1. ocupação histórica dos carregadores por hora do dia (onde há folga);
  2. a tarifa de cada faixa e o perfil de uso da pessoa.
Resultado: uma janela de início sugerida, com a economia estimada em reais se as
cargas feitas no pico tivessem sido feitas nessa janela.
"""
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from src import config
from src.rateio.tarifas import faixa_horaria


def ocupacao_por_hora(sessoes: pd.DataFrame, n_carregadores: int) -> pd.Series:
    """Fração média de carregadores ocupados em cada hora (0–23)."""
    if sessoes.empty:
        return pd.Series(0.0, index=range(24))
    horas_ocupadas = np.zeros(24)
    dias = set()
    for ini, fim in zip(sessoes["inicio"], sessoes["fim"]):
        t = ini.replace(minute=0, second=0)
        while t < fim:
            horas_ocupadas[t.hour] += 1
            dias.add(t.date())
            t += timedelta(hours=1)
    n_dias = max(len(dias), 1)
    return pd.Series(horas_ocupadas / (n_dias * n_carregadores), index=range(24)).clip(upper=1)


def sugerir_janela(ocupacao: pd.Series, duracao_media_h: float) -> int:
    """Escolhe a hora de início, entre 22h, 23h e 0h, com menor ocupação histórica.

    Ficamos nesse intervalo porque ele já é fora-pico e é viável para o morador:
    ele pode plugar ao chegar e usar o agendamento do próprio HCA G2
    (campo scheduleTime da API, Sprint 01) para a carga começar no horário sugerido.
    Ocupações parecidas (mesma casa decimal) desempatam pelo horário mais cedo.
    """
    candidatas = [22, 23, 0]
    return min(candidatas, key=lambda h: (round(float(ocupacao[h]), 1), candidatas.index(h)))


def economia_potencial(energia_pico_kwh: float, horas_ociosas_pico: float) -> float:
    """Quanto teria custado a menos se a energia e a ociosidade de pico fossem no noturno."""
    t = {x["tipo_horario"]: x for x in config.TARIFAS}
    dif_energia = t["pico"]["valor_kwh"] - t["fora_pico"]["valor_kwh"]
    dif_ocio = t["pico"]["taxa_ocupacao_hora"] - t["fora_pico"]["taxa_ocupacao_hora"]
    return round(energia_pico_kwh * dif_energia + horas_ociosas_pico * dif_ocio, 2)

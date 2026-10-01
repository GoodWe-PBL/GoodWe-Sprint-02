"""
IA — Otimização de horário (Etapa 6 da Sprint 01).

Combina duas coisas:
  1. ocupação histórica dos carregadores por hora do dia (onde há folga);
  2. a tarifa de cada faixa e o perfil de uso da pessoa.
Resultado: uma janela de início sugerida, com a economia estimada em reais se as
cargas feitas no pico tivessem sido feitas nessa janela.
"""
from datetime import timedelta

import numpy as np
import pandas as pd

from src.rateio.calculo import tarifas_por_faixa


def ocupacao_por_hora(sessoes, n_carregadores):
    """Fração média de carregadores ocupados em cada hora do dia (0 a 23)."""
    if sessoes.empty:
        return pd.Series(0.0, index=range(24))

    horas_ocupadas = np.zeros(24)  # quantas vezes cada hora do dia teve um carregador em uso
    dias_com_uso = set()
    for inicio, fim in zip(sessoes["inicio"], sessoes["fim"]):
        # percorre a sessão de hora em hora, contando 1 para cada hora em que ela esteve ativa
        instante = inicio.replace(minute=0, second=0)
        while instante < fim:
            horas_ocupadas[instante.hour] += 1
            dias_com_uso.add(instante.date())
            instante += timedelta(hours=1)

    n_dias = max(len(dias_com_uso), 1)
    ocupacao = pd.Series(horas_ocupadas / (n_dias * n_carregadores), index=range(24))
    return ocupacao.clip(upper=1)  # nunca passa de 100%


def sugerir_janela(ocupacao, duracao_media_h):
    """Escolhe a hora de início, entre 22h, 23h e 0h, com menor ocupação histórica.

    Ficamos nesse intervalo porque ele já é fora-pico e é viável para o morador:
    ele pode plugar ao chegar e usar o agendamento do próprio HCA G2
    (campo scheduleTime da API, Sprint 01) para a carga começar no horário sugerido.
    Ocupações parecidas (mesma casa decimal) desempatam pelo horário mais cedo.
    """
    melhor_hora = None
    menor_ocupacao = None
    for hora in [22, 23, 0]:
        ocupacao_da_hora = round(float(ocupacao[hora]), 1)
        # só troca se for estritamente menor: no empate fica a hora que veio antes
        if menor_ocupacao is None or ocupacao_da_hora < menor_ocupacao:
            melhor_hora, menor_ocupacao = hora, ocupacao_da_hora
    return melhor_hora


def economia_potencial(energia_pico_kwh, horas_ociosas_pico):
    """Quanto teria custado a menos se a energia e a ociosidade de pico fossem no noturno."""
    tarifa = tarifas_por_faixa()
    diferenca_por_kwh = tarifa["pico"]["valor_kwh"] - tarifa["fora_pico"]["valor_kwh"]
    diferenca_por_hora_ociosa = (tarifa["pico"]["taxa_ocupacao_hora"]
                                 - tarifa["fora_pico"]["taxa_ocupacao_hora"])
    return round(energia_pico_kwh * diferenca_por_kwh + horas_ociosas_pico * diferenca_por_hora_ociosa, 2)

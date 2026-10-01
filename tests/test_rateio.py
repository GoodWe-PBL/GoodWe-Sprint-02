"""Testes das regras de rateio definidas na Sprint 01."""
from datetime import datetime, time, timedelta

import pytest

from src import config
from src.rateio.calculo import (comparar_modalidades, fechar_fatura, itens_da_sessao,
                                liquidar_avulso, valor_sessao)
from src.rateio.tarifas import (dividir_energia_por_faixa, faixa_horaria, minutos_ociosos,
                                ociosidade_cobravel_por_faixa)


def leituras_constantes(inicio, minutos_carga, potencia, minutos_ociosos_=0, passo=5):
    """Carga a potência constante seguida de tempo plugado sem carregar."""
    leituras, energia, t = [], 0.0, inicio
    fim_carga = inicio + timedelta(minutes=minutos_carga)
    fim = fim_carga + timedelta(minutes=minutos_ociosos_)
    while True:
        leituras.append({"timestamp": t, "potencia_kw": potencia if t < fim_carga else 0.0,
                         "energia_kwh": energia})
        if t >= fim:
            return leituras
        prox = min(t + timedelta(minutes=passo), fim)
        if t < fim_carga:
            energia += potencia * (min(prox, fim_carga) - t).total_seconds() / 3600
        t = prox


@pytest.mark.parametrize("hora,esperado", [
    (time(17, 0), "pico"), (time(21, 59), "pico"), (time(22, 0), "fora_pico"),
    (time(3, 0), "fora_pico"), (time(6, 59), "fora_pico"), (time(7, 0), "intermediario"),
    (time(16, 59), "intermediario"),
])
def test_faixa_horaria(hora, esperado):
    assert faixa_horaria(hora)["tipo_horario"] == esperado


def test_sessao_que_cruza_faixas_e_dividida():
    # 20h às 24h a 3 kW: 2 h no pico (6 kWh) e 2 h no noturno (6 kWh)
    l = leituras_constantes(datetime(2026, 9, 1, 20, 0), 240, 3.0)
    faixas = dividir_energia_por_faixa(l)
    assert faixas["pico"] == pytest.approx(6.0, abs=0.01)
    assert faixas["fora_pico"] == pytest.approx(6.0, abs=0.01)


def test_ociosidade_respeita_tolerancia_e_faixa():
    # carga termina às 18h, carro fica plugado até 20h (no pico)
    l = leituras_constantes(datetime(2026, 9, 1, 16, 0), 120, 3.0, minutos_ociosos_=120)
    assert minutos_ociosos(l) == 120
    horas = ociosidade_cobravel_por_faixa(l, tolerancia_min=30)
    assert horas["pico"] == pytest.approx(1.5, abs=0.02)


def test_modalidade_mensal_formula():
    # F = Σ(E×T) + C + P
    itens = itens_da_sessao({"pico": 10.0, "fora_pico": 20.0}, {"pico": 1.0}, "mensal")
    energia = 10 * 0.95 + 20 * 0.55
    assert valor_sessao(itens) == pytest.approx(energia + 1.0 * 2.00, abs=0.01)
    fatura = fechar_fatura("mensal", itens)
    assert fatura["valor_final"] == pytest.approx(energia + 2.00 + config.C_FIXO_MENSAL, abs=0.01)


def test_modalidade_avulsa_formula_e_estorno():
    # V = E × (T + M) + P
    itens = itens_da_sessao({"intermediario": 10.0}, {}, "avulso")
    v = 10 * (0.75 + config.M_MARGEM_AVULSA)
    assert valor_sessao(itens) == pytest.approx(v, abs=0.01)
    assert liquidar_avulso(50.0, v)["estorno"] == pytest.approx(50 - v, abs=0.01)
    assert fechar_fatura("avulso", itens, 1, [v])["valor_fixo"] == 0


def test_ociosidade_noturna_nao_e_cobrada():
    itens = itens_da_sessao({"fora_pico": 5.0}, {"fora_pico": 6.0}, "mensal")
    assert all(i["tipo_item"] == "energia" for i in itens)


def test_ociosidade_desligada_pelo_condominio():
    itens = itens_da_sessao({"pico": 5.0}, {"pico": 2.0}, "mensal", ociosidade_ativa=False)
    assert all(i["tipo_item"] == "energia" for i in itens)


def test_mes_sem_consumo():
    assert fechar_fatura("mensal", [])["valor_final"] == config.C_FIXO_MENSAL
    assert fechar_fatura("avulso", [])["valor_final"] == 0


def test_comparar_modalidades_ponto_de_equilibrio():
    # mensal compensa a partir de C / M kWh no mês
    equilibrio = config.C_FIXO_MENSAL / config.M_MARGEM_AVULSA
    abaixo = comparar_modalidades({"intermediario": equilibrio - 10})
    acima = comparar_modalidades({"intermediario": equilibrio + 10})
    assert abaixo["avulso"] < abaixo["mensal"]
    assert acima["mensal"] < acima["avulso"]

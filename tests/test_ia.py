"""Testes das regras de anomalia e do comportamento estrutural da IA."""
from datetime import datetime, timedelta
from types import SimpleNamespace

from src.ia.anomalias import aplicar_regras, houve_queda_brusca
from tests.test_rateio import leituras_constantes


def sessao(energia, minutos):
    return SimpleNamespace(energia_kwh=energia, duracao_minutos=minutos)


def test_sessao_fantasma_e_descartada():
    decisao, _ = aplicar_regras(sessao(0.0, 22), 38.0, [])
    assert decisao == "descartada"


def test_sessao_longa_vai_para_revisao():
    decisao, motivos = aplicar_regras(sessao(10.0, 13 * 60), 38.0, [])
    assert decisao == "em_revisao" and "longa" in motivos[0]


def test_energia_maior_que_bateria():
    decisao, _ = aplicar_regras(sessao(60.0, 300), 44.9, [])
    assert decisao == "em_revisao"


def test_divergencia_medidor_telemetria():
    l = leituras_constantes(datetime(2026, 9, 1, 22), 240, 5.0)  # telemetria soma 20 kWh
    decisao, motivos = aplicar_regras(sessao(30.0, 240), 48.0, l)
    assert decisao == "em_revisao" and any("telemetria" in m for m in motivos)


def test_sessao_normal_passa_pelas_regras():
    l = leituras_constantes(datetime(2026, 9, 1, 22), 240, 5.0)
    assert aplicar_regras(sessao(20.0, 240), 48.0, l)[0] is None


def test_queda_brusca_de_potencia():
    l = leituras_constantes(datetime(2026, 9, 1, 22), 240, 5.0)
    for x in l[10:18]:
        x["potencia_kw"] = 0.1
    assert houve_queda_brusca(l)

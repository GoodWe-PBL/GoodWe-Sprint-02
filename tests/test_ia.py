"""Testes das regras de anomalia e do comportamento estrutural da IA."""
from datetime import datetime
from types import SimpleNamespace

from src.ia.anomalias import aplicar_regras, houve_queda_brusca
from tests.test_rateio import leituras_constantes


def sessao(energia, minutos):
    """Sessão de mentira, só com os dois campos que as regras leem."""
    return SimpleNamespace(energia_kwh=energia, duracao_minutos=minutos)


def carga_de_20_kwh():
    """Leituras de uma carga de 4 h a 5 kW (a telemetria soma 20 kWh)."""
    return leituras_constantes(datetime(2026, 9, 1, 22), 240, 5.0)


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
    decisao, motivos = aplicar_regras(sessao(30.0, 240), 48.0, carga_de_20_kwh())
    assert decisao == "em_revisao" and any("telemetria" in motivo for motivo in motivos)


def test_sessao_normal_passa_pelas_regras():
    decisao, _ = aplicar_regras(sessao(20.0, 240), 48.0, carga_de_20_kwh())
    assert decisao is None


def test_queda_brusca_de_potencia():
    leituras = carga_de_20_kwh()
    for leitura in leituras[10:18]:
        leitura["potencia_kw"] = 0.1
    assert houve_queda_brusca(leituras)

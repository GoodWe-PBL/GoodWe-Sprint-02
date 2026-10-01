"""
IA — Detecção de anomalias (Etapa 5 da Sprint 01, logo após a ingestão).

Esta é a parte da IA que controla o rateio: cada sessão registrada passa por aqui
ANTES de ser faturada, e a decisão define o que acontece com ela:

    validada    -> entra na fatura do mês
    em_revisao  -> NÃO é cobrada; fica pendente até o gestor aprovar ou rejeitar
    descartada  -> nunca é cobrada (ex.: sessão "fantasma" sem energia)

São duas camadas:
  1. Regras determinísticas da Sprint 01 (sessão > 12h, energia impossível para a
     bateria, divergência medidor x telemetria, queda brusca de potência).
  2. Modelo estatístico: Isolation Forest treinado no histórico de sessões
     validadas + z-score da energia em relação ao histórico do próprio usuário.
"""
import math

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from src import config
from src.rateio.tarifas import fim_da_carga

# Ficaram de fora do modelo, de propósito, depois dos primeiros testes:
#  - horário de início: quem carrega de dia (minoria) era marcado como anômalo só
#    por ser minoria, sem nada de errado na sessão;
#  - energia em kWh absoluta: veículos de bateria grande (ex.: BYD Seal, 82,5 kWh)
#    eram sempre marcados. Usamos a fração da bateria, que já normaliza isso.
COLUNAS_MODELO = ["duracao_h", "potencia_media_kw", "fracao_bateria", "ociosidade_h"]


# ---------------------------------------------------------------------------
# Camada 1 — regras
# ---------------------------------------------------------------------------
def houve_queda_brusca(leituras: list[dict]) -> bool:
    """Potência despenca (< 30% da mediana da carga) e depois volta (> 70%),
    tudo antes do fim da carga. Indica instabilidade de rede ou do carregador."""
    if len(leituras) < 6:
        return False
    limite = fim_da_carga(leituras)
    carga = [l["potencia_kw"] for l in leituras if l["timestamp"] < limite]
    if len(carga) < 6:
        return False
    mediana = float(np.median(carga))
    caiu = False
    for p in carga:
        if p < 0.3 * mediana:
            caiu = True
        elif caiu and p > 0.7 * mediana:
            return True
    return False


def aplicar_regras(sessao, bateria_kwh: float, leituras: list[dict]) -> tuple[str | None, list[str]]:
    """Devolve (decisao_forcada, motivos). decisao_forcada é None se nenhuma regra disparou."""
    motivos = []
    if sessao.energia_kwh < config.ENERGIA_MINIMA_SESSAO_KWH:
        return "descartada", ["sessão sem entrega de energia (conexão sem carga ou falha de partida)"]

    if sessao.duracao_minutos > config.LIMITE_SESSAO_LONGA_H * 60:
        motivos.append(f"sessão longa: {sessao.duracao_minutos / 60:.1f} h "
                       f"(limite {config.LIMITE_SESSAO_LONGA_H} h)")
    if sessao.energia_kwh > bateria_kwh * config.FATOR_MAX_BATERIA:
        motivos.append(f"energia ({sessao.energia_kwh:.1f} kWh) maior que a bateria do veículo "
                       f"({bateria_kwh:.1f} kWh)")
    if leituras:
        energia_tel = leituras[-1]["energia_kwh"]
        if abs(energia_tel - sessao.energia_kwh) > max(0.5, 0.10 * sessao.energia_kwh):
            motivos.append(f"medidor informou {sessao.energia_kwh:.1f} kWh, telemetria somou "
                           f"{energia_tel:.1f} kWh")
        if houve_queda_brusca(leituras):
            motivos.append("queda brusca de potência durante a carga")
    return ("em_revisao" if motivos else None), motivos


# ---------------------------------------------------------------------------
# Camada 2 — modelo
# ---------------------------------------------------------------------------
def montar_features(df: pd.DataFrame) -> pd.DataFrame:
    """df precisa ter: inicio, duracao_minutos, energia_kwh, potencia_media_kw,
    bateria_kwh, ociosidade_min."""
    hora = df["inicio"].dt.hour + df["inicio"].dt.minute / 60
    return pd.DataFrame({
        "duracao_h": df["duracao_minutos"] / 60,
        "energia_kwh": df["energia_kwh"],
        "potencia_media_kw": df["potencia_media_kw"],
        "hora_sin": np.sin(2 * math.pi * hora / 24),   # hora como círculo: 23h fica perto de 0h
        "hora_cos": np.cos(2 * math.pi * hora / 24),
        "fracao_bateria": df["energia_kwh"] / df["bateria_kwh"],
        "ociosidade_h": df["ociosidade_min"] / 60,
    }, index=df.index)


class DetectorAnomalias:
    def __init__(self):
        self.escalador = StandardScaler()
        self.modelo = IsolationForest(n_estimators=200,
                                      contamination=config.CONTAMINACAO_ISOLATION_FOREST,
                                      random_state=config.SEMENTE)
        self.treinado = False
        self.n_treino = 0

    def treinar(self, historico: pd.DataFrame):
        if len(historico) < 10:
            return self
        X = self.escalador.fit_transform(montar_features(historico)[COLUNAS_MODELO])
        self.modelo.fit(X)
        self.treinado = True
        self.n_treino = len(historico)
        return self

    def pontuar(self, novas: pd.DataFrame) -> pd.DataFrame:
        """score: quanto menor, mais anômala. anomala=True quando o modelo isola a sessão."""
        if not self.treinado or novas.empty:
            return pd.DataFrame({"score": np.nan, "anomala": False}, index=novas.index)
        X = self.escalador.transform(montar_features(novas)[COLUNAS_MODELO])
        return pd.DataFrame({"score": self.modelo.decision_function(X),
                             "anomala": self.modelo.predict(X) == -1}, index=novas.index)


def zscore_veiculo(energia: float, historico_veiculo: pd.Series) -> float | None:
    """Desvio da energia da sessão em relação às sessões anteriores do MESMO veículo
    ("consumo fora do padrão do veículo", Sprint 01). Comparar por veículo, e não
    por usuário, evita marcar quem tem dois carros com baterias diferentes."""
    if len(historico_veiculo) < 8 or historico_veiculo.std() == 0:
        return None
    return (energia - historico_veiculo.mean()) / historico_veiculo.std()


def explicar(linha_features: pd.Series, referencia: pd.DataFrame) -> str:
    """Aponta a característica que mais se afasta da média do histórico,
    para o gestor entender por que o modelo segurou a sessão."""
    nomes = {"duracao_h": "duração", "energia_kwh": "energia", "potencia_media_kw": "potência média",
             "fracao_bateria": "fração da bateria", "ociosidade_h": "tempo ocioso",
             "hora_sin": "horário", "hora_cos": "horário"}
    linha_features, referencia = linha_features[COLUNAS_MODELO], referencia[COLUNAS_MODELO]
    z = ((linha_features - referencia.mean()) / referencia.std().replace(0, 1)).abs()
    col = z.idxmax()
    return f"valor atípico de {nomes[col]} (z={z[col]:.1f})"

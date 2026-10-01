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
     validadas + z-score da energia em relação ao histórico do próprio veículo.
"""
import math

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from src import config
from src.rateio.tarifas import fim_da_carga

# Características da sessão que o modelo enxerga.
# Ficaram de fora, de propósito, depois dos primeiros testes:
#  - horário de início: quem carrega de dia (minoria) era marcado como anômalo só
#    por ser minoria, sem nada de errado na sessão;
#  - energia em kWh absoluta: veículos de bateria grande (ex.: BYD Seal, 82,5 kWh)
#    eram sempre marcados. Usamos a fração da bateria, que já normaliza isso.
COLUNAS_MODELO = ["duracao_h", "potencia_media_kw", "fracao_bateria", "ociosidade_h"]

# Nome de cada característica em português, para o motivo mostrado ao gestor.
NOMES_DAS_COLUNAS = {"duracao_h": "duração", "potencia_media_kw": "potência média",
                     "fracao_bateria": "fração da bateria", "ociosidade_h": "tempo ocioso"}


# ---------------------------------------------------------------------------
# Camada 1 — regras
# ---------------------------------------------------------------------------
def houve_queda_brusca(leituras):
    """Potência despenca (< 30% da mediana da carga) e depois volta (> 70%),
    tudo antes do fim da carga. Indica instabilidade de rede ou do carregador."""
    if len(leituras) < 6:
        return False
    instante_fim_da_carga = fim_da_carga(leituras)
    potencias_da_carga = []
    for leitura in leituras:
        if leitura["timestamp"] < instante_fim_da_carga:
            potencias_da_carga.append(leitura["potencia_kw"])
    if len(potencias_da_carga) < 6:
        return False

    mediana = float(np.median(potencias_da_carga))
    ja_caiu = False
    for potencia in potencias_da_carga:
        if potencia < 0.3 * mediana:
            ja_caiu = True
        elif ja_caiu and potencia > 0.7 * mediana:
            return True
    return False


def aplicar_regras(sessao, bateria_kwh, leituras):
    """Devolve (decisao, motivos). decisao é "descartada", "em_revisao" ou
    None quando nenhuma regra disparou (aí quem decide é o modelo)."""
    if sessao.energia_kwh < config.ENERGIA_MINIMA_SESSAO_KWH:
        return "descartada", ["sessão sem entrega de energia (conexão sem carga ou falha de partida)"]

    motivos = []
    if sessao.duracao_minutos > config.LIMITE_SESSAO_LONGA_H * 60:
        motivos.append(f"sessão longa: {sessao.duracao_minutos / 60:.1f} h "
                       f"(limite {config.LIMITE_SESSAO_LONGA_H} h)")
    if sessao.energia_kwh > bateria_kwh * config.FATOR_MAX_BATERIA:
        motivos.append(f"energia ({sessao.energia_kwh:.1f} kWh) maior que a bateria do veículo "
                       f"({bateria_kwh:.1f} kWh)")
    if leituras:
        energia_da_telemetria = leituras[-1]["energia_kwh"]
        # diferença aceita entre medidor e telemetria: 10% da energia, no mínimo 0,5 kWh
        diferenca_aceita = max(0.5, 0.10 * sessao.energia_kwh)
        if abs(energia_da_telemetria - sessao.energia_kwh) > diferenca_aceita:
            motivos.append(f"medidor informou {sessao.energia_kwh:.1f} kWh, telemetria somou "
                           f"{energia_da_telemetria:.1f} kWh")
        if houve_queda_brusca(leituras):
            motivos.append("queda brusca de potência durante a carga")

    if motivos:
        return "em_revisao", motivos
    return None, motivos


# ---------------------------------------------------------------------------
# Camada 2 — modelo
# ---------------------------------------------------------------------------
def montar_features(sessoes):
    """Calcula as características (features) de cada sessão.

    sessoes é um DataFrame com as colunas: inicio, duracao_minutos, energia_kwh,
    potencia_media_kw, bateria_kwh, ociosidade_min.
    """
    hora = sessoes["inicio"].dt.hour + sessoes["inicio"].dt.minute / 60
    return pd.DataFrame({
        "duracao_h": sessoes["duracao_minutos"] / 60,
        "energia_kwh": sessoes["energia_kwh"],
        "potencia_media_kw": sessoes["potencia_media_kw"],
        "hora_sin": np.sin(2 * math.pi * hora / 24),   # hora como círculo: 23h fica perto de 0h
        "hora_cos": np.cos(2 * math.pi * hora / 24),
        "fracao_bateria": sessoes["energia_kwh"] / sessoes["bateria_kwh"],
        "ociosidade_h": sessoes["ociosidade_min"] / 60,
    }, index=sessoes.index)


class DetectorAnomalias:
    """Isolation Forest: aprende como é uma sessão comum e aponta as que fogem do padrão."""

    def __init__(self):
        # o escalador põe todas as colunas na mesma escala antes de entrarem no modelo
        self.escalador = StandardScaler()
        self.modelo = IsolationForest(n_estimators=200,
                                      contamination=config.CONTAMINACAO_ISOLATION_FOREST,
                                      random_state=config.SEMENTE)
        self.treinado = False
        self.n_treino = 0

    def treinar(self, historico):
        """Treina com o histórico de sessões. Com menos de 10 sessões não treina."""
        if len(historico) < 10:
            return self
        features = montar_features(historico)[COLUNAS_MODELO]
        self.modelo.fit(self.escalador.fit_transform(features))
        self.treinado = True
        self.n_treino = len(historico)
        return self

    def pontuar(self, novas):
        """Devolve, para cada sessão nova, o score (quanto menor, mais anômala)
        e anomala=True quando o modelo isola a sessão."""
        if not self.treinado or novas.empty:
            return pd.DataFrame({"score": np.nan, "anomala": False}, index=novas.index)
        features = self.escalador.transform(montar_features(novas)[COLUNAS_MODELO])
        return pd.DataFrame({"score": self.modelo.decision_function(features),
                             "anomala": self.modelo.predict(features) == -1}, index=novas.index)


def zscore_veiculo(energia, historico_veiculo):
    """Quantos desvios-padrão a energia da sessão está da média das sessões
    anteriores do MESMO veículo ("consumo fora do padrão do veículo", Sprint 01).
    Comparar por veículo, e não por usuário, evita marcar quem tem dois carros
    com baterias diferentes. Devolve None se o histórico for pequeno demais."""
    if len(historico_veiculo) < 8 or historico_veiculo.std() == 0:
        return None
    return (energia - historico_veiculo.mean()) / historico_veiculo.std()


def explicar(features_da_sessao, features_de_referencia):
    """Aponta a característica que mais se afasta da média do histórico,
    para o gestor entender por que o modelo segurou a sessão."""
    sessao = features_da_sessao[COLUNAS_MODELO]
    referencia = features_de_referencia[COLUNAS_MODELO]
    desvio_padrao = referencia.std().replace(0, 1)  # evita divisão por zero
    distancia = ((sessao - referencia.mean()) / desvio_padrao).abs()
    coluna = distancia.idxmax()  # a característica mais distante da média
    return f"valor atípico de {NOMES_DAS_COLUNAS[coluna]} (z={distancia[coluna]:.1f})"

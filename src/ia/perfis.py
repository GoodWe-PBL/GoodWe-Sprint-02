"""
IA — Clustering de perfis de uso (K-Means), Etapa 5 da Sprint 01.

Agrupa os usuários pelo jeito como usam o carregador. O perfil é usado depois em
três lugares do fluxo:
  - previsão: entra como variável do modelo e serve de base para quem tem pouco histórico;
  - sugestão de horário: só é gerada para perfis que concentram uso no pico;
  - insights: compara o usuário com o próprio grupo.
"""
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

from src import config

COLUNAS = ["sessoes_mes", "kwh_mes", "kwh_sessao", "pct_pico", "hora_media", "ociosidade_media_h"]


def features_por_usuario(sessoes: pd.DataFrame, meses_ativos: dict[int, int]) -> pd.DataFrame:
    """sessoes: validadas, com colunas usuario_id, inicio, energia_kwh,
    energia_pico_kwh, ociosidade_min. meses_ativos: nº de meses de cadastro no período."""
    linhas = []
    for uid, g in sessoes.groupby("usuario_id"):
        meses = max(1, meses_ativos.get(uid, 1))
        hora = g["inicio"].dt.hour + g["inicio"].dt.minute / 60
        # média circular do horário de início (22h e 2h têm média 0h, não 12h)
        ang = 2 * np.pi * hora / 24
        hora_media = (np.degrees(np.arctan2(np.sin(ang).mean(), np.cos(ang).mean())) / 15) % 24
        linhas.append({
            "usuario_id": uid,
            "sessoes_mes": len(g) / meses,
            "kwh_mes": g["energia_kwh"].sum() / meses,
            "kwh_sessao": g["energia_kwh"].mean(),
            "pct_pico": g["energia_pico_kwh"].sum() / max(g["energia_kwh"].sum(), 1e-9),
            "hora_media": hora_media,
            "ociosidade_media_h": g["ociosidade_min"].mean() / 60,
        })
    return pd.DataFrame(linhas).set_index("usuario_id")


def _rotular(centro: pd.Series, mediana_kwh: float) -> str:
    consumo = "Uso intenso" if centro["kwh_mes"] >= mediana_kwh else "Uso leve"
    if centro["pct_pico"] >= 0.4:
        horario = "concentrado no pico"
    elif 7 <= centro["hora_media"] < 17:
        horario = "diurno"
    else:
        horario = "noturno"
    return f"{consumo}, {horario}"


def agrupar(features: pd.DataFrame, k: int = config.N_CLUSTERS_PERFIL):
    """Devolve (DataFrame com cluster e perfil por usuário, centróides em escala original)."""
    k = min(k, len(features))
    escalador = StandardScaler()
    X = escalador.fit_transform(features[COLUNAS])
    modelo = KMeans(n_clusters=k, n_init=20, random_state=config.SEMENTE).fit(X)
    centros = pd.DataFrame(escalador.inverse_transform(modelo.cluster_centers_), columns=COLUNAS)
    mediana = features["kwh_mes"].median()
    rotulos = {i: _rotular(centros.loc[i], mediana) for i in centros.index}
    # se dois clusters ganharem o mesmo rótulo, diferenciamos pelo consumo
    vistos = {}
    for i in sorted(rotulos, key=lambda c: -centros.loc[c, "kwh_mes"]):
        if rotulos[i] in vistos:
            rotulos[i] = rotulos[i] + " (moderado)"
        vistos[rotulos[i]] = i
    resultado = features.copy()
    resultado["cluster"] = modelo.labels_
    resultado["perfil"] = resultado["cluster"].map(rotulos)
    centros["perfil"] = centros.index.map(rotulos)
    return resultado, centros

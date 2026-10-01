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

# Características de cada usuário que o K-Means usa para agrupar.
COLUNAS = ["sessoes_mes", "kwh_mes", "kwh_sessao", "pct_pico", "hora_media", "ociosidade_media_h"]


def hora_media_circular(horas):
    """Média de horários tratando o dia como um círculo.

    A média comum de 22h e 2h daria 12h (meio-dia), o que é errado: o certo é 0h.
    Por isso cada hora vira um ângulo (24h = volta completa), tiramos a média
    dos senos e dos cossenos e convertemos o ângulo médio de volta para horas.
    """
    angulo = 2 * np.pi * horas / 24
    seno_medio = np.sin(angulo).mean()
    cosseno_medio = np.cos(angulo).mean()
    angulo_medio_em_graus = np.degrees(np.arctan2(seno_medio, cosseno_medio))
    return (angulo_medio_em_graus / 15) % 24  # 15 graus = 1 hora


def features_por_usuario(sessoes, meses_ativos):
    """Resume as sessões de cada usuário em uma linha de características.

    sessoes: sessões validadas (DataFrame) com as colunas usuario_id, inicio,
             energia_kwh, energia_pico_kwh e ociosidade_min.
    meses_ativos: {usuario_id: nº de meses de cadastro no período}.
    """
    linhas = []
    for usuario_id, sessoes_do_usuario in sessoes.groupby("usuario_id"):
        meses = max(1, meses_ativos.get(usuario_id, 1))
        hora_de_inicio = (sessoes_do_usuario["inicio"].dt.hour
                          + sessoes_do_usuario["inicio"].dt.minute / 60)
        energia_total = sessoes_do_usuario["energia_kwh"].sum()
        linhas.append({
            "usuario_id": usuario_id,
            "sessoes_mes": len(sessoes_do_usuario) / meses,
            "kwh_mes": energia_total / meses,
            "kwh_sessao": sessoes_do_usuario["energia_kwh"].mean(),
            # max(..., 1e-9) evita divisão por zero
            "pct_pico": sessoes_do_usuario["energia_pico_kwh"].sum() / max(energia_total, 1e-9),
            "hora_media": hora_media_circular(hora_de_inicio),
            "ociosidade_media_h": sessoes_do_usuario["ociosidade_min"].mean() / 60,
        })
    return pd.DataFrame(linhas).set_index("usuario_id")


def nome_do_perfil(centro, mediana_kwh):
    """Dá um nome em português ao grupo, a partir do seu centro (usuário médio do grupo)."""
    if centro["kwh_mes"] >= mediana_kwh:
        consumo = "Uso intenso"
    else:
        consumo = "Uso leve"

    if centro["pct_pico"] >= 0.4:
        horario = "concentrado no pico"
    elif 7 <= centro["hora_media"] < 17:
        horario = "diurno"
    else:
        horario = "noturno"
    return f"{consumo}, {horario}"


def agrupar(features, k=config.N_CLUSTERS_PERFIL):
    """Separa os usuários em k grupos. Devolve (tabela com o grupo e o perfil de
    cada usuário, centros dos grupos nas unidades originais)."""
    k = min(k, len(features))  # não dá para ter mais grupos do que usuários
    # o escalador põe todas as colunas na mesma escala, senão o kWh dominaria a conta
    escalador = StandardScaler()
    features_na_mesma_escala = escalador.fit_transform(features[COLUNAS])
    modelo = KMeans(n_clusters=k, n_init=20, random_state=config.SEMENTE).fit(features_na_mesma_escala)
    centros = pd.DataFrame(escalador.inverse_transform(modelo.cluster_centers_), columns=COLUNAS)

    mediana_kwh = features["kwh_mes"].median()
    nome_do_grupo = {}
    for grupo in centros.index:
        nome_do_grupo[grupo] = nome_do_perfil(centros.loc[grupo], mediana_kwh)

    # Se dois grupos ganharem o mesmo nome, o de menor consumo recebe "(moderado)".
    # Para isso percorremos os grupos do maior consumo para o menor.
    grupos_por_consumo = sorted(nome_do_grupo, key=lambda grupo: centros.loc[grupo, "kwh_mes"],
                                reverse=True)
    nomes_ja_usados = set()
    for grupo in grupos_por_consumo:
        if nome_do_grupo[grupo] in nomes_ja_usados:
            nome_do_grupo[grupo] = nome_do_grupo[grupo] + " (moderado)"
        nomes_ja_usados.add(nome_do_grupo[grupo])

    resultado = features.copy()
    resultado["cluster"] = modelo.labels_
    resultado["perfil"] = resultado["cluster"].map(nome_do_grupo)
    centros["perfil"] = centros.index.map(nome_do_grupo)
    return resultado, centros

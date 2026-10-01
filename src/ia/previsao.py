"""
IA — Previsão de consumo (Etapa 6 da Sprint 01).

Modelo de regressão (Ridge) que prevê o kWh do próximo mês de cada usuário.
Treina com pares (mês m -> mês m+1) de todos os usuários, usando só meses que já
fecharam, então nunca "vê o futuro".

Variáveis: consumo do mês, média histórica do usuário, nº de sessões, % no pico
e o consumo médio do cluster do usuário (é aqui que o perfil entra na previsão:
quem tem pouco histórico herda o comportamento do grupo).

A previsão alimenta: o valor estimado da próxima fatura, o alerta de consumo
acima do normal e a recomendação de modalidade (mensal x avulsa).
"""
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

from src import config

FEATURES = ["kwh_mes", "kwh_media_hist", "n_sessoes", "pct_pico", "kwh_cluster"]


def tabela_mensal(sessoes: pd.DataFrame, usuarios: pd.DataFrame, meses: list[str]) -> pd.DataFrame:
    """Uma linha por (usuário, mês em que ele já estava cadastrado), inclusive meses
    sem nenhuma sessão (kwh = 0), que também são informação para o modelo."""
    agg = (sessoes.groupby(["usuario_id", "mes_competencia"])
           .agg(kwh_mes=("energia_kwh", "sum"), n_sessoes=("energia_kwh", "size"),
                kwh_pico=("energia_pico_kwh", "sum"))
           .reset_index().rename(columns={"mes_competencia": "mes"}))
    base = []
    for _, u in usuarios.iterrows():
        for mes in meses:
            if pd.Period(mes) >= pd.Period(u["criado_em"], "M"):
                base.append({"usuario_id": u["id"], "mes": mes})
    tab = pd.DataFrame(base).merge(agg, on=["usuario_id", "mes"], how="left").fillna(0)
    tab["pct_pico"] = np.where(tab["kwh_mes"] > 0, tab["kwh_pico"] / tab["kwh_mes"].replace(0, 1), 0)
    tab = tab.sort_values(["usuario_id", "mes"])
    tab["kwh_media_hist"] = tab.groupby("usuario_id")["kwh_mes"].transform(
        lambda s: s.expanding().mean())
    return tab


class PrevisorConsumo:
    def __init__(self):
        self.modelo = Ridge(alpha=1.0)
        self.treinado = False
        self.n_treino = 0

    def treinar(self, tab: pd.DataFrame):
        tab = tab.sort_values(["usuario_id", "mes"]).copy()
        tab["alvo"] = tab.groupby("usuario_id")["kwh_mes"].shift(-1)
        treino = tab.dropna(subset=["alvo"])
        self.n_treino = len(treino)
        if len(treino) >= config.MIN_LINHAS_TREINO_PREVISAO:
            self.modelo.fit(treino[FEATURES], treino["alvo"])
            self.treinado = True
        return self

    def prever(self, linhas_mes_atual: pd.DataFrame) -> pd.DataFrame:
        """Recebe as linhas do mês corrente e devolve kwh previsto para o próximo mês."""
        saida = linhas_mes_atual[["usuario_id"]].copy()
        if self.treinado:
            saida["kwh_previsto"] = np.clip(self.modelo.predict(linhas_mes_atual[FEATURES]), 0, None)
            saida["metodo"] = "ridge"
        else:
            # partida a frio (1º mês): média entre o próprio histórico e o do cluster
            saida["kwh_previsto"] = (linhas_mes_atual["kwh_media_hist"] + linhas_mes_atual["kwh_cluster"]) / 2
            saida["metodo"] = "media_cluster"
        saida["kwh_previsto"] = saida["kwh_previsto"].round(2)
        return saida


def proximo_mes(mes: str) -> str:
    return str(pd.Period(mes) + 1)

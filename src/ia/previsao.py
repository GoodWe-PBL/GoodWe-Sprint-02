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

# Variáveis de entrada do modelo (uma linha por usuário e mês).
FEATURES = ["kwh_mes", "kwh_media_hist", "n_sessoes", "pct_pico", "kwh_cluster"]


def media_ate_o_mes(kwh_dos_meses):
    """Para cada mês, a média do consumo do primeiro mês até ele (média acumulada)."""
    return kwh_dos_meses.expanding().mean()


def tabela_mensal(sessoes, usuarios, meses):
    """Uma linha por (usuário, mês em que ele já estava cadastrado), inclusive meses
    sem nenhuma sessão (kwh = 0), que também são informação para o modelo.

    sessoes: DataFrame de sessões validadas; usuarios: DataFrame com id e criado_em;
    meses: lista de meses "AAAA-MM" já processados.
    """
    # consumo de cada usuário em cada mês em que ele teve sessão
    consumo = sessoes.groupby(["usuario_id", "mes_competencia"]).agg(
        kwh_mes=("energia_kwh", "sum"),
        n_sessoes=("energia_kwh", "size"),
        kwh_pico=("energia_pico_kwh", "sum"))
    consumo = consumo.reset_index().rename(columns={"mes_competencia": "mes"})

    # todos os pares (usuário, mês) a partir do mês de cadastro do usuário
    pares = []
    for _, usuario in usuarios.iterrows():
        mes_do_cadastro = pd.Period(usuario["criado_em"], "M")
        for mes in meses:
            if pd.Period(mes) >= mes_do_cadastro:
                pares.append({"usuario_id": usuario["id"], "mes": mes})

    # junta os dois: mês sem sessão fica com zero
    tabela = pd.DataFrame(pares).merge(consumo, on=["usuario_id", "mes"], how="left").fillna(0)
    tabela["pct_pico"] = np.where(tabela["kwh_mes"] > 0,
                                  tabela["kwh_pico"] / tabela["kwh_mes"].replace(0, 1), 0)
    tabela = tabela.sort_values(["usuario_id", "mes"])
    tabela["kwh_media_hist"] = tabela.groupby("usuario_id")["kwh_mes"].transform(media_ate_o_mes)
    return tabela


class PrevisorConsumo:
    """Regressão Ridge: aprende a relação entre o mês atual e o consumo do mês seguinte."""

    def __init__(self):
        self.modelo = Ridge(alpha=1.0)
        self.treinado = False
        self.n_treino = 0

    def treinar(self, tabela):
        tabela = tabela.sort_values(["usuario_id", "mes"]).copy()
        # alvo = consumo do mês seguinte do mesmo usuário (shift(-1) puxa a linha de baixo)
        tabela["alvo"] = tabela.groupby("usuario_id")["kwh_mes"].shift(-1)
        treino = tabela.dropna(subset=["alvo"])  # o último mês não tem "mês seguinte" ainda
        self.n_treino = len(treino)
        if len(treino) >= config.MIN_LINHAS_TREINO_PREVISAO:
            self.modelo.fit(treino[FEATURES], treino["alvo"])
            self.treinado = True
        return self

    def prever(self, linhas_do_mes_atual):
        """Recebe as linhas do mês corrente e devolve o kWh previsto para o próximo mês."""
        previsao = linhas_do_mes_atual[["usuario_id"]].copy()
        if self.treinado:
            kwh = self.modelo.predict(linhas_do_mes_atual[FEATURES])
            previsao["kwh_previsto"] = np.clip(kwh, 0, None)  # consumo previsto nunca é negativo
            previsao["metodo"] = "ridge"
        else:
            # partida a frio (1º mês): média entre o próprio histórico e o do cluster
            previsao["kwh_previsto"] = (linhas_do_mes_atual["kwh_media_hist"]
                                        + linhas_do_mes_atual["kwh_cluster"]) / 2
            previsao["metodo"] = "media_cluster"
        previsao["kwh_previsto"] = previsao["kwh_previsto"].round(2)
        return previsao


def proximo_mes(mes):
    """'2026-09' -> '2026-10'"""
    return str(pd.Period(mes) + 1)

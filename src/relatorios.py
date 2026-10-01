"""
Saídas do protótipo: CSVs das tabelas, gráficos e relatório de execução.
Servem de evidência de funcionamento e de material para o dashboard/vídeo.
"""
from datetime import time

import matplotlib

matplotlib.use("Agg")  # desenha direto em arquivo, sem abrir janela
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.patches import Patch
from sqlalchemy import select

from src import config
from src.db.modelos import Carregador, Usuario
from src.ia import horarios
from src.pipeline import sessoes_df
from src.rateio.tarifas import faixa_horaria


def consultar(db, sql):
    """Roda um SELECT e devolve o resultado como tabela (DataFrame)."""
    return pd.read_sql(sql, db.get_bind())


def exportar_csvs(db, pasta=config.PASTA_SAIDA):
    """Grava um CSV para cada consulta abaixo (nome do arquivo -> SELECT)."""
    consultas = {
        "sessoes": "SELECT s.*, u.nome AS usuario FROM sessao s JOIN usuario u ON u.id = s.usuario_id",
        "faturas": "SELECT f.*, u.nome AS usuario FROM fatura f JOIN usuario u ON u.id = f.usuario_id",
        "itens_fatura": "SELECT * FROM item_fatura",
        "insights_ia": "SELECT i.*, u.nome AS usuario FROM insight_ia i LEFT JOIN usuario u ON u.id = i.usuario_id",
        "previsoes": "SELECT p.*, u.nome AS usuario FROM previsao_consumo p JOIN usuario u ON u.id = p.usuario_id",
        "usuarios": "SELECT * FROM usuario",
        "sessoes_retidas_pela_ia": "SELECT s.id, u.nome AS usuario, s.inicio, s.fim, s.energia_kwh, "
                                   "s.duracao_minutos, s.status, s.score_anomalia, s.motivo_revisao, s.origem "
                                   "FROM sessao s JOIN usuario u ON u.id = s.usuario_id "
                                   "WHERE s.status IN ('em_revisao','descartada','erro')",
    }
    for nome, sql in consultas.items():
        # utf-8-sig: faz o Excel abrir os acentos corretamente
        consultar(db, sql).to_csv(pasta / f"{nome}.csv", index=False, encoding="utf-8-sig")


def avaliar_previsao(db):
    """Compara a previsão com o consumo que de fato aconteceu e com uma linha de
    base ingênua (repetir o mês anterior). Devolve um dicionário com os erros médios."""
    previsoes = consultar(db, "SELECT usuario_id, mes_base, mes_previsto, kwh_previsto, metodo "
                              "FROM previsao_consumo")
    consumo = consultar(db, "SELECT usuario_id, mes_competencia AS mes, SUM(energia_kwh) AS kwh FROM sessao "
                            "WHERE status = 'validada' GROUP BY usuario_id, mes_competencia")
    usuarios = consultar(db, "SELECT id AS usuario_id FROM usuario")
    # só meses que já aconteceram (a previsão do mês seguinte ao último ainda não é conferível)
    meses = sorted(consultar(db, "SELECT DISTINCT mes_competencia m FROM sessao")["m"])

    # consumo real de todo usuário em todo mês (zero quando não houve sessão)
    todos_os_pares = usuarios.merge(pd.DataFrame({"mes": meses}), how="cross")
    consumo = todos_os_pares.merge(consumo, on=["usuario_id", "mes"], how="left").fillna({"kwh": 0})

    # ao lado de cada previsão: o consumo real do mês previsto e o do mês anterior
    consumo_do_mes_previsto = consumo.rename(columns={"mes": "mes_previsto", "kwh": "kwh_real"})
    consumo_do_mes_anterior = consumo.rename(columns={"mes": "mes_base", "kwh": "kwh_mes_anterior"})
    comparacao = previsoes.merge(consumo_do_mes_previsto, on=["usuario_id", "mes_previsto"])
    comparacao = comparacao.merge(consumo_do_mes_anterior, on=["usuario_id", "mes_base"])
    comparacao = comparacao[comparacao["metodo"] == "ridge"]  # só previsões feitas pelo modelo
    if comparacao.empty:
        return {"n": 0}

    # MAE = erro médio absoluto, em kWh
    erro_do_modelo = (comparacao["kwh_previsto"] - comparacao["kwh_real"]).abs().mean()
    erro_ingenuo = (comparacao["kwh_mes_anterior"] - comparacao["kwh_real"]).abs().mean()
    return {"n": len(comparacao), "mae_modelo": round(erro_do_modelo, 1),
            "mae_ingenuo": round(erro_ingenuo, 1), "tabela": comparacao}


def salvar_grafico(pasta, nome_do_arquivo):
    plt.tight_layout()
    plt.savefig(pasta / nome_do_arquivo)
    plt.close()


def grafico_consumo_mensal(db, nomes, pasta):
    """1. Energia faturada por usuário e mês (barras empilhadas)."""
    faturas = consultar(db, "SELECT usuario_id, referencia_mes, total_kwh FROM fatura")
    # uma linha por mês e uma coluna por usuário
    kwh_por_mes = faturas.pivot_table(index="referencia_mes", columns="usuario_id", values="total_kwh",
                                      fill_value=0)
    kwh_por_mes.columns = [nomes[usuario_id] for usuario_id in kwh_por_mes.columns]
    eixo = kwh_por_mes.plot(kind="bar", stacked=True, figsize=(10, 5.5), colormap="tab20")
    eixo.set(title="Energia faturada por usuário (kWh)", xlabel="Mês de competência", ylabel="kWh")
    eixo.legend(fontsize=7, bbox_to_anchor=(1.01, 1), loc="upper left")
    plt.xticks(rotation=0)
    salvar_grafico(pasta, "01_consumo_mensal.png")


def grafico_anomalias(db, estado, pasta):
    """2. Decisões da IA de anomalias: duração x fração da bateria, cor por status."""
    sessoes = sessoes_df(db, estado, status=("validada", "em_revisao", "descartada"))
    sessoes["fracao_bateria"] = sessoes["energia_kwh"] / sessoes["bateria_kwh"]
    sessoes = sessoes.merge(consultar(db, "SELECT id, status FROM sessao"), on="id")

    figura, eixo = plt.subplots(figsize=(9, 5.5))
    cores = {"validada": "#9aa5b1", "em_revisao": "#e8590c", "descartada": "#c92a2a"}
    for status, grupo in sessoes.groupby("status"):
        # as validadas ficam pequenas e apagadas; as retidas, grandes e com contorno
        validada = status == "validada"
        eixo.scatter(grupo["duracao_minutos"] / 60, grupo["fracao_bateria"],
                     s=18 if validada else 60,
                     c=cores[status], label=f"{status} ({len(grupo)})",
                     alpha=0.6 if validada else 0.95,
                     edgecolors="none" if validada else "black")
    eixo.axvline(config.LIMITE_SESSAO_LONGA_H, ls="--", c="black", lw=1)
    eixo.text(config.LIMITE_SESSAO_LONGA_H + 0.2, eixo.get_ylim()[1] * 0.92, "limite 12 h", fontsize=8)
    eixo.set(title="IA de anomalias: o que foi cobrado, retido e descartado",
             xlabel="Duração da sessão (h)", ylabel="Energia / capacidade da bateria")
    eixo.legend()
    salvar_grafico(pasta, "02_anomalias.png")


def grafico_perfis(db, validadas, nomes, pasta):
    """3. Perfis (K-Means): kWh médio por mês x % da energia no pico, cor por perfil."""
    usuarios = {usuario.id: usuario for usuario in db.scalars(select(Usuario))}
    meses = sorted(validadas["mes_competencia"].unique())
    # em quantos meses cada usuário já estava cadastrado
    meses_de_cadastro = {}
    for usuario_id, usuario in usuarios.items():
        mes_do_cadastro = pd.Period(usuario.criado_em, "M")
        meses_de_cadastro[usuario_id] = sum(pd.Period(mes) >= mes_do_cadastro for mes in meses)

    resumo = validadas.groupby("usuario_id").agg(kwh=("energia_kwh", "sum"),
                                                 pico=("energia_pico_kwh", "sum"))
    resumo["kwh_mes"] = resumo["kwh"] / resumo.index.map(meses_de_cadastro)
    resumo["pct_pico"] = resumo["pico"] / resumo["kwh"]
    resumo["perfil"] = [usuarios[usuario_id].perfil for usuario_id in resumo.index]

    figura, eixo = plt.subplots(figsize=(9, 5.5))
    for perfil, grupo in resumo.groupby("perfil"):
        eixo.scatter(grupo["kwh_mes"], grupo["pct_pico"] * 100, s=120, label=perfil)
        for usuario_id, linha in grupo.iterrows():
            # escreve o nome do usuário ao lado do ponto
            eixo.annotate(nomes[usuario_id], (linha["kwh_mes"], linha["pct_pico"] * 100), fontsize=7,
                          xytext=(5, 4), textcoords="offset points")
    eixo.set(title="IA de perfis (K-Means): consumo x uso no horário de pico",
             xlabel="kWh médio por mês", ylabel="% da energia no pico (17h–22h)")
    eixo.legend(fontsize=8)
    salvar_grafico(pasta, "03_perfis.png")


def grafico_ocupacao_por_hora(db, validadas, pasta):
    """4. Ocupação média dos carregadores em cada hora, com a cor da faixa tarifária."""
    n_carregadores = len(db.scalars(select(Carregador)).all())
    ocupacao = horarios.ocupacao_por_hora(validadas, n_carregadores)
    cor_da_faixa = {"pico": "#e03131", "intermediario": "#f59f00", "fora_pico": "#2f9e44"}
    # cor de cada barra: a da faixa em que cai o meio da hora (ex.: 17h30)
    cores_das_barras = [cor_da_faixa[faixa_horaria(time(hora, 30))["tipo_horario"]] for hora in range(24)]

    figura, eixo = plt.subplots(figsize=(10, 4.5))
    eixo.bar(range(24), ocupacao * 100, color=cores_das_barras)
    eixo.set(title="Ocupação média dos carregadores por hora (cor = faixa tarifária)",
             xlabel="Hora do dia", ylabel="% de carregadores ocupados", xticks=range(24))
    eixo.legend(handles=[Patch(color=cor, label=faixa) for faixa, cor in cor_da_faixa.items()], fontsize=8)
    salvar_grafico(pasta, "04_ocupacao_por_hora.png")


def grafico_previsao(db, pasta):
    """5. Previsão x consumo real (quanto mais perto da diagonal, melhor a previsão)."""
    avaliacao = avaliar_previsao(db)
    if not avaliacao.get("n"):
        return  # ainda não há previsão conferível
    tabela = avaliacao["tabela"]
    figura, eixo = plt.subplots(figsize=(6.5, 6))
    eixo.scatter(tabela["kwh_real"], tabela["kwh_previsto"], s=40)
    limite = max(tabela["kwh_real"].max(), tabela["kwh_previsto"].max()) * 1.05
    eixo.plot([0, limite], [0, limite], ls="--", c="gray")  # diagonal: previsão perfeita
    eixo.set(title=f"Previsão x consumo real (MAE {avaliacao['mae_modelo']} kWh)",
             xlabel="kWh real no mês", ylabel="kWh previsto")
    salvar_grafico(pasta, "05_previsao.png")


def gerar_graficos(db, estado, pasta=config.PASTA_SAIDA):
    """Gera os cinco gráficos PNG em outputs/."""
    plt.rcParams.update({"figure.dpi": 120, "axes.grid": True, "grid.alpha": 0.3})
    # nome curto de cada usuário (sem o que vem entre parênteses)
    nomes = {usuario.id: usuario.nome.split(" (")[0] for usuario in db.scalars(select(Usuario))}

    grafico_consumo_mensal(db, nomes, pasta)
    grafico_anomalias(db, estado, pasta)
    validadas = sessoes_df(db, estado)
    grafico_perfis(db, validadas, nomes, pasta)
    grafico_ocupacao_por_hora(db, validadas, pasta)
    grafico_previsao(db, pasta)


def resumo_execucao(db, estado):
    """Monta o texto do relatorio_execucao.txt."""
    linhas = ["EV ChargeOps — relatório de execução", "=" * 60]

    por_origem = consultar(db, "SELECT origem, status, COUNT(*) n, ROUND(SUM(energia_kwh), 2) kwh FROM sessao "
                               "GROUP BY origem, status ORDER BY origem, status")
    reais = por_origem[por_origem["origem"] == "real"]
    linhas.append(f"Dados reais (Charging Record): {int(reais['n'].sum())} sessões, "
                  f"{reais['kwh'].sum():.2f} kWh (relatório GoodWe: 769,27 kWh)")
    linhas.append("\nSessões por origem e decisão:")
    linhas.append(por_origem.to_string(index=False))
    linhas.extend(["", "Log do pipeline:"] + estado.log)

    ultimo_mes = consultar(db, "SELECT MAX(referencia_mes) m FROM fatura")["m"][0]
    faturas = consultar(db, f"SELECT u.nome usuario, f.modalidade, ROUND(f.total_kwh,1) kwh, f.valor_energia energia, "
                            f"f.valor_ociosidade ociosidade, f.valor_fixo fixo, f.valor_final total, f.estorno, "
                            f"f.sessoes_em_revisao em_revisao FROM fatura f JOIN usuario u ON u.id=f.usuario_id "
                            f"WHERE referencia_mes = '{ultimo_mes}'")
    linhas.extend(["", f"Faturas de {ultimo_mes}:", faturas.to_string(index=False)])

    pendentes = consultar(db, "SELECT s.id, u.nome usuario, s.mes_competencia mes, ROUND(s.energia_kwh,1) kwh, "
                              "s.motivo_revisao motivo FROM sessao s JOIN usuario u ON u.id=s.usuario_id "
                              "WHERE s.status='em_revisao'")
    linhas.extend(["", "Sessões retidas pela IA aguardando o gestor:", pendentes.to_string(index=False)])

    avaliacao = avaliar_previsao(db)
    if avaliacao.get("n"):
        linhas.extend(["", f"Avaliação da previsão ({avaliacao['n']} previsões já conferíveis): "
                           f"erro médio absoluto {avaliacao['mae_modelo']} kWh/mês "
                           f"(repetir o mês anterior erraria {avaliacao['mae_ingenuo']} kWh/mês)"])
    return "\n".join(linhas)

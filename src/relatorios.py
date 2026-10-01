"""
Saídas do protótipo: CSVs das tabelas, gráficos e relatório de execução.
Servem de evidência de funcionamento e de material para o dashboard/vídeo.
"""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from sqlalchemy import select

from src import config
from src.db.modelos import Carregador, Fatura, Usuario
from src.ia import horarios


def _df(db, sql: str) -> pd.DataFrame:
    return pd.read_sql(sql, db.get_bind())


def exportar_csvs(db, pasta=config.PASTA_SAIDA):
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
        _df(db, sql).to_csv(pasta / f"{nome}.csv", index=False, encoding="utf-8-sig")


def avaliar_previsao(db) -> dict:
    """Compara a previsão com o consumo que de fato aconteceu e com uma linha de
    base ingênua (repetir o mês anterior)."""
    prev = _df(db, "SELECT usuario_id, mes_base, mes_previsto, kwh_previsto, metodo FROM previsao_consumo")
    real = _df(db, "SELECT usuario_id, mes_competencia AS mes, SUM(energia_kwh) AS kwh FROM sessao "
                   "WHERE status = 'validada' GROUP BY usuario_id, mes_competencia")
    usuarios = _df(db, "SELECT id AS usuario_id FROM usuario")
    # só meses que já aconteceram (a previsão do mês seguinte ao último ainda não é conferível)
    meses = sorted(_df(db, "SELECT DISTINCT mes_competencia m FROM sessao")["m"])
    grade = usuarios.merge(pd.DataFrame({"mes": meses}), how="cross")
    real = grade.merge(real, on=["usuario_id", "mes"], how="left").fillna({"kwh": 0})
    m = prev.merge(real.rename(columns={"mes": "mes_previsto", "kwh": "kwh_real"}),
                   on=["usuario_id", "mes_previsto"]) \
            .merge(real.rename(columns={"mes": "mes_base", "kwh": "kwh_mes_anterior"}),
                   on=["usuario_id", "mes_base"])
    m = m[m["metodo"] == "ridge"]
    if m.empty:
        return {"n": 0}
    return {"n": len(m),
            "mae_modelo": round((m["kwh_previsto"] - m["kwh_real"]).abs().mean(), 1),
            "mae_ingenuo": round((m["kwh_mes_anterior"] - m["kwh_real"]).abs().mean(), 1),
            "tabela": m}


def gerar_graficos(db, estado, pasta=config.PASTA_SAIDA):
    from src.pipeline import sessoes_df

    plt.rcParams.update({"figure.dpi": 120, "axes.grid": True, "grid.alpha": 0.3})
    nomes = {u.id: u.nome.split(" (")[0] for u in db.scalars(select(Usuario))}

    # 1. consumo faturado por usuário e mês
    fat = _df(db, "SELECT usuario_id, referencia_mes, total_kwh FROM fatura")
    piv = fat.pivot_table(index="referencia_mes", columns="usuario_id", values="total_kwh", fill_value=0)
    piv.columns = [nomes[c] for c in piv.columns]
    ax = piv.plot(kind="bar", stacked=True, figsize=(10, 5.5), colormap="tab20")
    ax.set(title="Energia faturada por usuário (kWh)", xlabel="Mês de competência", ylabel="kWh")
    ax.legend(fontsize=7, bbox_to_anchor=(1.01, 1), loc="upper left")
    plt.xticks(rotation=0)
    plt.tight_layout(); plt.savefig(pasta / "01_consumo_mensal.png"); plt.close()

    # 2. decisões da IA de anomalias
    todas = sessoes_df(db, estado, status=("validada", "em_revisao", "descartada"))
    todas["fracao_bateria"] = todas["energia_kwh"] / todas["bateria_kwh"]
    status_db = _df(db, "SELECT id, status FROM sessao")
    todas = todas.drop(columns=[], errors="ignore").merge(status_db, on="id")
    fig, ax = plt.subplots(figsize=(9, 5.5))
    cores = {"validada": "#9aa5b1", "em_revisao": "#e8590c", "descartada": "#c92a2a"}
    for st, g in todas.groupby("status"):
        ax.scatter(g["duracao_minutos"] / 60, g["fracao_bateria"], s=18 if st == "validada" else 60,
                   c=cores[st], label=f"{st} ({len(g)})", alpha=0.6 if st == "validada" else 0.95,
                   edgecolors="black" if st != "validada" else "none")
    ax.axvline(config.LIMITE_SESSAO_LONGA_H, ls="--", c="black", lw=1)
    ax.text(config.LIMITE_SESSAO_LONGA_H + 0.2, ax.get_ylim()[1] * 0.92, "limite 12 h", fontsize=8)
    ax.set(title="IA de anomalias: o que foi cobrado, retido e descartado",
           xlabel="Duração da sessão (h)", ylabel="Energia / capacidade da bateria")
    ax.legend()
    plt.tight_layout(); plt.savefig(pasta / "02_anomalias.png"); plt.close()

    # 3. perfis (clustering) no último mês
    usuarios = {u.id: u for u in db.scalars(select(Usuario))}
    val = sessoes_df(db, estado)
    meses = sorted(val["mes_competencia"].unique())
    ativos = {uid: sum(pd.Period(m) >= pd.Period(u.criado_em, "M") for m in meses)
              for uid, u in usuarios.items()}
    resumo = val.groupby("usuario_id").agg(kwh=("energia_kwh", "sum"), pico=("energia_pico_kwh", "sum"))
    resumo["kwh_mes"] = resumo["kwh"] / resumo.index.map(ativos)
    resumo["pct_pico"] = resumo["pico"] / resumo["kwh"]
    resumo["perfil"] = [usuarios[i].perfil for i in resumo.index]
    fig, ax = plt.subplots(figsize=(9, 5.5))
    for perfil, g in resumo.groupby("perfil"):
        ax.scatter(g["kwh_mes"], g["pct_pico"] * 100, s=120, label=perfil)
        for uid, r in g.iterrows():
            ax.annotate(nomes[uid], (r["kwh_mes"], r["pct_pico"] * 100), fontsize=7,
                        xytext=(5, 4), textcoords="offset points")
    ax.set(title="IA de perfis (K-Means): consumo x uso no horário de pico",
           xlabel="kWh médio por mês", ylabel="% da energia no pico (17h–22h)")
    ax.legend(fontsize=8)
    plt.tight_layout(); plt.savefig(pasta / "03_perfis.png"); plt.close()

    # 4. ocupação por hora com as faixas tarifárias
    n_carr = len(db.scalars(select(Carregador)).all())
    ocup = horarios.ocupacao_por_hora(val, n_carr)
    fig, ax = plt.subplots(figsize=(10, 4.5))
    cor_faixa = {"pico": "#e03131", "intermediario": "#f59f00", "fora_pico": "#2f9e44"}
    from src.rateio.tarifas import faixa_horaria
    from datetime import time
    cores_h = [cor_faixa[faixa_horaria(time(h, 30))["tipo_horario"]] for h in range(24)]
    ax.bar(range(24), ocup * 100, color=cores_h)
    ax.set(title="Ocupação média dos carregadores por hora (cor = faixa tarifária)",
           xlabel="Hora do dia", ylabel="% de carregadores ocupados", xticks=range(24))
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=c, label=f) for f, c in cor_faixa.items()], fontsize=8)
    plt.tight_layout(); plt.savefig(pasta / "04_ocupacao_por_hora.png"); plt.close()

    # 5. previsão x realizado
    av = avaliar_previsao(db)
    if av.get("n"):
        t = av["tabela"]
        fig, ax = plt.subplots(figsize=(6.5, 6))
        ax.scatter(t["kwh_real"], t["kwh_previsto"], s=40)
        lim = max(t["kwh_real"].max(), t["kwh_previsto"].max()) * 1.05
        ax.plot([0, lim], [0, lim], ls="--", c="gray")
        ax.set(title=f"Previsão x consumo real (MAE {av['mae_modelo']} kWh)",
               xlabel="kWh real no mês", ylabel="kWh previsto")
        plt.tight_layout(); plt.savefig(pasta / "05_previsao.png"); plt.close()


def resumo_execucao(db, estado) -> str:
    linhas = ["EV ChargeOps — relatório de execução", "=" * 60]
    s = _df(db, "SELECT origem, status, COUNT(*) n, ROUND(SUM(energia_kwh), 2) kwh FROM sessao "
                "GROUP BY origem, status ORDER BY origem, status")
    real_total = s[s["origem"] == "real"]["kwh"].sum()
    linhas.append(f"Dados reais (Charging Record): {int(s[s['origem'] == 'real']['n'].sum())} sessões, "
                  f"{real_total:.2f} kWh (relatório GoodWe: 769,27 kWh)")
    linhas.append("\nSessões por origem e decisão:")
    linhas.append(s.to_string(index=False))
    linhas.extend(["", "Log do pipeline:"] + estado.log)

    ult = _df(db, "SELECT MAX(referencia_mes) m FROM fatura")["m"][0]
    f = _df(db, f"SELECT u.nome usuario, f.modalidade, ROUND(f.total_kwh,1) kwh, f.valor_energia energia, "
                f"f.valor_ociosidade ociosidade, f.valor_fixo fixo, f.valor_final total, f.estorno, "
                f"f.sessoes_em_revisao em_revisao FROM fatura f JOIN usuario u ON u.id=f.usuario_id "
                f"WHERE referencia_mes = '{ult}'")
    linhas.extend(["", f"Faturas de {ult}:", f.to_string(index=False)])

    pend = _df(db, "SELECT s.id, u.nome usuario, s.mes_competencia mes, ROUND(s.energia_kwh,1) kwh, "
                   "s.motivo_revisao motivo FROM sessao s JOIN usuario u ON u.id=s.usuario_id "
                   "WHERE s.status='em_revisao'")
    linhas.extend(["", "Sessões retidas pela IA aguardando o gestor:", pend.to_string(index=False)])

    av = avaliar_previsao(db)
    if av.get("n"):
        linhas.extend(["", f"Avaliação da previsão ({av['n']} previsões já conferíveis): "
                           f"erro médio absoluto {av['mae_modelo']} kWh/mês "
                           f"(repetir o mês anterior erraria {av['mae_ingenuo']} kWh/mês)"])
    return "\n".join(linhas)

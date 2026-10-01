# Tela 1 - Visão geral (gestor). Ponto de entrada: streamlit run app/Home.py
# Mostra o resumo do mês escolhido: métricas, insights do gestor, faturas e o
# consumo de cada usuário. Os dados vêm das tabelas fatura, item_fatura e insight_ia.
import streamlit as st

import apoio

apoio.iniciar_tela("Visão geral do gestor")

meses = apoio.consultar("SELECT DISTINCT referencia_mes AS mes FROM fatura ORDER BY mes DESC")
mes = st.selectbox("Mês", meses["mes"])

faturas = apoio.consultar("""
    SELECT u.nome AS usuario, f.modalidade, f.total_kwh AS kwh, f.valor_energia AS energia,
           f.valor_ociosidade AS ociosidade, f.valor_fixo AS fixo, f.valor_final AS total,
           f.sessoes_em_revisao AS em_revisao, f.status
    FROM fatura f JOIN usuario u ON u.id = f.usuario_id
    WHERE f.referencia_mes = :mes ORDER BY u.id""", mes=mes)

# Uma sessão pode ter vários itens (um por faixa horária), por isso o DISTINCT.
sessoes_faturadas = apoio.consultar("""
    SELECT COUNT(DISTINCT i.sessao_id) AS total
    FROM item_fatura i JOIN fatura f ON f.id = i.fatura_id
    WHERE f.referencia_mes = :mes""", mes=mes)["total"][0]

colunas = st.columns(4)
colunas[0].metric("Sessões faturadas", sessoes_faturadas)
colunas[1].metric("Energia faturada", f"{faturas['kwh'].sum():.1f} kWh")
colunas[2].metric("Receita", apoio.reais(faturas["total"].sum()))
colunas[3].metric("Sessões retidas pela IA", faturas["em_revisao"].sum())

st.subheader("Insights do gestor")
# Insight sem usuário (usuario_id nulo) é o que a IA escreveu para o gestor.
insights = apoio.consultar("""
    SELECT tipo, mensagem FROM insight_ia
    WHERE usuario_id IS NULL AND periodo_referencia = :mes""", mes=mes)
apoio.mostrar_insights(insights)
st.caption("Textos gerados na execução do pipeline; não mudam depois de uma revisão.")

st.subheader(f"Faturas de {mes}")
st.dataframe(faturas, hide_index=True)

st.subheader("Energia faturada por usuário e mês (kWh)")
consumo = apoio.consultar("""
    SELECT f.referencia_mes AS mes, u.nome AS usuario, f.total_kwh AS kwh
    FROM fatura f JOIN usuario u ON u.id = f.usuario_id""")
st.bar_chart(consumo, x="mes", y="kwh", color="usuario")

# Tela 2 - Fatura do usuário.
# Mostra a fatura de um usuário em um mês: itens, totais e insights da IA.
# É o mesmo conteúdo de "python main.py fatura <usuario_id> --mes AAAA-MM".
# Os dados vêm das tabelas usuario, fatura, item_fatura, sessao e insight_ia.
import pandas as pd
import streamlit as st

import apoio

apoio.iniciar_tela("Fatura do usuário")

usuarios = apoio.consultar("SELECT id, nome, apartamento, perfil FROM usuario ORDER BY id")
coluna_usuario, coluna_mes = st.columns(2)
nome = coluna_usuario.selectbox("Usuário", usuarios["nome"])
usuario = usuarios[usuarios["nome"] == nome].iloc[0]

# int(): o id vem do pandas como numpy.int64, que o SQLite não aceita como parâmetro.
faturas = apoio.consultar("SELECT * FROM fatura WHERE usuario_id = :usuario_id "
                          "ORDER BY referencia_mes DESC", usuario_id=int(usuario["id"]))
if faturas.empty:
    st.info("Este usuário ainda não tem fatura.")
    st.stop()
mes = coluna_mes.selectbox("Mês", faturas["referencia_mes"])
fatura = faturas[faturas["referencia_mes"] == mes].iloc[0]

mensal = fatura["modalidade"] == "mensal"
modalidade = "A - plano mensal" if mensal else "B - carga avulsa"
vencimento = pd.to_datetime(fatura["vencimento"]).strftime("%d/%m/%Y")
st.write(f"**Unidade:** {usuario['apartamento'] or 'sem unidade'} | **Modalidade:** {modalidade} | "
         f"**Perfil (IA):** {usuario['perfil']} | **Status:** {fatura['status']} | "
         f"**Vencimento:** {vencimento}")

st.subheader("Itens")
itens = apoio.consultar("""
    SELECT i.sessao_id AS sessao, substr(s.inicio, 1, 16) AS inicio, i.tipo_item AS tipo, i.tipo_horario_aplicado AS faixa,
           i.energia_kwh AS kwh, i.horas_ociosidade AS horas_ociosas,
           i.valor_unitario, i.valor_total_item AS valor, i.ajuste_mes_anterior AS ajuste
    FROM item_fatura i JOIN sessao s ON s.id = i.sessao_id
    WHERE i.fatura_id = :fatura_id ORDER BY i.sessao_id, i.tipo_item""",
    fatura_id=int(fatura["id"]))
st.dataframe(itens, hide_index=True)
st.caption("Item de energia: kwh x valor_unitario. Item de ociosidade: horas_ociosas x valor_unitario.")

st.subheader("Totais")
colunas = st.columns(5)
colunas[0].metric(f"Energia ({fatura['total_kwh']:.1f} kWh)", apoio.reais(fatura["valor_energia"]))
colunas[1].metric("Ociosidade (P)", apoio.reais(fatura["valor_ociosidade"]))
if mensal:
    colunas[2].metric("Contribuição fixa (C)", apoio.reais(fatura["valor_fixo"]))
    colunas[3].metric("Total", apoio.reais(fatura["valor_final"]))
else:
    # No avulso o valor é reservado antes da carga; a sobra é devolvida (estorno).
    colunas[2].metric("Total", apoio.reais(fatura["valor_final"]))
    colunas[3].metric("Pré-autorizado", apoio.reais(fatura["pre_autorizado"]))
    colunas[4].metric("Estornado", apoio.reais(fatura["estorno"]))

if fatura["sessoes_em_revisao"] > 0:
    st.warning(f"{fatura['sessoes_em_revisao']} sessão(ões) do mês retida(s) pela IA, "
               "fora desta cobrança.")

st.subheader("Insights da IA")
insights = apoio.consultar("SELECT tipo, mensagem FROM insight_ia WHERE fatura_id = :fatura_id",
                           fatura_id=int(fatura["id"]))
apoio.mostrar_insights(insights)

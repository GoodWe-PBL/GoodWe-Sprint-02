# Tela 6 - Perfis e previsão.
# Mostra o perfil que o K-Means deu a cada usuário, a previsão de consumo do
# próximo mês e os gráficos gerados pelo pipeline.
# Os dados vêm das tabelas usuario e previsao_consumo e das imagens em outputs/.
import streamlit as st

import apoio
from src import config

apoio.iniciar_tela("Perfis e previsão")

st.subheader("Perfil de cada usuário (K-Means)")
usuarios = apoio.consultar("SELECT id, nome, apartamento, modalidade, perfil FROM usuario ORDER BY id")
st.dataframe(usuarios, hide_index=True)

st.subheader("Previsão do próximo mês (regressão Ridge)")
# A tabela guarda uma previsão por mês já processado; mostramos só a mais recente.
previsoes = apoio.consultar("""
    SELECT u.nome AS usuario, p.mes_base, p.mes_previsto, p.kwh_previsto, p.valor_previsto, p.metodo
    FROM previsao_consumo p JOIN usuario u ON u.id = p.usuario_id
    WHERE p.mes_base = (SELECT MAX(mes_base) FROM previsao_consumo)
    ORDER BY u.id""")
st.dataframe(previsoes, hide_index=True)

st.subheader("Gráficos gerados pelo pipeline")
graficos = {"03_perfis.png": "Perfis: consumo x uso no horário de pico",
            "04_ocupacao_por_hora.png": "Ocupação média dos carregadores por hora",
            "05_previsao.png": "Previsão x consumo real"}
for arquivo, legenda in graficos.items():
    caminho = config.PASTA_SAIDA / arquivo
    if caminho.exists():
        st.image(str(caminho), caption=legenda)

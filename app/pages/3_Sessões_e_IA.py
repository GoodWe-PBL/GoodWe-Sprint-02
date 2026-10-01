# Tela 3 - Sessões e IA.
# Lista todas as sessões de recarga com a decisão da IA de anomalias (status,
# score e motivo) e um gráfico de duração x fração da bateria.
# Os dados vêm das tabelas sessao, usuario e veiculo.
import streamlit as st

import apoio

# Cor de fundo das linhas que a IA não deixou cobrar.
CORES = {"em_revisao": "background-color: #ffe8cc; color: black",
         "descartada": "background-color: #ffc9c9; color: black",
         "erro": "background-color: #dee2e6; color: black"}


def filtrar(tabela, coluna, rotulo, lugar):
    """Mostra uma caixa de seleção e devolve só as linhas com o valor escolhido."""
    opcoes = ["Todos"] + sorted(tabela[coluna].dropna().unique())
    escolha = lugar.selectbox(rotulo, opcoes)
    if escolha == "Todos":
        return tabela
    return tabela[tabela[coluna] == escolha]


def cor_da_linha(linha):
    """Devolve a cor de cada célula da linha, de acordo com o status da sessão."""
    return [CORES.get(linha["status"], "")] * len(linha)


apoio.iniciar_tela("Sessões e IA")
st.write("Toda sessão passa pela IA de anomalias antes do rateio. **Só as sessões com status "
         "\"validada\" entram na fatura.** As \"em_revisao\" ficam retidas até o gestor decidir, "
         "as \"descartadas\" nunca são cobradas e as com \"erro\" falharam na validação da ingestão.")

# LEFT JOIN: uma sessão com erro pode apontar para um usuário ou veículo que não existe.
# substr(inicio, 1, 16): fica só "AAAA-MM-DD HH:MM", sem segundos.
sessoes = apoio.consultar("""
    SELECT s.id, u.nome AS usuario, s.origem, substr(s.inicio, 1, 16) AS inicio,
           s.duracao_minutos / 60.0 AS duracao_h,
           s.energia_kwh, s.energia_kwh / v.capacidade_bateria_kwh AS fracao_bateria,
           s.status, s.score_anomalia, s.motivo_revisao
    FROM sessao s
    LEFT JOIN usuario u ON u.id = s.usuario_id
    LEFT JOIN veiculo v ON v.id = s.veiculo_id
    ORDER BY s.id""")

colunas = st.columns(3)
sessoes = filtrar(sessoes, "status", "Status", colunas[0])
sessoes = filtrar(sessoes, "origem", "Origem", colunas[1])
sessoes = filtrar(sessoes, "usuario", "Usuário", colunas[2])

st.write(f"{len(sessoes)} sessões. Laranja = em revisão, vermelho = descartada, cinza = erro.")
tabela_colorida = sessoes.style.apply(cor_da_linha, axis=1).format(precision=2)
st.dataframe(tabela_colorida, hide_index=True)
st.caption("score_anomalia vem do Isolation Forest: quanto menor, mais estranha é a sessão. "
           "Fica vazio quando uma regra decidiu antes do modelo.")

st.subheader("Duração x fração da bateria")
st.write("Cada ponto é uma sessão. Fração da bateria = energia da sessão dividida pela "
         "capacidade da bateria do veículo (acima de 1 é fisicamente impossível).")
st.scatter_chart(sessoes, x="duracao_h", y="fracao_bateria", color="status")

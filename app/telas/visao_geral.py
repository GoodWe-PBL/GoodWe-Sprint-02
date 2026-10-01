# Tela 1 - Visão geral (gestor).
# Mostra o resumo do mês escolhido: métricas, insights do gestor, faturas e o
# consumo de cada usuário. Os dados vêm das tabelas fatura, item_fatura e insight_ia.
from matplotlib.figure import Figure

import banco
import componentes


def montar(area, mes=None):
    """Desenha a tela inteira. É chamada de novo sempre que o mês é trocado."""
    componentes.limpar(area)
    componentes.escrever_titulo(area, "Visão geral do gestor")

    meses = banco.consultar("SELECT DISTINCT referencia_mes AS mes FROM fatura ORDER BY mes DESC")
    meses = meses["mes"].tolist()
    if mes is None:
        mes = meses[0]  # a tela abre no mês mais recente
    linha = componentes.criar_linha(area)
    componentes.criar_seletor(linha, "Mês", meses, mes, lambda novo_mes: montar(area, novo_mes))

    faturas = banco.consultar("""
        SELECT u.nome AS usuario, f.modalidade, f.total_kwh AS kwh, f.valor_energia AS energia,
               f.valor_ociosidade AS ociosidade, f.valor_fixo AS fixo, f.valor_final AS total,
               f.sessoes_em_revisao AS em_revisao, f.status
        FROM fatura f JOIN usuario u ON u.id = f.usuario_id
        WHERE f.referencia_mes = :mes ORDER BY u.id""", mes=mes)

    # Uma sessão pode ter vários itens (um por faixa horária), por isso o DISTINCT.
    sessoes_faturadas = banco.consultar("""
        SELECT COUNT(DISTINCT i.sessao_id) AS total
        FROM item_fatura i JOIN fatura f ON f.id = i.fatura_id
        WHERE f.referencia_mes = :mes""", mes=mes)["total"][0]

    componentes.mostrar_metricas(area, {
        "Sessões faturadas": sessoes_faturadas,
        "Energia faturada": f"{faturas['kwh'].sum():.1f} kWh",
        "Receita": componentes.reais(faturas["total"].sum()),
        "Sessões retidas pela IA": faturas["em_revisao"].sum(),
    })

    componentes.escrever_subtitulo(area, "Insights do gestor")
    # Insight sem usuário (usuario_id nulo) é o que a IA escreveu para o gestor.
    insights = banco.consultar("""
        SELECT tipo, mensagem FROM insight_ia
        WHERE usuario_id IS NULL AND periodo_referencia = :mes""", mes=mes)
    componentes.mostrar_insights(area, insights)
    componentes.escrever_texto(area, "(Textos gerados na execução do pipeline; não mudam depois "
                                     "de uma revisão.)")

    componentes.escrever_subtitulo(area, f"Faturas de {mes}")
    componentes.mostrar_tabela(area, faturas)

    componentes.escrever_subtitulo(area, "Energia faturada por usuário e mês (kWh)")
    consumo = banco.consultar("""
        SELECT f.referencia_mes AS mes, u.nome AS usuario, f.total_kwh AS kwh
        FROM fatura f JOIN usuario u ON u.id = f.usuario_id""")
    # pivot: uma linha por mês e uma coluna por usuário, para empilhar as barras
    kwh_por_mes = consumo.pivot(index="mes", columns="usuario", values="kwh").fillna(0)
    figura = Figure(figsize=(10, 4.5))
    eixo = figura.add_subplot()
    kwh_por_mes.plot(kind="bar", stacked=True, ax=eixo, rot=0, colormap="tab20")
    eixo.legend(fontsize=7, bbox_to_anchor=(1.01, 1), loc="upper left")
    figura.tight_layout()
    componentes.mostrar_grafico(area, figura)

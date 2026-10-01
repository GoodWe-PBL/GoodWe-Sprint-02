# Tela 2 - Fatura do usuário.
# Mostra a fatura de um usuário em um mês: itens, totais e insights da IA.
# É o mesmo conteúdo de "python main.py fatura <usuario_id> --mes AAAA-MM".
# Os dados vêm das tabelas usuario, fatura, item_fatura, sessao e insight_ia.
import pandas as pd

import banco
import componentes


def montar(area, nome=None, mes=None):
    """Desenha a tela inteira. É chamada de novo quando o usuário ou o mês é trocado."""
    componentes.limpar(area)
    componentes.escrever_titulo(area, "Fatura do usuário")

    usuarios = banco.consultar("SELECT id, nome, COALESCE(apartamento, 'sem unidade') AS unidade, "
                               "perfil FROM usuario ORDER BY id")
    nomes = usuarios["nome"].tolist()
    if nome is None:
        nome = nomes[0]
    usuario = usuarios[usuarios["nome"] == nome].iloc[0]

    # int(): o id vem do pandas como numpy.int64, que o SQLite não aceita como parâmetro.
    faturas = banco.consultar("SELECT * FROM fatura WHERE usuario_id = :usuario_id "
                              "ORDER BY referencia_mes DESC", usuario_id=int(usuario["id"]))
    meses = faturas["referencia_mes"].tolist()

    linha = componentes.criar_linha(area)
    # Ao trocar de usuário o mês volta para o mais recente (por isso não é repassado).
    componentes.criar_seletor(linha, "Usuário", nomes, nome, lambda novo_nome: montar(area, novo_nome))
    if not meses:
        componentes.escrever_texto(area, "Este usuário ainda não tem fatura.")
        return
    if mes is None:
        mes = meses[0]
    componentes.criar_seletor(linha, "Mês", meses, mes, lambda novo_mes: montar(area, nome, novo_mes))
    fatura = faturas[faturas["referencia_mes"] == mes].iloc[0]

    mensal = fatura["modalidade"] == "mensal"
    modalidade = "A - plano mensal" if mensal else "B - carga avulsa"
    vencimento = pd.to_datetime(fatura["vencimento"]).strftime("%d/%m/%Y")
    componentes.escrever_texto(
        area, f"Unidade: {usuario['unidade']}  |  Modalidade: {modalidade}  |  "
              f"Perfil (IA): {usuario['perfil']}  |  Status: {fatura['status']}  |  "
              f"Vencimento: {vencimento}")

    componentes.escrever_subtitulo(area, "Itens")
    # substr(inicio, 1, 16): fica só "AAAA-MM-DD HH:MM", sem segundos.
    itens = banco.consultar("""
        SELECT i.sessao_id AS sessao, substr(s.inicio, 1, 16) AS inicio, i.tipo_item AS tipo,
               i.tipo_horario_aplicado AS faixa, i.energia_kwh AS kwh,
               i.horas_ociosidade AS horas_ociosas, i.valor_unitario,
               i.valor_total_item AS valor, i.ajuste_mes_anterior AS ajuste
        FROM item_fatura i JOIN sessao s ON s.id = i.sessao_id
        WHERE i.fatura_id = :fatura_id ORDER BY i.sessao_id, i.tipo_item""",
        fatura_id=int(fatura["id"]))
    componentes.mostrar_tabela(area, itens)
    componentes.escrever_texto(area, "Item de energia: kwh x valor_unitario. "
                                     "Item de ociosidade: horas_ociosas x valor_unitario.")

    componentes.escrever_subtitulo(area, "Totais")
    totais = {f"Energia ({fatura['total_kwh']:.1f} kWh)": componentes.reais(fatura["valor_energia"]),
              "Ociosidade (P)": componentes.reais(fatura["valor_ociosidade"])}
    if mensal:
        totais["Contribuição fixa (C)"] = componentes.reais(fatura["valor_fixo"])
        totais["Total"] = componentes.reais(fatura["valor_final"])
    else:
        # No avulso o valor é reservado antes da carga; a sobra é devolvida (estorno).
        totais["Total"] = componentes.reais(fatura["valor_final"])
        totais["Pré-autorizado"] = componentes.reais(fatura["pre_autorizado"])
        totais["Estornado"] = componentes.reais(fatura["estorno"])
    componentes.mostrar_metricas(area, totais)

    if fatura["sessoes_em_revisao"] > 0:
        componentes.escrever_texto(area, f"{fatura['sessoes_em_revisao']} sessão(ões) do mês "
                                         "retida(s) pela IA, fora desta cobrança.")

    componentes.escrever_subtitulo(area, "Insights da IA")
    insights = banco.consultar("SELECT tipo, mensagem FROM insight_ia WHERE fatura_id = :fatura_id",
                               fatura_id=int(fatura["id"]))
    componentes.mostrar_insights(area, insights)

"""
IA — Insights em linguagem natural (Etapa 8 da Sprint 01).

Templates preenchidos com as saídas dos outros módulos de IA (anomalias, perfil,
previsão e horário). Cada insight vira um registro INSIGHT_IA vinculado à fatura.
A Sprint 01 previa "NLP / templates inteligentes"; no protótipo usamos templates,
que são auditáveis e não inventam números.

Cada insight é um dicionário {"tipo", "valor", "mensagem"}.
"""


def para_formato_brasileiro(texto):
    """Troca os separadores: '1,234.50' -> '1.234,50'."""
    return texto.replace(",", "X").replace(".", ",").replace("X", ".")


def reais(valor):
    """1234.5 -> 'R$ 1.234,50'"""
    return para_formato_brasileiro(f"R$ {valor:,.2f}")


def numero(valor, casas=1):
    """1234.56 -> '1.234,6'"""
    return para_formato_brasileiro(f"{valor:,.{casas}f}")


def mes_e_ano(mes):
    """'2026-09' -> '09/2026'"""
    ano, numero_do_mes = mes.split("-")
    return f"{numero_do_mes}/{ano}"


def insights_usuario(contexto):
    """Monta os insights de um usuário em um mês.
    contexto traz os números do usuário no mês (ver pipeline.contexto_do_usuario)."""
    insights = []
    mes = mes_e_ano(contexto["mes"])
    proximo_mes = mes_e_ano(contexto["proximo_mes"])
    kwh_mes = contexto["kwh_mes"]
    kwh_previsto = contexto.get("kwh_previsto")

    # 1. sessões retidas pela IA
    retidas = contexto["sessoes_em_revisao"]
    if retidas:
        quantidade = len(retidas)
        motivo = retidas[0]["motivo"]
        insights.append({"tipo": "anomalia", "valor": float(quantidade), "mensagem":
            f"{quantidade} sessão(ões) sua(s) ficou(aram) em análise e não foi(ram) cobrada(s) nesta fatura "
            f"({motivo}). Se o gestor aprovar, o valor entra na próxima fatura como ajuste."})

    # 2. previsão do próximo mês (para o plano mensal aparece mesmo com previsão zero)
    if kwh_previsto is not None and (kwh_previsto >= 1 or contexto["modalidade"] == "mensal"):
        texto = (f"Previsão para {proximo_mes}: cerca de {numero(kwh_previsto, 0)} kWh, "
                 f"fatura estimada em {reais(contexto['valor_previsto'])}.")
        media = contexto["kwh_media_hist"]
        if media >= 20 and kwh_previsto > 1.3 * media:
            texto += f" Isso está {kwh_previsto / media - 1:.0%} acima da sua média mensal."
        insights.append({"tipo": "previsao", "valor": contexto["valor_previsto"], "mensagem": texto})

    # 3. sugestão de horário (quem usa muito o pico) ou elogio (quem já usa o noturno)
    if contexto.get("economia_horario", 0) >= 3 and contexto["pct_pico"] >= 0.25:
        insights.append({"tipo": "sugestao_horario", "valor": contexto["economia_horario"], "mensagem":
            f"Em {mes}, {contexto['pct_pico']:.0%} da sua energia foi no horário de pico (17h–22h). "
            f"Programando o início da recarga para {contexto['hora_sugerida']:02d}h (agendamento do carregador), quando a ocupação média dos "
            f"carregadores é de {contexto['ocupacao_sugerida']:.0%}, você economizaria cerca de "
            f"{reais(contexto['economia_horario'])} por mês."})
    elif kwh_mes > 0 and contexto["pct_fora_pico"] >= 0.7:
        insights.append({"tipo": "economia", "valor": contexto["economia_noturno"], "mensagem":
            f"{contexto['pct_fora_pico']:.0%} da sua energia em {mes} foi no horário noturno. "
            f"Comparado ao pico, isso representou uma economia de {reais(contexto['economia_noturno'])}."})

    # 4. comparação com o grupo (só quando a diferença é de 15% ou mais)
    media_do_grupo = contexto["media_grupo_kwh"]
    if kwh_mes > 0 and media_do_grupo > 0:
        diferenca = kwh_mes / media_do_grupo - 1
        if abs(diferenca) >= 0.15:
            sentido = "acima" if diferenca > 0 else "abaixo"
            insights.append({"tipo": "comparativo", "valor": kwh_mes, "mensagem":
                f"Seu consumo de {numero(kwh_mes)} kWh ficou {abs(diferenca):.0%} {sentido} da média "
                f"do seu grupo de uso ({contexto['perfil']}: {numero(media_do_grupo)} kWh)."})

    # 5. recomendação de troca de modalidade
    recomendacao = contexto.get("recomendacao_modalidade")
    if recomendacao:
        insights.append({"tipo": "modalidade", "valor": recomendacao["economia"], "mensagem":
            f"Pelo consumo previsto, a modalidade {recomendacao['sugerida']} sairia "
            f"{reais(recomendacao['economia'])} "
            f"mais barata que a {recomendacao['atual']} no próximo mês."})

    # 6. plano mensal sem uso no mês
    if contexto["modalidade"] == "mensal" and kwh_mes == 0:
        insights.append({"tipo": "comparativo", "valor": 0.0, "mensagem":
            f"Você não usou o carregador em {mes}; a fatura tem apenas a contribuição fixa do plano."})
    return insights


def insights_gestor(contexto):
    """Monta os insights do mês para o gestor do condomínio."""
    mes = mes_e_ano(contexto["mes"])
    proximo_mes = mes_e_ano(contexto["proximo_mes"])

    insights = [{"tipo": "operacional", "valor": contexto["kwh_total"], "mensagem":
        f"{mes}: {contexto['n_validadas']} sessões faturadas, {numero(contexto['kwh_total'])} kWh, "
        f"receita de energia/ociosidade de {reais(contexto['receita'])} + "
        f"{reais(contexto['receita_fixa'])} de planos."}]
    if contexto["n_revisao"]:
        insights.append({"tipo": "anomalia", "valor": float(contexto["n_revisao"]), "mensagem":
            f"{contexto['n_revisao']} sessão(ões) aguardando revisão do gestor "
            f"({numero(contexto['kwh_revisao'])} kWh retidos da cobrança)."})
    if contexto["n_descartadas"]:
        insights.append({"tipo": "anomalia", "valor": float(contexto["n_descartadas"]), "mensagem":
            f"{contexto['n_descartadas']} sessão(ões) sem entrega de energia descartada(s) automaticamente."})
    insights.append({"tipo": "previsao", "valor": contexto["kwh_previsto_total"], "mensagem":
        f"Demanda prevista para {proximo_mes}: {numero(contexto['kwh_previsto_total'], 0)} kWh no condomínio. "
        f"Horário mais disputado: {contexto['hora_pico_ocupacao']:02d}h "
        f"({contexto['ocupacao_maxima']:.0%} dos carregadores ocupados em média)."})
    return insights

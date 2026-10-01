"""
IA — Insights em linguagem natural (Etapa 8 da Sprint 01).

Templates preenchidos com as saídas dos outros módulos de IA (anomalias, perfil,
previsão e horário). Cada insight vira um registro INSIGHT_IA vinculado à fatura.
A Sprint 01 previa "NLP / templates inteligentes"; no protótipo usamos templates,
que são auditáveis e não inventam números.
"""


def _r(v: float) -> str:
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _n(v: float, casas: int = 1) -> str:
    return f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _m(mes: str) -> str:
    ano, m = mes.split("-")
    return f"{m}/{ano}"


def insights_usuario(ctx: dict) -> list[dict]:
    """ctx traz os números do usuário no mês (ver pipeline._contexto_usuario)."""
    saida = []
    mes, prox = _m(ctx["mes"]), _m(ctx["proximo_mes"])

    if ctx["sessoes_em_revisao"]:
        n = len(ctx["sessoes_em_revisao"])
        motivo = ctx["sessoes_em_revisao"][0]["motivo"]
        saida.append({"tipo": "anomalia", "valor": float(n), "mensagem":
            f"{n} sessão(ões) sua(s) ficou(aram) em análise e não foi(ram) cobrada(s) nesta fatura "
            f"({motivo}). Se o gestor aprovar, o valor entra na próxima fatura como ajuste."})

    if ctx.get("kwh_previsto") is not None and (ctx["kwh_previsto"] >= 1 or ctx["modalidade"] == "mensal"):
        texto = (f"Previsão para {prox}: cerca de {_n(ctx['kwh_previsto'], 0)} kWh, "
                 f"fatura estimada em {_r(ctx['valor_previsto'])}.")
        media = ctx["kwh_media_hist"]
        if media >= 20 and ctx["kwh_previsto"] > 1.3 * media:
            texto += f" Isso está {ctx['kwh_previsto'] / media - 1:.0%} acima da sua média mensal."
        saida.append({"tipo": "previsao", "valor": ctx["valor_previsto"], "mensagem": texto})

    if ctx.get("economia_horario", 0) >= 3 and ctx["pct_pico"] >= 0.25:
        saida.append({"tipo": "sugestao_horario", "valor": ctx["economia_horario"], "mensagem":
            f"Em {mes}, {ctx['pct_pico']:.0%} da sua energia foi no horário de pico (17h–22h). "
            f"Programando o início da recarga para {ctx['hora_sugerida']:02d}h (agendamento do carregador), quando a ocupação média dos "
            f"carregadores é de {ctx['ocupacao_sugerida']:.0%}, você economizaria cerca de "
            f"{_r(ctx['economia_horario'])} por mês."})
    elif ctx["kwh_mes"] > 0 and ctx["pct_fora_pico"] >= 0.7:
        saida.append({"tipo": "economia", "valor": ctx["economia_noturno"], "mensagem":
            f"{ctx['pct_fora_pico']:.0%} da sua energia em {mes} foi no horário noturno. "
            f"Comparado ao pico, isso representou uma economia de {_r(ctx['economia_noturno'])}."})

    if ctx["kwh_mes"] > 0 and ctx["media_grupo_kwh"] > 0:
        dif = ctx["kwh_mes"] / ctx["media_grupo_kwh"] - 1
        if abs(dif) >= 0.15:
            sentido = "acima" if dif > 0 else "abaixo"
            saida.append({"tipo": "comparativo", "valor": ctx["kwh_mes"], "mensagem":
                f"Seu consumo de {_n(ctx['kwh_mes'])} kWh ficou {abs(dif):.0%} {sentido} da média "
                f"do seu grupo de uso ({ctx['perfil']}: {_n(ctx['media_grupo_kwh'])} kWh)."})

    rec = ctx.get("recomendacao_modalidade")
    if rec:
        saida.append({"tipo": "modalidade", "valor": rec["economia"], "mensagem":
            f"Pelo consumo previsto, a modalidade {rec['sugerida']} sairia {_r(rec['economia'])} "
            f"mais barata que a {rec['atual']} no próximo mês."})

    if ctx["modalidade"] == "mensal" and ctx["kwh_mes"] == 0:
        saida.append({"tipo": "comparativo", "valor": 0.0, "mensagem":
            f"Você não usou o carregador em {mes}; a fatura tem apenas a contribuição fixa do plano."})
    return saida


def insights_gestor(ctx: dict) -> list[dict]:
    mes, prox = _m(ctx["mes"]), _m(ctx["proximo_mes"])
    saida = [{"tipo": "operacional", "valor": ctx["kwh_total"], "mensagem":
        f"{mes}: {ctx['n_validadas']} sessões faturadas, {_n(ctx['kwh_total'])} kWh, "
        f"receita de energia/ociosidade de {_r(ctx['receita'])} + {_r(ctx['receita_fixa'])} de planos."}]
    if ctx["n_revisao"]:
        saida.append({"tipo": "anomalia", "valor": float(ctx["n_revisao"]), "mensagem":
            f"{ctx['n_revisao']} sessão(ões) aguardando revisão do gestor "
            f"({_n(ctx['kwh_revisao'])} kWh retidos da cobrança)."})
    if ctx["n_descartadas"]:
        saida.append({"tipo": "anomalia", "valor": float(ctx["n_descartadas"]), "mensagem":
            f"{ctx['n_descartadas']} sessão(ões) sem entrega de energia descartada(s) automaticamente."})
    saida.append({"tipo": "previsao", "valor": ctx["kwh_previsto_total"], "mensagem":
        f"Demanda prevista para {prox}: {_n(ctx['kwh_previsto_total'], 0)} kWh no condomínio. "
        f"Horário mais disputado: {ctx['hora_pico_ocupacao']:02d}h "
        f"({ctx['ocupacao_maxima']:.0%} dos carregadores ocupados em média)."})
    return saida

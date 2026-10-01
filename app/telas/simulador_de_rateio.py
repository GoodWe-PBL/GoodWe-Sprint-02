# Tela 5 - Simulador de rateio.
# Calcula o valor de UMA sessão inventada, passo a passo, para explicar o modelo.
# Não usa o banco: os dados vêm do formulário e as contas são feitas pelas mesmas
# funções do rateio real (src/rateio/tarifas.py e src/rateio/calculo.py).
from datetime import date, datetime, timedelta

import customtkinter as ctk
import pandas as pd
from matplotlib.dates import DateFormatter
from matplotlib.figure import Figure

import banco  # ajusta o caminho de busca para o "from src..." abaixo
import componentes
from src import config
from src.rateio.calculo import fechar_fatura, itens_da_sessao, valor_sessao
from src.rateio.tarifas import dividir_energia_por_faixa, ociosidade_cobravel_por_faixa


def montar_leituras(inicio, minutos_carga, kwh, minutos_ocioso):
    """Uma leitura a cada 5 min. A energia sobe em linha reta durante a carga
    (potência constante) e fica parada durante o tempo ocioso."""
    potencia = kwh / (minutos_carga / 60)
    leituras = []
    for minuto in range(0, minutos_carga + minutos_ocioso + 1, 5):
        carregando = minuto < minutos_carga
        leituras.append({"timestamp": inicio + timedelta(minutes=minuto),
                         "potencia_kw": potencia if carregando else 0.0,
                         "energia_kwh": kwh * min(minuto / minutos_carga, 1)})
    return leituras


def texto_da_formula(modalidade, itens, totais):
    """Monta a fórmula F (mensal) ou V (avulso) preenchida com os números da sessão."""
    margem = config.M_MARGEM_AVULSA
    ociosidade = totais["valor_ociosidade"]

    # Uma parcela "E x T" para cada faixa horária em que houve energia.
    parcelas = []
    for item in itens:
        if item["tipo_item"] == "energia" and modalidade == "mensal":
            parcelas.append(f"{item['energia_kwh']:.2f} x {item['valor_unitario']:.2f}")
        elif item["tipo_item"] == "energia":
            # no avulso o valor unitário do item já é T + M; separamos para mostrar os dois
            tarifa = item["valor_unitario"] - margem
            parcelas.append(f"{item['energia_kwh']:.2f} x ({tarifa:.2f} + {margem:.2f})")
    energia = " + ".join(parcelas)

    if modalidade == "mensal":
        return (f"F = soma(E x T) + C + P\n"
                f"F = ({energia}) + {totais['valor_fixo']:.2f} + {ociosidade:.2f}\n"
                f"F = {componentes.reais(totais['valor_final'])}\n"
                f"(C é cobrado uma vez por mês, não por sessão. Aqui o mês tem só esta sessão.)")
    return (f"V = E x (T + M) + P\n"
            f"V = ({energia}) + {ociosidade:.2f}\n"
            f"V = {componentes.reais(totais['valor_final'])}\n"
            f"Pré-autorizado: {componentes.reais(totais['pre_autorizado'])} | "
            f"Estorno: {componentes.reais(totais['estorno'])}")


def mostrar_calculo(area, modalidade, inicio, minutos_carga, kwh, minutos_ocioso):
    leituras = montar_leituras(inicio, minutos_carga, kwh, minutos_ocioso)

    componentes.escrever_subtitulo(area, "1. Leituras de telemetria (a cada 5 min)")
    tabela_leituras = pd.DataFrame(leituras)
    figura = Figure(figsize=(9, 3))
    eixo = figura.add_subplot()
    eixo.plot(tabela_leituras["timestamp"], tabela_leituras["energia_kwh"])
    eixo.set_ylabel("Energia acumulada (kWh)")
    eixo.xaxis.set_major_formatter(DateFormatter("%H:%M"))  # eixo x mostra só hora:minuto
    figura.tight_layout()
    componentes.mostrar_grafico(area, figura)

    componentes.escrever_subtitulo(area, "2. Energia por faixa horária (E), em kWh")
    componentes.escrever_texto(area, "Faixas: pico 17h-22h, intermediário 7h-17h, fora de pico "
                                     "22h-7h. A energia de cada intervalo de 5 min vai para a "
                                     "faixa em que ele aconteceu.")
    energia_por_faixa = dividir_energia_por_faixa(leituras)
    componentes.escrever_texto(area, str(energia_por_faixa))

    componentes.escrever_subtitulo(area, "3. Ociosidade cobrável, em horas")
    componentes.escrever_texto(area, f"Tempo plugado depois do fim da carga, descontados os "
                                     f"primeiros {config.TOLERANCIA_OCIOSIDADE_MIN} min de tolerância.")
    ociosidade_por_faixa = ociosidade_cobravel_por_faixa(leituras)
    componentes.escrever_texto(area, str(ociosidade_por_faixa))

    componentes.escrever_subtitulo(area, "4. Itens de cobrança")
    itens = itens_da_sessao(energia_por_faixa, ociosidade_por_faixa, modalidade)
    componentes.mostrar_tabela(area, pd.DataFrame(itens))

    componentes.escrever_subtitulo(area, "5. Fórmula preenchida")
    # fechar_fatura soma os itens e aplica C (mensal) ou a pré-autorização (avulso).
    totais = fechar_fatura(modalidade, itens, n_sessoes=1, valores_por_sessao=[valor_sessao(itens)])
    componentes.escrever_texto(area, texto_da_formula(modalidade, itens, totais), fonte="Consolas")


def montar(area, modalidade="mensal", inicio="15:00", minutos_carga="180", kwh="20",
           minutos_ocioso="90"):
    """Desenha a tela inteira. Os valores chegam como texto, do jeito que foram digitados.
    Os valores iniciais fazem a sessão pegar duas faixas e ter ociosidade cobrável."""
    componentes.limpar(area)
    componentes.escrever_titulo(area, "Simulador de rateio")

    linha = componentes.criar_linha(area)
    caixa_modalidade = componentes.criar_seletor(linha, "Modalidade", ["mensal", "avulso"], modalidade)
    campo_inicio = componentes.criar_campo(linha, "Início (HH:MM)", inicio)
    campo_carga = componentes.criar_campo(linha, "Carga (min)", minutos_carga)
    campo_kwh = componentes.criar_campo(linha, "Energia (kWh)", kwh)
    campo_ocioso = componentes.criar_campo(linha, "Ocioso ao final (min)", minutos_ocioso)

    def calcular():
        # redesenha a tela com o que está digitado no formulário
        montar(area, caixa_modalidade.get(), campo_inicio.get(), campo_carga.get(),
               campo_kwh.get(), campo_ocioso.get())

    ctk.CTkButton(linha, text="Calcular", width=90, command=calcular).pack(side="left")

    # Converte os textos em números. Se algo não for número, o Python gera ValueError.
    try:
        hora = datetime.strptime(inicio, "%H:%M").time()
        minutos_carga = int(minutos_carga)
        minutos_ocioso = int(minutos_ocioso)
        kwh = float(kwh.replace(",", "."))
    except ValueError:
        componentes.escrever_texto(area, "Valores inválidos. Use o horário como HH:MM e números "
                                         "nos outros campos.")
        return
    # As leituras são de 5 em 5 min, então os minutos precisam ser múltiplos de 5.
    if minutos_carga <= 0 or kwh <= 0 or minutos_ocioso < 0 or minutos_carga % 5 or minutos_ocioso % 5:
        componentes.escrever_texto(area, "Use minutos múltiplos de 5, carga e energia maiores que zero.")
        return

    inicio = datetime.combine(date.today(), hora)
    mostrar_calculo(area, modalidade, inicio, minutos_carga, kwh, minutos_ocioso)

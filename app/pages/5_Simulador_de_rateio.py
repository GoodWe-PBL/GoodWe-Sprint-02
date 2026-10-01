# Tela 5 - Simulador de rateio.
# Calcula o valor de UMA sessão inventada, passo a passo, para explicar o modelo.
# Não usa o banco: os dados vêm do formulário e as contas são feitas pelas mesmas
# funções do rateio real (src/rateio/tarifas.py e src/rateio/calculo.py).
from datetime import date, datetime, time, timedelta

import pandas as pd
import streamlit as st

import apoio
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


apoio.iniciar_tela("Simulador de rateio")

colunas = st.columns(5)
modalidade = colunas[0].selectbox("Modalidade", ["mensal", "avulso"])
# Valores iniciais escolhidos para a sessão pegar duas faixas e ter ociosidade cobrável.
hora_inicio = colunas[1].time_input("Horário de início", time(15, 0))
# step=5 nos minutos para as leituras de 5 em 5 min fecharem certinho.
minutos_carga = colunas[2].slider("Duração da carga (min)", 5, 720, 180, step=5)
kwh = colunas[3].number_input("Energia (kWh)", 0.5, 100.0, 20.0)
minutos_ocioso = colunas[4].slider("Minutos ocioso ao final", 0, 480, 90, step=5)

inicio = datetime.combine(date.today(), hora_inicio)
leituras = montar_leituras(inicio, minutos_carga, kwh, minutos_ocioso)

st.subheader("1. Leituras de telemetria (a cada 5 min)")
st.line_chart(pd.DataFrame(leituras), x="timestamp", y="energia_kwh")

st.subheader("2. Energia por faixa horária (E)")
st.write("Faixas: pico 17h-22h, intermediário 7h-17h, fora de pico 22h-7h. A energia de cada "
         "intervalo de 5 min vai para a faixa em que ele aconteceu.")
energia_por_faixa = dividir_energia_por_faixa(leituras)
st.write(energia_por_faixa)

st.subheader("3. Ociosidade cobrável (horas)")
st.write(f"Tempo plugado depois do fim da carga, descontados os primeiros "
         f"{config.TOLERANCIA_OCIOSIDADE_MIN} min de tolerância.")
ociosidade_por_faixa = ociosidade_cobravel_por_faixa(leituras)
st.write(ociosidade_por_faixa)

st.subheader("4. Itens de cobrança")
itens = itens_da_sessao(energia_por_faixa, ociosidade_por_faixa, modalidade)
st.dataframe(pd.DataFrame(itens), hide_index=True)

st.subheader("5. Fórmula preenchida")
# fechar_fatura soma os itens e aplica C (mensal) ou a pré-autorização (avulso).
totais = fechar_fatura(modalidade, itens, n_sessoes=1, valores_por_sessao=[valor_sessao(itens)])
ociosidade = totais["valor_ociosidade"]
margem = config.M_MARGEM_AVULSA

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
    st.code(f"F = soma(E x T) + C + P\n"
            f"F = ({energia}) + {totais['valor_fixo']:.2f} + {ociosidade:.2f}\n"
            f"F = {apoio.reais(totais['valor_final'])}")
    st.caption("C é cobrado uma vez por mês, não por sessão. Aqui o mês tem só esta sessão.")
else:
    st.code(f"V = E x (T + M) + P\n"
            f"V = ({energia}) + {ociosidade:.2f}\n"
            f"V = {apoio.reais(totais['valor_final'])}")
    st.write(apoio.escapar_cifrao(f"Pré-autorizado: {apoio.reais(totais['pre_autorizado'])} | "
                                  f"Estorno: {apoio.reais(totais['estorno'])}"))

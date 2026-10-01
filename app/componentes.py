# Peças visuais prontas, usadas por todas as telas: título, texto, seletor,
# campo de digitação, métricas, tabela, gráfico e imagem.
# "area" é sempre o quadro (frame) onde a peça vai ser colocada.
from tkinter import ttk

import customtkinter as ctk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from PIL import Image

FONTE = "Segoe UI"


def reais(valor):
    """1234.5 -> 'R$ 1.234,50'"""
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def limpar(area):
    """Apaga tudo o que está na área, para a tela ser desenhada de novo."""
    for componente in area.winfo_children():
        componente.destroy()


def escrever_titulo(area, texto):
    ctk.CTkLabel(area, text=texto, font=(FONTE, 24, "bold")).pack(anchor="w", pady=(5, 10))


def escrever_subtitulo(area, texto):
    ctk.CTkLabel(area, text=texto, font=(FONTE, 17, "bold")).pack(anchor="w", pady=(15, 5))


def escrever_texto(area, texto, fonte=FONTE):
    # wraplength: largura (em pixels) a partir da qual o texto quebra de linha
    ctk.CTkLabel(area, text=texto, font=(fonte, 13), justify="left", wraplength=1000).pack(anchor="w")


def criar_linha(area):
    """Quadro invisível para colocar várias peças lado a lado."""
    linha = ctk.CTkFrame(area, fg_color="transparent")
    linha.pack(fill="x", pady=5)
    return linha


def criar_seletor(linha, rotulo, opcoes, escolhida, ao_trocar=None):
    """Rótulo + caixa de opções. ao_trocar é a função chamada com a nova opção."""
    ctk.CTkLabel(linha, text=rotulo).pack(side="left", padx=(0, 5))
    caixa = ctk.CTkOptionMenu(linha, values=opcoes, command=ao_trocar)
    caixa.set(escolhida)
    caixa.pack(side="left", padx=(0, 20))
    return caixa


def criar_campo(linha, rotulo, valor):
    """Rótulo + campo de digitação já preenchido com um valor."""
    ctk.CTkLabel(linha, text=rotulo).pack(side="left", padx=(0, 5))
    campo = ctk.CTkEntry(linha, width=70)
    campo.insert(0, valor)
    campo.pack(side="left", padx=(0, 20))
    return campo


def mostrar_metricas(area, metricas):
    """metricas é um dicionário rótulo -> valor. Cada par vira um cartão."""
    linha = criar_linha(area)
    for rotulo, valor in metricas.items():
        cartao = ctk.CTkFrame(linha)
        cartao.pack(side="left", padx=(0, 10))
        ctk.CTkLabel(cartao, text=rotulo).pack(padx=15, pady=(8, 0))
        ctk.CTkLabel(cartao, text=str(valor), font=(FONTE, 20, "bold")).pack(padx=15, pady=(0, 8))


def mostrar_insights(area, insights):
    """Uma frase para cada linha da tabela insight_ia."""
    for insight in insights.itertuples():
        escrever_texto(area, f"[{insight.tipo}] {insight.mensagem}")


def mostrar_tabela(area, dados, max_linhas=10, cores=None):
    """Desenha um DataFrame como tabela, com até max_linhas visíveis (o resto rola).
    cores (opcional) é um dicionário status -> cor de fundo, para destacar linhas
    pela coluna "status"."""
    dados = dados.round(2).astype(object).fillna("")  # 2 casas decimais; vazio no lugar de nulo
    colunas = list(dados.columns)
    linha = criar_linha(area)
    linhas_visiveis = max(1, min(len(dados), max_linhas))
    grade = ttk.Treeview(linha, columns=colunas, show="headings", height=linhas_visiveis)

    for coluna in colunas:
        # largura da coluna pelo maior texto que ela tem (com um limite)
        textos = [coluna] + dados[coluna].astype(str).tolist()
        maior_texto = max(len(texto) for texto in textos)
        grade.heading(coluna, text=coluna)
        grade.column(coluna, width=min(8 * maior_texto + 20, 400), stretch=False)

    for status, cor in (cores or {}).items():
        grade.tag_configure(status, background=cor)
    for registro in dados.to_dict("records"):
        # a "tag" da linha é o status dela; é pela tag que a cor é aplicada
        grade.insert("", "end", values=list(registro.values()), tags=(registro.get("status", ""),))

    barra_vertical = ttk.Scrollbar(linha, orient="vertical", command=grade.yview)
    barra_horizontal = ttk.Scrollbar(linha, orient="horizontal", command=grade.xview)
    grade.configure(yscrollcommand=barra_vertical.set, xscrollcommand=barra_horizontal.set)
    barra_vertical.pack(side="right", fill="y")
    barra_horizontal.pack(side="bottom", fill="x")
    grade.pack(side="left", fill="x", expand=True)


def mostrar_grafico(area, figura):
    """Coloca uma figura do matplotlib dentro da janela."""
    tela_do_grafico = FigureCanvasTkAgg(figura, master=area)
    tela_do_grafico.draw()
    tela_do_grafico.get_tk_widget().pack(anchor="w", pady=5)


def mostrar_imagem(area, caminho, largura=750):
    foto = Image.open(caminho)
    altura = int(largura * foto.height / foto.width)  # mantém a proporção
    imagem = ctk.CTkImage(foto, size=(largura, altura))
    ctk.CTkLabel(area, image=imagem, text="").pack(anchor="w", pady=5)

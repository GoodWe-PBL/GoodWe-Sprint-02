# Ponto de entrada da interface: python app/principal.py
# Cria a janela, o menu lateral e a área onde cada tela é desenhada.
from tkinter import messagebox

import customtkinter as ctk

import banco  # precisa vir antes de "main" e "src": é ele que ajusta o caminho de busca
import componentes
import main
from src import config
from telas import (fatura_do_usuario, perfis_e_previsao, revisao_do_gestor, sessoes_e_ia,
                   simulador_de_rateio, visao_geral)

# Nome que aparece no menu -> função que desenha a tela.
TELAS = {
    "Visão geral": visao_geral.montar,
    "Fatura do usuário": fatura_do_usuario.montar,
    "Sessões e IA": sessoes_e_ia.montar,
    "Revisão do gestor": revisao_do_gestor.montar,
    "Simulador de rateio": simulador_de_rateio.montar,
    "Perfis e previsão": perfis_e_previsao.montar,
}


def abrir_tela(nome):
    if not config.CAMINHO_BANCO.exists():
        componentes.limpar(area)
        componentes.escrever_texto(area, "O banco de dados ainda não existe. Clique em \"Reexecutar "
                                         "pipeline\" ou rode no terminal: python main.py executar")
        return
    TELAS[nome](area)


def reexecutar_pipeline():
    confirmou = messagebox.askyesno("Reexecutar pipeline", "Isso recria o banco do zero e apaga as "
                                    "revisões feitas pelo gestor. Continuar?")
    if not confirmou:
        return
    botao_reexecutar.configure(text="Executando...", state="disabled")
    janela.update()  # redesenha o botão antes de a janela ficar ocupada por alguns segundos
    main.cmd_executar(None)  # a mesma função de "python main.py executar"
    botao_reexecutar.configure(text="Reexecutar pipeline", state="normal")
    menu.set("Visão geral")
    abrir_tela("Visão geral")


ctk.set_appearance_mode("light")
janela = ctk.CTk()
janela.title("EV ChargeOps")
janela.geometry("1300x800")

lateral = ctk.CTkFrame(janela)
lateral.pack(side="left", fill="y")
ctk.CTkLabel(lateral, text="EV ChargeOps", font=(componentes.FONTE, 18, "bold")).pack(padx=15, pady=15)
# O menu chama abrir_tela com o nome do botão clicado.
menu = ctk.CTkSegmentedButton(lateral, values=list(TELAS), orientation="vertical", command=abrir_tela)
menu.set("Visão geral")
menu.pack(padx=10)
botao_reexecutar = ctk.CTkButton(lateral, text="Reexecutar pipeline", command=reexecutar_pipeline)
botao_reexecutar.pack(side="bottom", padx=10, pady=15)

# Área com rolagem onde as telas são desenhadas.
area = ctk.CTkScrollableFrame(janela, fg_color="transparent")
area.pack(side="left", fill="both", expand=True, padx=15, pady=10)

abrir_tela("Visão geral")
janela.mainloop()

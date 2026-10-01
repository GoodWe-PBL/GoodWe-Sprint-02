# Tela 6 - Perfis e previsão.
# Mostra o perfil que o K-Means deu a cada usuário, a previsão de consumo do
# próximo mês e os gráficos gerados pelo pipeline.
# Os dados vêm das tabelas usuario e previsao_consumo e das imagens em outputs/.
import banco
import componentes
from src import config

# Arquivo em outputs/ -> legenda.
GRAFICOS = {"03_perfis.png": "Perfis: consumo x uso no horário de pico",
            "04_ocupacao_por_hora.png": "Ocupação média dos carregadores por hora",
            "05_previsao.png": "Previsão x consumo real"}


def montar(area):
    componentes.limpar(area)
    componentes.escrever_titulo(area, "Perfis e previsão")

    componentes.escrever_subtitulo(area, "Perfil de cada usuário (K-Means)")
    usuarios = banco.consultar("SELECT id, nome, apartamento, modalidade, perfil FROM usuario ORDER BY id")
    componentes.mostrar_tabela(area, usuarios)

    componentes.escrever_subtitulo(area, "Previsão do próximo mês (regressão Ridge)")
    # A tabela guarda uma previsão por mês já processado; mostramos só a mais recente.
    previsoes = banco.consultar("""
        SELECT u.nome AS usuario, p.mes_base, p.mes_previsto, p.kwh_previsto, p.valor_previsto, p.metodo
        FROM previsao_consumo p JOIN usuario u ON u.id = p.usuario_id
        WHERE p.mes_base = (SELECT MAX(mes_base) FROM previsao_consumo)
        ORDER BY u.id""")
    componentes.mostrar_tabela(area, previsoes)

    componentes.escrever_subtitulo(area, "Gráficos gerados pelo pipeline")
    for arquivo, legenda in GRAFICOS.items():
        caminho = config.PASTA_SAIDA / arquivo
        if caminho.exists():
            componentes.escrever_texto(area, legenda)
            componentes.mostrar_imagem(area, caminho)

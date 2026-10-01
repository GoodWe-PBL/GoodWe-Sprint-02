# Tela 3 - Sessões e IA.
# Lista todas as sessões de recarga com a decisão da IA de anomalias (status,
# score e motivo) e um gráfico de duração x fração da bateria.
# Os dados vêm das tabelas sessao, usuario e veiculo.
from matplotlib.figure import Figure

import banco
import componentes

# Cor de fundo, na tabela, das linhas que a IA não deixou cobrar.
CORES_DA_LINHA = {"em_revisao": "#ffe8cc", "descartada": "#ffc9c9", "erro": "#dee2e6"}
# Cor de cada status no gráfico.
CORES_DO_PONTO = {"validada": "#9aa5b1", "em_revisao": "#e8590c", "descartada": "#c92a2a",
                  "erro": "#495057"}


def opcoes_da_coluna(sessoes, coluna):
    """'Todos' + os valores que existem na coluna, em ordem alfabética."""
    return ["Todos"] + sorted(sessoes[coluna].dropna().unique())


def filtrar(sessoes, coluna, escolha):
    if escolha == "Todos":
        return sessoes
    return sessoes[sessoes[coluna] == escolha]


def montar(area, status="Todos", origem="Todos", usuario="Todos"):
    """Desenha a tela inteira. É chamada de novo sempre que um filtro é trocado."""
    componentes.limpar(area)
    componentes.escrever_titulo(area, "Sessões e IA")
    componentes.escrever_texto(
        area, "Toda sessão passa pela IA de anomalias antes do rateio. Só as sessões com status "
              "\"validada\" entram na fatura. As \"em_revisao\" ficam retidas até o gestor decidir, "
              "as \"descartada\" nunca são cobradas e as com \"erro\" falharam na validação da ingestão.")

    # LEFT JOIN: uma sessão com erro pode apontar para um usuário ou veículo que não existe.
    # substr(inicio, 1, 16): fica só "AAAA-MM-DD HH:MM", sem segundos.
    sessoes = banco.consultar("""
        SELECT s.id, u.nome AS usuario, s.origem, substr(s.inicio, 1, 16) AS inicio,
               s.duracao_minutos / 60.0 AS duracao_h, s.energia_kwh,
               s.energia_kwh / v.capacidade_bateria_kwh AS fracao_bateria,
               s.status, s.score_anomalia, s.motivo_revisao
        FROM sessao s
        LEFT JOIN usuario u ON u.id = s.usuario_id
        LEFT JOIN veiculo v ON v.id = s.veiculo_id
        ORDER BY s.id""")

    # Cada seletor redesenha a tela com o novo valor e mantém os outros dois filtros.
    linha = componentes.criar_linha(area)
    componentes.criar_seletor(linha, "Status", opcoes_da_coluna(sessoes, "status"), status,
                              lambda novo: montar(area, novo, origem, usuario))
    componentes.criar_seletor(linha, "Origem", opcoes_da_coluna(sessoes, "origem"), origem,
                              lambda novo: montar(area, status, novo, usuario))
    componentes.criar_seletor(linha, "Usuário", opcoes_da_coluna(sessoes, "usuario"), usuario,
                              lambda novo: montar(area, status, origem, novo))

    sessoes = filtrar(sessoes, "status", status)
    sessoes = filtrar(sessoes, "origem", origem)
    sessoes = filtrar(sessoes, "usuario", usuario)

    componentes.escrever_texto(area, f"{len(sessoes)} sessões. Laranja = em revisão, "
                                     "vermelho = descartada, cinza = erro.")
    componentes.mostrar_tabela(area, sessoes, max_linhas=12, cores=CORES_DA_LINHA)
    componentes.escrever_texto(area, "score_anomalia vem do Isolation Forest: quanto menor, mais "
                                     "estranha é a sessão. Fica vazio quando uma regra decidiu "
                                     "antes do modelo.")

    componentes.escrever_subtitulo(area, "Duração x fração da bateria")
    componentes.escrever_texto(area, "Cada ponto é uma sessão. Fração da bateria = energia da sessão "
                                     "dividida pela capacidade da bateria do veículo (acima de 1 é "
                                     "fisicamente impossível).")
    figura = Figure(figsize=(9, 4.5))
    eixo = figura.add_subplot()
    for nome_status, grupo in sessoes.groupby("status"):
        eixo.scatter(grupo["duracao_h"], grupo["fracao_bateria"], s=20,
                     color=CORES_DO_PONTO[nome_status], label=f"{nome_status} ({len(grupo)})")
    eixo.set_xlabel("Duração da sessão (h)")
    eixo.set_ylabel("Energia / capacidade da bateria")
    if not sessoes.empty:
        eixo.legend()
    figura.tight_layout()
    componentes.mostrar_grafico(area, figura)

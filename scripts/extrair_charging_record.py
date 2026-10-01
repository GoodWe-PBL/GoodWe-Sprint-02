"""
Extrai as sessões do relatório "Charging Record" exportado do portal SEMS+ (PDF)
e gera data/raw/charging_record.csv.

Uso:
    python scripts/extrair_charging_record.py caminho/Charging_Record.pdf

Cada linha da tabela do PDF tem o formato:
    <card_id> MM/DD/AAAA HH:MM MM/DD/AAAA HH:MM HH:MM:SS <kwh>
"""
import csv
import re
import sys
from pathlib import Path

PADRAO_LINHA = re.compile(
    r"(?P<card>[0-9A-Z]{16})\s+"
    r"(?P<inicio>\d{2}/\d{2}/\d{4} \d{2}:\d{2})\s+"
    r"(?P<fim>\d{2}/\d{2}/\d{4} \d{2}:\d{2})\s+"
    r"(?P<duracao>\d{2}:\d{2}:\d{2})\s+"
    r"(?P<kwh>\d+\.\d{2})"
)
PADRAO_SN = re.compile(r"EV Charger SN:\s*(\S+)")
PADRAO_TOTAL = re.compile(r"Total Energy Charged:\s*([\d.]+)")


def extrair_texto(caminho_pdf: Path) -> str:
    import pdfplumber  # importado aqui para o resto do módulo não depender dele

    with pdfplumber.open(caminho_pdf) as pdf:
        return "\n".join(pagina.extract_text() or "" for pagina in pdf.pages)


def parse_texto(texto: str):
    """Retorna (serial_carregador, total_declarado_kwh, lista_de_sessoes)."""
    sn = PADRAO_SN.search(texto)
    total = PADRAO_TOTAL.search(texto)
    sessoes = [m.groupdict() for m in PADRAO_LINHA.finditer(texto)]
    return (sn.group(1) if sn else None,
            float(total.group(1)) if total else None,
            sessoes)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    origem = Path(sys.argv[1])
    texto = extrair_texto(origem) if origem.suffix.lower() == ".pdf" else origem.read_text()
    serial, total_declarado, sessoes = parse_texto(texto)

    soma = round(sum(float(s["kwh"]) for s in sessoes), 2)
    print(f"Carregador: {serial} | sessões lidas: {len(sessoes)} | soma: {soma} kWh "
          f"| total no relatório: {total_declarado} kWh")
    if total_declarado is not None and abs(soma - total_declarado) > 0.05:
        print("ATENÇÃO: a soma das sessões não bate com o total do relatório.")

    destino = Path(__file__).resolve().parents[1] / "data" / "raw" / "charging_record.csv"
    with open(destino, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["serial_carregador", "card_id", "inicio", "fim", "duracao", "energia_kwh"])
        # o relatório vem do mais recente para o mais antigo; gravamos em ordem cronológica
        for s in reversed(sessoes):
            w.writerow([serial, s["card"], s["inicio"], s["fim"], s["duracao"], s["kwh"]])
    print(f"CSV gravado em {destino}")


if __name__ == "__main__":
    main()

import os
import re

from bs4 import BeautifulSoup
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CAMINHO_CREDENCIAIS = os.path.join(BASE_DIR, "credentials.json")
CAMINHO_TOKEN = os.path.join(BASE_DIR, "token.json")


# ---------------------------------------------------------------
# AUTENTICAÇÃO (igual à fase 2)
# ---------------------------------------------------------------
def autenticar():
    creds = None

    if os.path.exists(CAMINHO_TOKEN):
        creds = Credentials.from_authorized_user_file(CAMINHO_TOKEN, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            fluxo = InstalledAppFlow.from_client_secrets_file(
                CAMINHO_CREDENCIAIS, SCOPES
            )
            creds = fluxo.run_local_server(port=0)

        with open(CAMINHO_TOKEN, "w", encoding="utf-8") as token:
            token.write(creds.to_json())

    return creds


QUERIES = {
    "loja": (
        "from:(amazon.com.br OR amazon.com OR marketplace.amazon.com.br) "
        "-from:(aws) newer_than:7d"
    ),
    "aws": ("from:(aws OR notify.aws OR aws.amazon.com OR aws-billing) newer_than:7d"),
}


def buscar_emails(service, categoria="loja", limite=5):
    """Busca e-mails por categoria: 'loja' ou 'aws'."""
    if categoria not in QUERIES:
        raise ValueError(f"Categoria inválida: {categoria}")

    resultado = (
        service.users()
        .messages()
        .list(userId="me", q=QUERIES[categoria], maxResults=limite)
        .execute()
    )

    return resultado.get("messages", [])


# ---------------------------------------------------------------
# NOVO: percorre a árvore MIME e devolve o corpo do e-mail
# ---------------------------------------------------------------
def extrair_corpo(payload):
    """
    Recebe o 'payload' de uma mensagem e devolve o texto do corpo.
    Estratégia: procura text/plain primeiro; se não achar, usa text/html limpo.
    """
    texto_puro = None
    texto_html = None

    def percorrer(parte):
        nonlocal texto_puro, texto_html

        mime = parte.get("mimeType", "")

        # Parte simples: tem o conteúdo direto no 'body'
        if mime == "text/plain" and parte.get("body", {}).get("data"):
            texto_puro = decodificar(parte["body"]["data"])

        elif mime == "text/html" and parte.get("body", {}).get("data"):
            texto_html = decodificar(parte["body"]["data"])

        # Parte composta: desce nos filhos (multipart/alternative, multipart/related...)
        for filho in parte.get("parts", []):
            percorrer(filho)

    percorrer(payload)

    if texto_puro:
        return texto_puro
    if texto_html:
        return limpar_html(texto_html)
    return ""


def decodificar(dados_base64):
    """A API do Gmail devolve o corpo em base64url."""
    import base64

    return base64.urlsafe_b64decode(dados_base64).decode("utf-8", errors="ignore")


# ---------------------------------------------------------------
# NOVO: limpa o HTML e reduz o texto ao que interessa
# ---------------------------------------------------------------
def limpar_html(html):
    soup = BeautifulSoup(html, "html.parser")

    # Remove o que nunca é conteúdo útil
    for tag in soup(["script", "style", "head", "title", "meta"]):
        tag.decompose()

    texto = soup.get_text(separator="\n")

    # Normaliza espaços e remove linhas vazias repetidas
    linhas = [linha.strip() for linha in texto.splitlines()]
    linhas = [linha for linha in linhas if linha]

    return "\n".join(linhas)


# ---------------------------------------------------------------
# NOVO: extrai os campos que interessam de um e-mail da Amazon
# ---------------------------------------------------------------
def extrair_campos(texto, categoria="loja"):
    campos = {"pedido": None, "valor": None, "entrega": None, "servico": None}

    # Valor em reais — comum aos dois
    m = re.search(r"R\$\s*\d{1,3}(?:\.\d{3})*,\d{2}", texto)
    if m:
        campos["valor"] = m.group(0)

    if categoria == "loja":
        m = re.search(r"\b\d{3}-\d{7}-\d{7}\b", texto)
        if m:
            campos["pedido"] = m.group(0)

        m = re.search(
            r"(?:chegar[áa]|previs[ãa]o de entrega)[^\n]{0,80}",
            texto,
            re.IGNORECASE,
        )
        if m:
            campos["entrega"] = m.group(0).strip()

    elif categoria == "aws":
        # ID de conta AWS: 12 dígitos
        m = re.search(r"\b\d{12}\b", texto)
        if m:
            campos["pedido"] = f"conta {m.group(0)}"

        # Nome do serviço AWS mais comum no texto
        servicos = [
            "EC2",
            "S3",
            "RDS",
            "Lambda",
            "CloudWatch",
            "IAM",
            "CloudFront",
            "Route 53",
            "SES",
            "SNS",
            "EBS",
        ]
        for s in servicos:
            if re.search(rf"\b{re.escape(s)}\b", texto):
                campos["servico"] = s
                break

    return campos


# ---------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------
def obter_cabecalhos(service, msg_id):
    msg = (
        service.users()
        .messages()
        .get(
            userId="me",
            id=msg_id,
            format="metadata",
            metadataHeaders=["From", "Subject", "Date"],
        )
        .execute()
    )
    return {h["name"]: h["value"] for h in msg["payload"]["headers"]}


def obter_mensagem_completa(service, msg_id):
    """Aqui está a mudança central: format='full' traz o corpo."""
    return (
        service.users().messages().get(userId="me", id=msg_id, format="full").execute()
    )


def main():
    credenciais = autenticar()
    service = build("gmail", "v1", credentials=credenciais)

    for categoria in ["loja", "aws"]:
        mensagens = buscar_emails(service, categoria=categoria)

        print(f"\n{'#' * 70}")
        print(f"CATEGORIA: {categoria.upper()} — {len(mensagens)} e-mail(s)")
        print(f"{'#' * 70}\n")

        for m in mensagens:
            try:
                completo = obter_mensagem_completa(service, m["id"])
            except HttpError as erro:
                print(f"Falha ao ler {m['id']}: {erro}")
                continue

            cabecalhos = {h["name"]: h["value"] for h in completo["payload"]["headers"]}
            corpo = extrair_corpo(completo["payload"])
            campos = extrair_campos(corpo, categoria=categoria)

            print("Assunto.:", cabecalhos.get("Subject", "sem assunto"))
            print("De......:", cabecalhos.get("From", "sem remetente"))
            print("Pedido..:", campos["pedido"] or "não encontrado")
            print("Valor...:", campos["valor"] or "não encontrado")
            print("-" * 70)


if __name__ == "__main__":
    try:
        main()
    except HttpError as erro:
        print("Erro da API do Gmail:", erro)

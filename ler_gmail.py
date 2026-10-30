# Projeto para ler e-mail, verificar se é da Amazon e enviar resumo pelo whatsapp
import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Escopo somente leitura: o script pode LER, nunca alterar ou apagar
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CAMINHO_CREDENCIAIS = os.path.join(BASE_DIR, "credentials.json")
CAMINHO_TOKEN = os.path.join(BASE_DIR, "token.json")


def autenticar():
    """Faz o login OAuth e devolve as credenciais válidas."""
    creds = None

    # Se já existe um token salvo, reaproveita
    if os.path.exists(CAMINHO_TOKEN):
        creds = Credentials.from_authorized_user_file(CAMINHO_TOKEN, SCOPES)

    # Se não existe ou está inválido, resolve
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())  # renova sem abrir navegador
        else:
            fluxo = InstalledAppFlow.from_client_secrets_file(
                CAMINHO_CREDENCIAIS, SCOPES
            )
            creds = fluxo.run_local_server(port=0)  # abre o navegador

        # Salva para as próximas execuções
        with open(CAMINHO_TOKEN, "w", encoding="utf-8") as token:
            token.write(creds.to_json())

    return creds


def buscar_emails_amazon(service, limite=5):
    """Filtra no próprio Gmail: só remetentes Amazon, últimos 7 dias."""
    query = (
        "from:(amazon.com.br OR amazon.com OR marketplace.amazon.com.br) newer_than:7d"
    )

    resultado = (
        service.users()
        .messages()
        .list(userId="me", q=query, maxResults=limite)
        .execute()
    )

    return resultado.get("messages", [])


def obter_cabecalhos(service, msg_id):
    """Busca só os cabeçalhos — rápido, sem baixar o corpo do e-mail."""
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


def main():
    credenciais = autenticar()
    service = build("gmail", "v1", credentials=credenciais)

    mensagens = buscar_emails_amazon(service)

    if not mensagens:
        print("Nenhum e-mail da Amazon nos últimos 7 dias.")
        return

    print(f"{len(mensagens)} e-mail(s) encontrado(s)\n")
    print("=" * 70)

    for m in mensagens:
        try:
            cabecalhos = obter_cabecalhos(service, m["id"])
        except HttpError as erro:
            print(f"Falha ao ler a mensagem {m['id']}: {erro}")
            continue

        print("ID......:", m["id"])
        print("Data....:", cabecalhos.get("Date", "sem data"))
        print("De......:", cabecalhos.get("From", "sem remetente"))
        print("Assunto.:", cabecalhos.get("Subject", "sem assunto"))
        print("-" * 70)


if __name__ == "__main__":
    try:
        main()
    except HttpError as erro:
        print("Erro da API do Gmail:", erro)

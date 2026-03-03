"""Cliente SOAP para GoSATI / Zangari — consultas financeiras de condomínios."""

import gzip
import json
import logging
import re
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from pathlib import Path

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import BASE_DIR, Settings
from app.core.exceptions import NotFoundError
from app.models.session import Session
from app.models.source import Source
from app.services.document_converter import extract_text_from_pdf

logger = logging.getLogger(__name__)

GOSATI_DIR = BASE_DIR / "data" / "gosati"


class GoSatiError(Exception):
    """Raised when GoSati API returns an error."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_zangari_senha_from_env() -> str | None:
    """Lê ZANGARI_SENHA direto do .env (pydantic-settings trata # como comentário)."""
    env_path = Path(".env")
    if not env_path.exists():
        return None
    with open(env_path, "r") as f:
        for line in f:
            if line.startswith("ZANGARI_SENHA="):
                value = line.split("=", 1)[1].strip()
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                elif value.startswith("'") and value.endswith("'"):
                    value = value[1:-1]
                return value
    return None


def _xml_to_dict(element: ET.Element) -> dict | str | None:
    """Converte elemento XML em dicionário recursivamente."""
    result = {}

    if element.attrib:
        result["@attributes"] = dict(element.attrib)

    if element.text and element.text.strip():
        if len(element) == 0:
            return element.text.strip()
        result["#text"] = element.text.strip()

    children: dict = {}
    for child in element:
        child_data = _xml_to_dict(child)
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag

        if tag in children:
            if not isinstance(children[tag], list):
                children[tag] = [children[tag]]
            children[tag].append(child_data)
        else:
            children[tag] = child_data

    if children:
        result.update(children)

    return result if result else None


def _dict_to_text(data: dict, label: str) -> str:
    """Formata resposta GoSati como texto legível para o Gemini."""
    return f"=== {label} ===\n\n{json.dumps(data, ensure_ascii=False, indent=2)}"


def _detect_mime_type(data: bytes) -> str | None:
    """Detecta mime type a partir dos magic bytes."""
    if len(data) < 10:
        return None
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"\x89PNG":
        return "image/png"
    if data[:3] == b"GIF":
        return "image/gif"
    if data[:2] == b"BM":
        return "image/bmp"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:5] == b"%PDF-":
        return "application/pdf"
    if data[:4] in (b"II\x2a\x00", b"MM\x00\x2a"):
        return "image/tiff"
    return None


GOSATI_QUERY_LABELS = {
    "prestacao_contas": "Prestação de Contas",
    "fluxo_caixa": "Fluxo de Caixa",
    "inadimplencia": "Inadimplência",
    "periodo_fechamento": "Período de Fechamento",
    "previsao_orcamentaria": "Previsão Orçamentária",
    "relacao_lancamentos": "Relação de Lançamentos",
    "relacao_pendentes": "Relação de Pendentes",
}


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class GoSatiService:
    def __init__(self, db: AsyncSession, settings: Settings):
        self.db = db
        self.settings = settings
        self._senha: str | None = None

    def _get_senha(self) -> str:
        if self._senha is None:
            self._senha = _read_zangari_senha_from_env() or self.settings.zangari_senha
        return self._senha

    def _auth_params(self) -> str:
        return (
            f"<usuario>{self.settings.zangari_usuario}</usuario>\n"
            f"      <senha>{self._get_senha()}</senha>\n"
            f"      <chave>{self.settings.zangari_chave}</chave>"
        )

    # ------------------------------------------------------------------
    # SOAP transport
    # ------------------------------------------------------------------

    async def _send_soap_request(self, action: str, body: str) -> str:
        headers = {
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": f'"http://gosati.com.br/webservices/{action}"',
            "User-Agent": "NotebookZang SOAP Client",
            "Accept-Encoding": "gzip, deflate",
        }
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    self.settings.zangari_url, content=body, headers=headers
                )
        except httpx.ConnectError as e:
            raise GoSatiError(f"Não foi possível conectar ao servidor GoSati: {e}")
        except httpx.TimeoutException:
            raise GoSatiError("Timeout ao conectar ao servidor GoSati (60s)")

        content_encoding = response.headers.get("Content-Encoding", "").lower()
        if content_encoding == "gzip" or response.content[:2] == b"\x1f\x8b":
            try:
                return gzip.decompress(response.content).decode("utf-8")
            except Exception:
                return response.text
        return response.text

    def _parse_soap_response(self, xml_text: str, result_tag: str) -> dict | None:
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as e:
            raise GoSatiError(f"Erro ao processar XML da resposta: {e}")

        # Strip namespaces
        for elem in root.iter():
            if "}" in elem.tag:
                elem.tag = elem.tag.split("}")[1]

        # Check for SOAP fault
        for fault in root.iter("Fault"):
            faultstring = ""
            for fs in fault.iter("faultstring"):
                faultstring = fs.text or ""
            msg = faultstring
            if "--->" in msg:
                inner = msg.split("--->")[-1].strip()
                for sep in ["\n", "   em ", "   at "]:
                    if sep in inner:
                        inner = inner.split(sep)[0].strip()
                msg = inner
            if ": " in msg and msg.split(": ", 1)[0].replace(".", "").isalpha():
                msg = msg.split(": ", 1)[1]
            raise GoSatiError(msg)

        # Find result element
        for body in root.iter("Body"):
            for child in body:
                if (result_tag + "Response") in child.tag:
                    for grandchild in child:
                        if (result_tag + "Result") in grandchild.tag:
                            return _xml_to_dict(grandchild)
        return None

    # ------------------------------------------------------------------
    # 7 query methods
    # ------------------------------------------------------------------

    async def consultar_prestacao_contas(
        self,
        condominio: int,
        mes: int | None = None,
        ano: int | None = None,
        demonstr_contas: bool = True,
        demonstr_despesas: bool = True,
        relat_devedores: bool = True,
        demonstr_receitas: bool = True,
        acompanh_cobranca: bool = True,
        orcado_gasto: bool = True,
    ) -> dict | None:
        if not mes:
            mes = date.today().month
        if not ano:
            ano = date.today().year

        data_inicial = f"{ano}-{mes:02d}-01"
        if mes == 12:
            ultimo_dia = date(ano + 1, 1, 1) - timedelta(days=1)
        else:
            ultimo_dia = date(ano, mes + 1, 1) - timedelta(days=1)
        data_final = ultimo_dia.strftime("%Y-%m-%d")
        data_contas = data_final

        soap_body = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               xmlns:xsd="http://www.w3.org/2001/XMLSchema"
               xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <PrestacaoContasFechada xmlns="http://gosati.com.br/webservices/">
      <Condominio>{condominio}</Condominio>
      <Bloco_Ini></Bloco_Ini>
      <Bloco_Fin>ZZ</Bloco_Fin>
      <Data_Inicial>{data_inicial}T00:00:00</Data_Inicial>
      <Data_Final>{data_final}T23:59:59</Data_Final>
      <Mes>{mes}</Mes>
      <Ano>{ano}</Ano>
      <Data_Contas>{data_contas}T00:00:00</Data_Contas>
      <Demonstr_Contas>{str(demonstr_contas).lower()}</Demonstr_Contas>
      <Demonstr_Despesas>{str(demonstr_despesas).lower()}</Demonstr_Despesas>
      <Relat_Devedores>{str(relat_devedores).lower()}</Relat_Devedores>
      <Demonstr_Receitas>{str(demonstr_receitas).lower()}</Demonstr_Receitas>
      <Acompanh_Cobranca>{str(acompanh_cobranca).lower()}</Acompanh_Cobranca>
      <Orcado_gasto>{str(orcado_gasto).lower()}</Orcado_gasto>
      {self._auth_params()}
    </PrestacaoContasFechada>
  </soap:Body>
</soap:Envelope>"""

        xml_text = await self._send_soap_request("PrestacaoContasFechada", soap_body)
        return self._parse_soap_response(xml_text, "PrestacaoContasFechada")

    async def consultar_fluxo_caixa(
        self, condominio: int, mes: int | None = None, ano: int | None = None
    ) -> dict | None:
        if not mes:
            mes = date.today().month
        if not ano:
            ano = date.today().year

        data_inicial = f"{ano}-{mes:02d}-01"
        if mes == 12:
            ultimo_dia = date(ano + 1, 1, 1) - timedelta(days=1)
        else:
            ultimo_dia = date(ano, mes + 1, 1) - timedelta(days=1)
        data_final = ultimo_dia.strftime("%Y-%m-%d")

        soap_body = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               xmlns:xsd="http://www.w3.org/2001/XMLSchema"
               xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <FluxoCaixa xmlns="http://gosati.com.br/webservices/">
      <Condominio>{condominio}</Condominio>
      <Data_Inicial>{data_inicial}T00:00:00</Data_Inicial>
      <Data_Final>{data_final}T23:59:59</Data_Final>
      {self._auth_params()}
    </FluxoCaixa>
  </soap:Body>
</soap:Envelope>"""

        xml_text = await self._send_soap_request("FluxoCaixa", soap_body)
        return self._parse_soap_response(xml_text, "FluxoCaixa")

    async def consultar_inadimplencia(self, condominio: int) -> dict | None:
        soap_body = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               xmlns:xsd="http://www.w3.org/2001/XMLSchema"
               xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <ConsultaInadimplenciaUnidade xmlns="http://gosati.com.br/webservices/">
      <Condominio>{condominio}</Condominio>
      {self._auth_params()}
    </ConsultaInadimplenciaUnidade>
  </soap:Body>
</soap:Envelope>"""

        xml_text = await self._send_soap_request("ConsultaInadimplenciaUnidade", soap_body)
        return self._parse_soap_response(xml_text, "ConsultaInadimplenciaUnidade")

    async def consultar_periodo_fechamento(
        self, condominio: int, ano: int | None = None
    ) -> dict | None:
        if not ano:
            ano = date.today().year

        soap_body = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               xmlns:xsd="http://www.w3.org/2001/XMLSchema"
               xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <PeriodoFechamento xmlns="http://gosati.com.br/webservices/">
      <Condominio>{condominio}</Condominio>
      <Ano>{ano}</Ano>
      {self._auth_params()}
    </PeriodoFechamento>
  </soap:Body>
</soap:Envelope>"""

        xml_text = await self._send_soap_request("PeriodoFechamento", soap_body)
        return self._parse_soap_response(xml_text, "PeriodoFechamento")

    async def consultar_previsao_orcamentaria(
        self, condominio: int, mes: int | None = None, ano: int | None = None
    ) -> dict | None:
        if not mes:
            mes = date.today().month
        if not ano:
            ano = date.today().year

        soap_body = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               xmlns:xsd="http://www.w3.org/2001/XMLSchema"
               xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <PrevisaoOrcamentaria xmlns="http://gosati.com.br/webservices/">
      <Condominio>{condominio}</Condominio>
      <Mes>{mes}</Mes>
      <Ano>{ano}</Ano>
      {self._auth_params()}
    </PrevisaoOrcamentaria>
  </soap:Body>
</soap:Envelope>"""

        xml_text = await self._send_soap_request("PrevisaoOrcamentaria", soap_body)
        return self._parse_soap_response(xml_text, "PrevisaoOrcamentaria")

    async def consultar_relacao_lancamentos(
        self, condominio: int, mes: int | None = None, ano: int | None = None
    ) -> dict | None:
        if not mes:
            mes = date.today().month
        if not ano:
            ano = date.today().year

        data_inicial = f"{ano}-{mes:02d}-01"
        if mes == 12:
            ultimo_dia = date(ano + 1, 1, 1) - timedelta(days=1)
        else:
            ultimo_dia = date(ano, mes + 1, 1) - timedelta(days=1)
        data_final = ultimo_dia.strftime("%Y-%m-%d")

        soap_body = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               xmlns:xsd="http://www.w3.org/2001/XMLSchema"
               xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <RelacaoLancamento xmlns="http://gosati.com.br/webservices/">
      <Condominio>{condominio}</Condominio>
      <DataInicial>{data_inicial}T00:00:00</DataInicial>
      <DataFinal>{data_final}T23:59:59</DataFinal>
      <Mes>{mes}</Mes>
      <Ano>{ano}</Ano>
      {self._auth_params()}
    </RelacaoLancamento>
  </soap:Body>
</soap:Envelope>"""

        xml_text = await self._send_soap_request("RelacaoLancamento", soap_body)
        return self._parse_soap_response(xml_text, "RelacaoLancamento")

    async def consultar_relacao_pendentes(
        self, condominio: int, ano: int | None = None
    ) -> dict | None:
        if not ano:
            ano = date.today().year

        soap_body = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               xmlns:xsd="http://www.w3.org/2001/XMLSchema"
               xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <RelacaoPendentes xmlns="http://gosati.com.br/webservices/">
      <Condominio>{condominio}</Condominio>
      <Bloco></Bloco>
      <Unidade></Unidade>
      <Vencimento_Inicial>{ano}-01-01T00:00:00</Vencimento_Inicial>
      <Vencimento_Final>{ano}-12-31T23:59:59</Vencimento_Final>
      <Data_Posicao>{ano}-12-31T00:00:00</Data_Posicao>
      <Atualizacao_Monetaria>false</Atualizacao_Monetaria>
      <Data_Calculo>{ano}-12-31T00:00:00</Data_Calculo>
      {self._auth_params()}
    </RelacaoPendentes>
  </soap:Body>
</soap:Envelope>"""

        xml_text = await self._send_soap_request("RelacaoPendentes", soap_body)
        return self._parse_soap_response(xml_text, "RelacaoPendentes")

    # ------------------------------------------------------------------
    # Comprovantes (receipt images)
    # ------------------------------------------------------------------

    def extrair_despesas_com_comprovante(self, prestacao_data: dict) -> list[dict]:
        """Extrai despesas que possuem link de comprovante da prestação de contas."""
        despesas = []
        try:
            diffgram = prestacao_data.get("diffgram", {})
            prestacao = diffgram.get("PrestacaoContas", {})
            raw_despesas = prestacao.get("Despesas", [])
            if not isinstance(raw_despesas, list):
                raw_despesas = [raw_despesas]

            for d in raw_despesas:
                if not isinstance(d, dict):
                    continue
                link = d.get("link_docto", "")
                tem_docto = d.get("tem_docto", "0")
                if tem_docto == "1" and link and "AbrirDoctos" in link:
                    despesas.append({
                        "numero_lancamento": d.get("numero_lancamento", ""),
                        "historico": d.get("historico", ""),
                        "valor": d.get("valor", "0"),
                        "data": d.get("data", ""),
                        "nome_conta": d.get("nome_conta", ""),
                        "nome_sub_conta": d.get("nome_sub_conta", ""),
                        "link_docto": link,
                        "catalogo_id": d.get("catalogo_id", ""),
                    })
        except (KeyError, TypeError):
            pass
        return despesas

    async def baixar_comprovante(self, link_docto: str) -> list[tuple[bytes, str]]:
        """Baixa imagens/PDFs de comprovante de despesa.

        Retorna lista de (bytes, mime_type).
        """
        documents: list[tuple[bytes, str]] = []
        empty_count = 0
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                resp = await client.get(link_docto)
                if resp.status_code != 200:
                    logger.warning(
                        "GoSATI retornou HTTP %d ao acessar link_docto: %s",
                        resp.status_code, link_docto,
                    )
                    return documents

                html = resp.text
                # Tenta múltiplos padrões (GoSATI pode mudar o formato do redirect)
                session_match = (
                    re.search(r"Session=(\d+)", html)
                    or re.search(r"Session=([A-Za-z0-9]+)", html)
                    or re.search(r"session=([A-Za-z0-9]+)", html, re.IGNORECASE)
                    or re.search(r"SessionID?=([A-Za-z0-9]+)", html, re.IGNORECASE)
                )
                if not session_match:
                    logger.warning(
                        "Session ID não encontrado no HTML do GoSATI — "
                        "o formato do redirect pode ter mudado. URL: %s | "
                        "Início do HTML: %s",
                        link_docto,
                        html[:600].replace("\n", " ").replace("\r", ""),
                    )
                    return documents

                session_id = session_match.group(1)
                base_url = "https://sistemas.zangari.com.br/gocontroledocumentos/Show.aspx"
                cookies = resp.cookies

                for ca in range(20):
                    img_url = f"{base_url}?ca={ca}&or=2&Session={session_id}"
                    img_resp = await client.get(img_url, cookies=cookies)

                    if img_resp.status_code != 200:
                        logger.debug("Show.aspx ca=%d retornou HTTP %d", ca, img_resp.status_code)
                        empty_count += 1
                        if empty_count >= 2:
                            break
                        continue

                    mime = _detect_mime_type(img_resp.content)
                    if mime:
                        documents.append((img_resp.content, mime))
                        logger.debug("Show.aspx ca=%d: %s (%d bytes)", ca, mime, len(img_resp.content))
                        empty_count = 0
                        continue

                    empty_count += 1
                    if empty_count >= 2:
                        break
        except Exception as e:
            logger.warning("Erro ao baixar comprovante '%s': %s", link_docto, e)
        return documents

    # ------------------------------------------------------------------
    # High-level: query → save as Source
    # ------------------------------------------------------------------

    async def query_as_source(
        self,
        session_id: int,
        query_type: str,
        condominio: int,
        mes: int | None = None,
        ano: int | None = None,
    ) -> Source:
        """Executa consulta SOAP e salva o resultado como Source no banco."""
        session = await self.db.get(Session, session_id)
        if not session:
            raise NotFoundError(404, f"Session {session_id} não encontrada")

        data = await self._execute_query(query_type, condominio, mes, ano)

        label_base = GOSATI_QUERY_LABELS.get(query_type, query_type)
        period_suffix = ""
        if mes and ano:
            period_suffix = f" - {mes:02d}/{ano}"
        elif ano:
            period_suffix = f" - {ano}"
        label = f"{label_base}{period_suffix} (Cond. {condominio})"

        if data is None:
            raise GoSatiError(
                f"API GoSati não retornou dados para {label}. "
                "Verifique se o condomínio e período estão corretos."
            )

        text_content = _dict_to_text(data, label)
        content_bytes = text_content.encode("utf-8")

        # Salva em disco
        save_dir = GOSATI_DIR / str(session_id)
        save_dir.mkdir(parents=True, exist_ok=True)
        filename = f"gosati_{query_type}_{condominio}_{mes or 0}_{ano or 0}.txt"
        file_path = save_dir / filename
        file_path.write_bytes(content_bytes)

        source = Source(
            session_id=session_id,
            filename=filename,
            file_path=str(file_path),
            mime_type="text/plain",
            size_bytes=len(content_bytes),
            origin="gosati",
            label=label,
            text_path="",
            is_native=True,
        )
        self.db.add(source)
        session.source_count += 1
        await self.db.commit()
        await self.db.refresh(source)

        # Se prestação de contas, retorna dados para cache de comprovantes
        if query_type == "prestacao_contas":
            source._prestacao_data = data  # transient, não persiste

        return source

    async def save_comprovantes_as_sources(
        self,
        session_id: int,
        links: list[str],
        despesas_info: list[dict] | None = None,
    ) -> list[Source]:
        """Baixa comprovantes e salva cada imagem/PDF como Source.

        Args:
            despesas_info: lista de dicts com {numero_lancamento, historico, valor}
                           na mesma ordem de 'links'. Se fornecido, enriquece o label.
        """
        session = await self.db.get(Session, session_id)
        if not session:
            raise NotFoundError(404, f"Session {session_id} não encontrada")

        save_dir = GOSATI_DIR / str(session_id) / "comprovantes"
        save_dir.mkdir(parents=True, exist_ok=True)

        sources: list[Source] = []

        for link_idx, link in enumerate(links):
            documents = await self.baixar_comprovante(link)
            if not documents:
                logger.warning(
                    "Sessão %d: nenhum documento baixado para link %d/%d — "
                    "o comprovante pode não existir no GoSATI ou houve falha no download.",
                    session_id, link_idx + 1, len(links),
                )
                continue

            # Info do lançamento associado (se disponível)
            desp = (despesas_info[link_idx] if despesas_info and link_idx < len(despesas_info) else None)

            for page_idx, (doc_bytes, mime_type) in enumerate(documents):
                ext = {
                    "image/jpeg": ".jpg",
                    "image/png": ".png",
                    "image/gif": ".gif",
                    "image/bmp": ".bmp",
                    "image/webp": ".webp",
                    "image/tiff": ".tiff",
                    "application/pdf": ".pdf",
                }.get(mime_type, ".bin")

                filename = f"comprovante_{link_idx}_{page_idx}{ext}"
                file_path = save_dir / filename
                file_path.write_bytes(doc_bytes)

                # Extrai texto de PDFs para não enviar binário pesado ao Gemini
                text_path = ""
                is_native = True
                if mime_type == "application/pdf":
                    try:
                        extracted = extract_text_from_pdf(doc_bytes)
                        if extracted.strip():
                            txt_file = file_path.with_suffix(".extracted.txt")
                            txt_file.write_text(extracted, encoding="utf-8")
                            text_path = str(txt_file)
                            is_native = False
                            logger.info(
                                "PDF comprovante %s → %d chars texto",
                                filename, len(extracted),
                            )
                    except Exception as e:
                        logger.warning("Falha extração PDF %s: %s", filename, e)

                # Label enriquecido com info do lançamento
                if desp:
                    hist = desp.get("historico", "")[:60]
                    valor = desp.get("valor", "")
                    lanc = desp.get("numero_lancamento", "")
                    label = f"Comprovante Lanç.{lanc} — {hist} (R$ {valor}) pág {page_idx + 1}"
                else:
                    label = f"Comprovante {link_idx + 1} (pág {page_idx + 1})"

                source = Source(
                    session_id=session_id,
                    filename=filename,
                    file_path=str(file_path),
                    mime_type=mime_type,
                    size_bytes=len(doc_bytes),
                    origin="gosati",
                    label=label,
                    text_path=text_path,
                    is_native=is_native,
                )
                self.db.add(source)
                sources.append(source)
                session.source_count += 1

        if sources:
            await self.db.commit()
            for s in sources:
                await self.db.refresh(s)

        return sources

    # ------------------------------------------------------------------
    # Internal dispatch
    # ------------------------------------------------------------------

    async def _execute_query(
        self, query_type: str, condominio: int, mes: int | None, ano: int | None
    ) -> dict | None:
        dispatch = {
            "prestacao_contas": lambda: self.consultar_prestacao_contas(condominio, mes, ano),
            "fluxo_caixa": lambda: self.consultar_fluxo_caixa(condominio, mes, ano),
            "inadimplencia": lambda: self.consultar_inadimplencia(condominio),
            "periodo_fechamento": lambda: self.consultar_periodo_fechamento(condominio, ano),
            "previsao_orcamentaria": lambda: self.consultar_previsao_orcamentaria(condominio, mes, ano),
            "relacao_lancamentos": lambda: self.consultar_relacao_lancamentos(condominio, mes, ano),
            "relacao_pendentes": lambda: self.consultar_relacao_pendentes(condominio, ano),
        }
        fn = dispatch.get(query_type)
        if not fn:
            raise GoSatiError(f"Tipo de consulta inválido: {query_type}")
        return await fn()

    def format_as_text(self, data: dict | None, label: str) -> str:
        if data is None:
            return f"=== {label} ===\n\nNenhum dado retornado pela API."
        return _dict_to_text(data, label)

"""
src/ingestion/document_loader.py
─────────────────────────────────────────────────────────────────────────────
Ingests bank/credit card statements from:
  • CSV files  (any column layout — LLM normalises headers)
  • PDF files  (pdfplumber → text → LLM extraction)
  • Gmail      (OAuth fetch of statement attachments)

Returns a TransactionBatch for each source.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pdfplumber
from langchain_core.messages import HumanMessage, SystemMessage

from src.llm import get_fast_llm, get_reasoning_llm
from src.models import (
    Transaction,
    TransactionBatch,
    TransactionCategory,
    TransactionType,
)

logger = logging.getLogger(__name__)

# ─── Prompts ──────────────────────────────────────────────────────────────────

CATEGORISATION_SYSTEM = f"""You are a financial transaction categoriser.
Given a list of bank/credit card transactions, return a JSON array where each
element has:
  - "id": the transaction id passed in
  - "category": one of {[c.value for c in TransactionCategory]}
  - "subcategory": a short (1-3 word) specific label, e.g. "Swiggy delivery"
  - "merchant": cleaned merchant name (remove transaction codes, bank refs)
  - "confidence": float 0-1

Return ONLY the JSON array, no markdown fences, no explanation.
"""

PDF_EXTRACTION_SYSTEM = """You are a bank statement parser.
Extract ALL transactions from the text below. Return a JSON array where each element has:
  - "date": "YYYY-MM-DD"
  - "description": raw description from statement
  - "amount": positive number
  - "type": "debit" or "credit"
  - "balance": running balance if present, else null

Return ONLY the JSON array. No explanation, no markdown fences."""

CSV_NORMALISE_SYSTEM = """You are a bank CSV header normaliser.
Given these CSV column names: {columns}
Return a JSON object mapping each column to one of these standard names
(use null if no match):
  date, description, amount, debit_amount, credit_amount, balance, account, reference

Return ONLY the JSON object."""


# ─── CSV Ingestion ────────────────────────────────────────────────────────────


class CSVIngester:
    """Handles any CSV layout by using LLM to normalise column headers."""

    def __init__(self) -> None:
        self._llm = get_fast_llm()

    def _normalise_headers(self, columns: list[str]) -> dict[str, str]:
        """
        Ask LLM to map arbitrary CSV headers to standard names.

        The LLM returns ``{originalColumn: standardName}``. We invert it to
        ``{standardName: originalColumn}`` so downstream callers can do
        ``row.get(mapping["debit_amount"])``. Null/empty mappings are dropped.
        """
        prompt = CSV_NORMALISE_SYSTEM.format(columns=columns)
        response = self._llm.invoke(
            [
                SystemMessage(content=prompt),
                HumanMessage(content=f"Columns: {columns}"),
            ]
        )
        raw = response.content.strip()
        # Strip markdown fences if present
        raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("```")
        raw_map: dict[str, str | None] = json.loads(raw)
        return {std: orig for orig, std in raw_map.items() if std}

    def _parse_date(self, val: Any) -> date:
        if isinstance(val, date):
            return val
        for fmt in (
            "%d/%m/%Y",
            "%m/%d/%Y",
            "%Y-%m-%d",
            "%d-%m-%Y",
            "%d %b %Y",
            "%d %B %Y",
            "%b %d, %Y",
        ):
            try:
                return datetime.strptime(str(val).strip(), fmt).date()
            except ValueError:
                continue
        raise ValueError(f"Cannot parse date: {val}")

    def ingest(self, file_path: str | Path, account_name: str | None = None) -> TransactionBatch:
        path = Path(file_path)
        logger.info("Ingesting CSV: %s", path.name)

        df = pd.read_csv(path, encoding="utf-8", on_bad_lines="skip")
        df.columns = [c.strip() for c in df.columns]

        mapping = self._normalise_headers(list(df.columns))
        logger.debug("Header mapping: %s", mapping)

        transactions: list[Transaction] = []

        for _, row in df.iterrows():
            try:
                raw_date = row.get(mapping.get("date") or "")
                raw_desc = row.get(mapping.get("description") or "", "")
                raw_amount = row.get(mapping.get("amount") or "")
                raw_debit = row.get(mapping.get("debit_amount") or "")
                raw_credit = row.get(mapping.get("credit_amount") or "")

                # Determine amount and type
                if mapping.get("debit_amount") and mapping.get("credit_amount"):
                    debit_val = _to_float(raw_debit)
                    credit_val = _to_float(raw_credit)
                    if debit_val and debit_val > 0:
                        amount = debit_val
                        tx_type = TransactionType.DEBIT
                    elif credit_val and credit_val > 0:
                        amount = credit_val
                        tx_type = TransactionType.CREDIT
                    else:
                        continue
                else:
                    amount = _to_float(raw_amount)
                    if amount is None:
                        continue
                    # Negative = debit in many banks
                    tx_type = TransactionType.CREDIT if amount > 0 else TransactionType.DEBIT

                tx = Transaction(
                    id=str(uuid.uuid4()),
                    date=self._parse_date(raw_date),
                    description=str(raw_desc).strip(),
                    amount=abs(amount),
                    transaction_type=tx_type,
                    account=account_name or path.stem,
                    source_file=path.name,
                    raw_text=str(row.to_dict()),
                )
                transactions.append(tx)
            except Exception as exc:
                logger.warning("Skipping row due to error: %s", exc)
                continue

        logger.info("Parsed %d transactions from CSV", len(transactions))
        return TransactionBatch(
            transactions=transactions,
            source_name=path.name,
            source_type="csv",
            account_holder=account_name,
        )


# ─── PDF Ingestion ────────────────────────────────────────────────────────────


class PDFIngester:
    """Extracts transactions from bank statement PDFs using pdfplumber + LLM."""

    def __init__(self) -> None:
        self._llm = get_reasoning_llm()

    def _extract_text(self, pdf_path: Path) -> str:
        """Extract all text from PDF, page by page."""
        pages: list[str] = []
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page in pdf.pages:
                text = page.extract_text(x_tolerance=2, y_tolerance=2)
                if text:
                    pages.append(text)
        return "\n\n--- PAGE BREAK ---\n\n".join(pages)

    def _extract_text_from_bytes(self, pdf_bytes: bytes) -> str:
        pages: list[str] = []
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                text = page.extract_text(x_tolerance=2, y_tolerance=2)
                if text:
                    pages.append(text)
        return "\n\n--- PAGE BREAK ---\n\n".join(pages)

    def _llm_extract_transactions(self, text: str) -> list[dict[str, Any]]:
        """Use LLM to extract structured transactions from raw PDF text."""
        # Chunk text if very long (LLM context safety)
        chunks = _chunk_text(text, max_chars=12000)
        all_txns: list[dict[str, Any]] = []

        for chunk in chunks:
            response = self._llm.invoke(
                [
                    SystemMessage(content=PDF_EXTRACTION_SYSTEM),
                    HumanMessage(content=chunk),
                ]
            )
            raw = response.content.strip()
            raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("```")
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    all_txns.extend(parsed)
            except json.JSONDecodeError as exc:
                logger.warning("JSON parse failed for PDF chunk: %s", exc)

        return all_txns

    def ingest(
        self,
        file_path: str | Path | None = None,
        file_bytes: bytes | None = None,
        file_name: str = "statement.pdf",
        account_name: str | None = None,
    ) -> TransactionBatch:
        if file_path:
            path = Path(file_path)
            logger.info("Ingesting PDF: %s", path.name)
            text = self._extract_text(path)
            source_name = path.name
        elif file_bytes:
            logger.info("Ingesting PDF from bytes: %s", file_name)
            text = self._extract_text_from_bytes(file_bytes)
            source_name = file_name
        else:
            raise ValueError("Either file_path or file_bytes must be provided")

        raw_txns = self._llm_extract_transactions(text)
        transactions: list[Transaction] = []

        for raw in raw_txns:
            try:
                date_obj = _parse_date_flexible(raw.get("date", ""))
                tx = Transaction(
                    id=str(uuid.uuid4()),
                    date=date_obj,
                    description=str(raw.get("description", "")).strip(),
                    amount=abs(float(raw.get("amount", 0))),
                    transaction_type=TransactionType(raw.get("type", "debit").lower()),
                    account=account_name,
                    source_file=source_name,
                    raw_text=str(raw),
                )
                transactions.append(tx)
            except Exception as exc:
                logger.warning("Skipping PDF transaction: %s | raw=%s", exc, raw)

        logger.info("Extracted %d transactions from PDF", len(transactions))
        return TransactionBatch(
            transactions=transactions,
            source_name=source_name,
            source_type="pdf",
            account_holder=account_name,
        )


# ─── Gmail Ingestion ──────────────────────────────────────────────────────────


class GmailIngester:
    """
    Fetches bank statement attachments from Gmail via OAuth.

    Setup:
      1. Enable Gmail API in Google Cloud Console
      2. Download OAuth credentials.json
      3. First run opens browser for user authorisation
    """

    SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
    STATEMENT_KEYWORDS = [
        "statement",
        "bank statement",
        "credit card statement",
        "account statement",
        "e-statement",
        "monthly statement",
    ]

    def __init__(self) -> None:
        self._pdf_ingester = PDFIngester()
        self._csv_ingester = CSVIngester()
        self._creds_path = os.getenv("GMAIL_CREDENTIALS_PATH", "./credentials.json")
        self._token_path = os.getenv("GMAIL_TOKEN_PATH", "./data/gmail_token.json")

    def _get_service(self):
        """Build authenticated Gmail service with OAuth2."""
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build

        creds = None
        token_path = Path(self._token_path)

        if token_path.exists():
            creds = Credentials.from_authorized_user_file(str(token_path), self.SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not Path(self._creds_path).exists():
                    raise FileNotFoundError(
                        f"Gmail credentials not found at {self._creds_path}. "
                        "Download OAuth credentials.json from Google Cloud Console."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(self._creds_path, self.SCOPES)
                creds = flow.run_local_server(port=0)

            token_path.parent.mkdir(parents=True, exist_ok=True)
            token_path.write_text(creds.to_json())

        return build("gmail", "v1", credentials=creds)

    def _search_statement_emails(self, service, months_back: int = 3) -> list[str]:
        """Return message IDs of emails that likely contain statements."""
        query_parts = [f'"{kw}"' for kw in self.STATEMENT_KEYWORDS]
        query = f"({' OR '.join(query_parts)}) has:attachment"
        result = service.users().messages().list(userId="me", q=query, maxResults=50).execute()
        return [m["id"] for m in result.get("messages", [])]

    def _download_attachment(self, service, message_id: str) -> list[dict[str, Any]]:
        """Download all PDF/CSV attachments from a message."""
        import base64

        msg = service.users().messages().get(userId="me", id=message_id, format="full").execute()
        attachments = []

        def walk_parts(parts: list) -> None:
            for part in parts:
                filename = part.get("filename", "")
                mime = part.get("mimeType", "")
                if filename and (
                    filename.lower().endswith(".pdf") or filename.lower().endswith(".csv")
                ):
                    att_id = part["body"].get("attachmentId")
                    if att_id:
                        att = (
                            service.users()
                            .messages()
                            .attachments()
                            .get(userId="me", messageId=message_id, id=att_id)
                            .execute()
                        )
                        data = base64.urlsafe_b64decode(att["data"])
                        attachments.append(
                            {
                                "filename": filename,
                                "mime": mime,
                                "data": data,
                            }
                        )
                if "parts" in part:
                    walk_parts(part["parts"])

        payload = msg.get("payload", {})
        if "parts" in payload:
            walk_parts(payload["parts"])
        return attachments

    def ingest(self, months_back: int = 3) -> list[TransactionBatch]:
        """Fetch and parse all statement attachments from Gmail."""
        logger.info("Connecting to Gmail to fetch bank statements...")
        service = self._get_service()
        message_ids = self._search_statement_emails(service, months_back)
        logger.info("Found %d candidate emails", len(message_ids))

        batches: list[TransactionBatch] = []
        seen_hashes: set[str] = set()

        for msg_id in message_ids:
            attachments = self._download_attachment(service, msg_id)
            for att in attachments:
                # Dedup by file content hash
                file_hash = hashlib.md5(att["data"]).hexdigest()
                if file_hash in seen_hashes:
                    continue
                seen_hashes.add(file_hash)

                filename: str = att["filename"]
                logger.info("Processing Gmail attachment: %s", filename)

                try:
                    if filename.lower().endswith(".pdf"):
                        batch = self._pdf_ingester.ingest(
                            file_bytes=att["data"],
                            file_name=filename,
                        )
                    else:
                        # CSV — write temp file
                        tmp = Path(f"/tmp/{filename}")
                        tmp.write_bytes(att["data"])
                        batch = self._csv_ingester.ingest(tmp)
                        tmp.unlink(missing_ok=True)

                    batch.source_type = "gmail"
                    batches.append(batch)
                except Exception as exc:
                    logger.error("Failed to process %s: %s", filename, exc)

        logger.info("Gmail ingestion complete: %d batches", len(batches))
        return batches


# ─── LLM Categoriser ─────────────────────────────────────────────────────────


class TransactionCategoriser:
    """Bulk-categorises transactions using a fast LLM (Haiku)."""

    BATCH_SIZE = 50  # transactions per LLM call

    def __init__(self) -> None:
        # Each categorised tx serialises to ~80-100 output tokens; a 50-tx batch
        # needs ~5k tokens. The default 1024 truncates the JSON mid-string.
        self._llm = get_fast_llm(max_tokens=8192)

    def categorise(self, transactions: list[Transaction]) -> list[Transaction]:
        """Categorise all transactions in batches. Returns updated list."""
        logger.info("Categorising %d transactions...", len(transactions))
        result: list[Transaction] = []

        for i in range(0, len(transactions), self.BATCH_SIZE):
            batch = transactions[i : i + self.BATCH_SIZE]
            batch_input = [
                {
                    "id": t.id,
                    "description": t.description,
                    "amount": t.amount,
                    "type": t.transaction_type.value,
                }
                for t in batch
            ]
            try:
                response = self._llm.invoke(
                    [
                        SystemMessage(content=CATEGORISATION_SYSTEM),
                        HumanMessage(content=json.dumps(batch_input, ensure_ascii=False)),
                    ]
                )
                raw = response.content.strip()
                raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("```")
                categorised: list[dict[str, Any]] = json.loads(raw)

                cat_map = {c["id"]: c for c in categorised}
                for tx in batch:
                    info = cat_map.get(tx.id, {})
                    try:
                        tx.category = TransactionCategory(info.get("category", "other"))
                    except ValueError:
                        tx.category = TransactionCategory.OTHER
                    tx.subcategory = info.get("subcategory")
                    tx.merchant = info.get("merchant")
                    tx.confidence = float(info.get("confidence", 0.8))
                    result.append(tx)
            except Exception as exc:
                logger.error("Categorisation batch failed: %s", exc)
                result.extend(batch)  # keep uncategorised rather than drop

        logger.info("Categorisation complete")
        return result


# ─── Investment Goals CSV ─────────────────────────────────────────────────────


class InvestmentGoalsLoader:
    """Parses the investment_goals.csv file supplied by the user."""

    def __init__(self) -> None:
        self._llm = get_fast_llm()

    GOALS_NORMALISE_PROMPT = """Given these CSV columns for investment goals: {columns}
Map each to standard fields (use null if no match):
  name, goal_type, target_amount, current_amount, monthly_contribution,
  target_date, priority, notes

Valid goal_type values: {types}
Return ONLY a JSON object.""".format(
        columns="{columns}",
        types=[g.value for g in __import__("src.models", fromlist=["GoalType"]).GoalType],
    )

    def load(self, file_path: str | Path) -> list:
        from src.models import GoalType, InvestmentGoal

        path = Path(file_path)
        df = pd.read_csv(path)
        df.columns = [c.strip() for c in df.columns]

        # Normalise headers
        prompt = self.GOALS_NORMALISE_PROMPT.format(columns=list(df.columns))
        resp = self._llm.invoke(
            [
                SystemMessage(content=prompt),
                HumanMessage(content=str(list(df.columns))),
            ]
        )
        raw = resp.content.strip()
        raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("```")
        raw_map: dict[str, str | None] = json.loads(raw)
        # LLM returns {originalCol: standardName} — invert for row.get(mapping["name"]).
        mapping = {std: orig for orig, std in raw_map.items() if std}

        goals: list[InvestmentGoal] = []
        for _, row in df.iterrows():
            try:
                goal_type_raw = str(row.get(mapping.get("goal_type") or "", "other")).lower()
                try:
                    goal_type = GoalType(goal_type_raw)
                except ValueError:
                    goal_type = GoalType.OTHER

                target_date = None
                td_col = mapping.get("target_date")
                if td_col and row.get(td_col):
                    try:
                        target_date = _parse_date_flexible(str(row[td_col]))
                    except Exception:
                        pass

                goal = InvestmentGoal(
                    id=str(uuid.uuid4()),
                    name=str(row.get(mapping.get("name") or df.columns[0], f"Goal {_}")),
                    goal_type=goal_type,
                    target_amount=abs(float(row.get(mapping.get("target_amount") or 0, 0))),
                    current_amount=abs(float(row.get(mapping.get("current_amount") or 0, 0) or 0)),
                    monthly_contribution=abs(
                        float(row.get(mapping.get("monthly_contribution") or 0, 0) or 0)
                    ),
                    target_date=target_date,
                    priority=int(row.get(mapping.get("priority") or 1, 1) or 1),
                    notes=str(row.get(mapping.get("notes") or "", "") or ""),
                )
                goals.append(goal)
            except Exception as exc:
                logger.warning("Skipping goal row: %s", exc)

        logger.info("Loaded %d investment goals", len(goals))
        return goals


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _to_float(val: Any) -> float | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    try:
        cleaned = re.sub(r"[^\d.\-]", "", str(val))
        return float(cleaned) if cleaned else None
    except ValueError:
        return None


def _parse_date_flexible(val: str) -> date:
    for fmt in (
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%m/%d/%Y",
        "%d-%m-%Y",
        "%d %b %Y",
        "%d %B %Y",
        "%b %d, %Y",
        "%B %d, %Y",
    ):
        try:
            return datetime.strptime(val.strip(), fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date: {val}")


def _chunk_text(text: str, max_chars: int = 12000) -> list[str]:
    """Split text into chunks without cutting mid-line."""
    if len(text) <= max_chars:
        return [text]
    chunks, current = [], []
    current_len = 0
    for line in text.split("\n"):
        if current_len + len(line) > max_chars and current:
            chunks.append("\n".join(current))
            current, current_len = [], 0
        current.append(line)
        current_len += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks

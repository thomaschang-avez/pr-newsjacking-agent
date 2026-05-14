import os
from dataclasses import dataclass
from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials

load_dotenv()

GLEAN_API_TOKEN       = os.environ["GLEAN_API_TOKEN"]
GLEAN_INSTANCE        = os.environ["GLEAN_INSTANCE"]
GLEAN_SERVER_URL      = os.environ["GLEAN_SERVER_URL"]
SLACK_BOT_TOKEN       = os.environ["SLACK_BOT_TOKEN"]
SLACK_BOT_USER_ID     = os.environ["SLACK_BOT_USER_ID"]
GOOGLE_SHEETS_ID      = os.environ["GOOGLE_SHEETS_ID"]
GOOGLE_CREDENTIALS_PATH = os.environ["GOOGLE_CREDENTIALS_PATH"]

GLEAN_ACT_AS    = os.environ.get("GLEAN_ACT_AS", "you@yourcompany.com")
GEMINI_PROJECT  = os.environ.get("GEMINI_PROJECT", "your-gcp-project-id")
GEMINI_LOCATION = os.environ.get("GEMINI_LOCATION", "us-central1")

ERROR_CHANNEL   = os.environ.get("SLACK_ERROR_CHANNEL", "YOUR_ERROR_CHANNEL_ID")
TEST_CHANNEL    = os.environ.get("SLACK_TEST_CHANNEL", "YOUR_TEST_CHANNEL_ID")

# Blocked domains — substring match against article URLs (case-insensitive).
# Prevents PR wires, aggregators, financial data scrapers, and low-quality
# sites from reaching the scoring agents.
BLOCKED_DOMAINS = [
    "docs.google.com", "drive.google.com", "muckrack.com",
    "twitter.com", "x.com", "linkedin.com", "facebook.com",
    "instagram.com", "google.com", "news.yahoo.com", "bing.com",
    "reddit.com", "prnewswire.com", "businesswire.com",
    "globenewswire.com", "einpresswire.com", "einnews.com",
    "yahoo.com", "aol.com", "msn.com", "headtopics.com",
    "investing.com", "simplywall.st", "gurufocus.com",
    "coinmarketcap.com", "marketbeat.com", "tradingview.com",
    "markets.businessinsider.com", "insidermonkey.com",
    "naturalnews.com", "openpr.com",
]


@dataclass
class ClientConfig:
    name: str
    industry: str
    mr_client_news_id: str
    mr_industry_news_id: str
    mr_competitors_id: str | None
    output_channel_id: str
    mr_fourth_channel_id: str | None
    pitchbook_url: str
    faq_url: str | None
    strategy_url: str
    notes: str

    @property
    def muck_rack_channel_ids(self) -> list[str]:
        channels = [self.mr_client_news_id, self.mr_industry_news_id]
        if self.mr_competitors_id:
            channels.append(self.mr_competitors_id)
        if self.mr_fourth_channel_id:
            channels.append(self.mr_fourth_channel_id)
        return channels

    @property
    def has_faq(self) -> bool:
        return self.faq_url is not None


def _normalize_channel_id(raw: str) -> str | None:
    val = raw.strip()
    return None if not val or val.upper() == "N/A" else val


def _normalize_url(raw: str) -> str | None:
    val = raw.strip()
    return None if not val or val.upper() in ("N/A", "NO FAQ", "NONE") else val


def load_clients() -> list[ClientConfig]:
    """Load client configs from Google Sheets (n8n-config tab)."""
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    creds = Credentials.from_service_account_file(GOOGLE_CREDENTIALS_PATH, scopes=scopes)
    gc = gspread.authorize(creds)
    sheet = gc.open_by_key(GOOGLE_SHEETS_ID)
    worksheet = sheet.worksheet("n8n-config")
    rows = worksheet.get_all_records()

    clients = []
    for row in rows:
        name = row.get("Client Name", "").strip()
        if not name:
            continue
        clients.append(ClientConfig(
            name=name,
            industry=row.get("Industry", "").strip(),
            mr_client_news_id=row.get("MR Client News ID", "").strip(),
            mr_industry_news_id=row.get("MR Industry News ID", "").strip(),
            mr_competitors_id=_normalize_channel_id(row.get("MR Competitors ID", "")),
            output_channel_id=row.get("Output Channel ID", "").strip(),
            mr_fourth_channel_id=_normalize_channel_id(row.get("Core Scientific 4th Channel", "")),
            pitchbook_url=row.get("Pitchbook URL", "").strip(),
            faq_url=_normalize_url(row.get("FAQ URL", "")),
            strategy_url=row.get("Strategy URL", "").strip(),
            notes=row.get("Notes", "").strip(),
        ))

    return clients

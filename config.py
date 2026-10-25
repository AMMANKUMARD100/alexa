"""Server-only configuration. Never import secrets into frontend files."""
import os
from dataclasses import dataclass
from datetime import timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

BASE_DIR = Path(__file__).resolve().parent

def load_env(path=BASE_DIR / '.env'):
    if path.exists():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, value = line.split('=', 1)
            key, value = key.strip(), value.strip()
            if value[:1] in ('"', "'") and value[-1:] == value[:1]:
                value = value[1:-1]
            if key.isidentifier():
                os.environ.setdefault(key, value)

def get_zone(name):
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        if name in ('Asia/Kolkata', 'Asia/Calcutta'):
            return timezone(timedelta(hours=5, minutes=30), 'Asia/Kolkata')
        if name == 'UTC':
            return timezone.utc
        raise ValueError('Unknown timezone or missing timezone database. Install tzdata.') from None

@dataclass
class Settings:
    api_key: str = ''
    model: str = 'llama-3.1-8b-instant'
    timezone: str = 'Asia/Kolkata'
    port: int = 8765
    database: Path = BASE_DIR / 'data' / 'alexa_plus_v2.db'

    @classmethod
    def from_env(cls):
        load_env()
        result = cls(api_key=os.getenv('GROQ_API_KEY', '').strip(),
                     model=os.getenv('GROQ_MODEL', 'llama-3.1-8b-instant').strip(),
                     timezone=os.getenv('ASSISTANT_TIMEZONE', 'Asia/Kolkata').strip(),
                     port=int(os.getenv('ASSISTANT_PORT', '8765')),
                     database=Path(os.getenv('ASSISTANT_DB', str(cls.database))))
        get_zone(result.timezone)
        if not 1024 <= result.port <= 65535:
            raise ValueError('ASSISTANT_PORT must be between 1024 and 65535.')
        return result

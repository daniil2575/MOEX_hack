from src.news.channels import CHANNELS
from src.news.contracts import NewsItem
from src.news.parser import (
    FixturesParser,
    NewsParser,
    TelethonParser,
    parser_from_env,
)

__all__ = [
    "CHANNELS",
    "FixturesParser",
    "NewsItem",
    "NewsParser",
    "TelethonParser",
    "parser_from_env",
]

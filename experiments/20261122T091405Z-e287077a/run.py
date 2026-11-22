from pathlib import Path
from mail_search import cli
from mail_search import search

search.__path__.append(str(Path(__file__).resolve().parent))
raise SystemExit(cli.main())

import os

# ─── CREDENCIALES ──────────────────────────────────────────────────────────────
# Rellena estos valores o usa variables de entorno (recomendado)

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN",   "8486950785:AAHZZptDx8PdL9ZTrr_fIGNN7CwPl5wWe_M")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "7334433424")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "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")

# ─── CONFIGURACIÓN ─────────────────────────────────────────────────────────────

CHECK_INTERVAL_HOURS = 1  # Cada cuántas horas revisar noticias

# ─── PALABRAS CLAVE ────────────────────────────────────────────────────────────
# El bot filtra noticias que contengan al menos una de estas palabras

KEYWORDS = [
    # ── Forex ──────────────────────────────────────────────────────────────────
    "USD", "dollar", "dólar",
    "EUR", "euro",
    "GBP", "pound", "sterling",
    "JPY", "yen", "Bank of Japan", "BoJ",
    "Fed", "Federal Reserve", "FOMC",
    "ECB", "BCE", "European Central Bank",
    "Bank of England", "BoE",
    "interest rate", "tasa de interés", "rate decision", "rate hike", "rate cut",
    "inflation", "inflación", "CPI", "PCE", "PPI",
    "NFP", "nonfarm", "payroll", "employment", "unemployment", "jobs report",
    "GDP", "PIB", "economic growth", "PMI", "retail sales", "consumer confidence",

    # ── Metales preciosos ──────────────────────────────────────────────────────
    "gold", "oro", "XAU",
    "silver", "plata", "XAG",
    "precious metals", "metales preciosos", "safe haven", "refugio",

    # ── Cripto ─────────────────────────────────────────────────────────────────
    "Bitcoin", "BTC",
    "Ethereum", "ETH",
    "Solana", "SOL",
    "XRP", "Ripple",
    "crypto", "cryptocurrency", "criptomoneda",
    "blockchain", "SEC crypto", "crypto regulation", "ETF bitcoin", "ETF ethereum",

    # ── Geopolítica — países activos actualmente ───────────────────────────────
    "Iran", "Irán",
    "Russia", "Rusia",
    "Ukraine", "Ucrania",
    "China", "Taiwan", "Taiwán",
    "North Korea", "Corea del Norte",
    "Israel", "Palestine", "Palestina", "Gaza",
    "Saudi Arabia", "Arabia Saudita",
    "Pakistan", "Pakistán", "India",

    # ── Geopolítica — eventos genéricos (cualquier conflicto futuro) ───────────
    "war", "guerra",
    "conflict", "conflicto",
    "military", "militar", "airstrike", "ataque aéreo",
    "invasion", "invasión",
    "missile", "misil", "nuclear",
    "coup", "golpe de estado",
    "civil war", "guerra civil",
    "terrorism", "terrorismo", "terror attack",
    "assassination", "asesinato político",
    "regime change", "cambio de régimen",
    "protest", "uprising", "revolución",
    "geopolitical", "geopolítico", "geopolitics",
    "escalation", "escalada",
    "ceasefire", "alto al fuego", "peace talks",
    "embargo", "blockade", "bloqueo",

    # ── Sanciones y comercio ───────────────────────────────────────────────────
    "sanctions", "sanciones",
    "tariff", "arancel",
    "trade war", "guerra comercial",
    "export ban", "supply chain", "cadena de suministro",

    # ── Energía y commodities ──────────────────────────────────────────────────
    "OPEC", "OPEP", "oil", "petróleo", "crude",
    "natural gas", "gas natural", "energy crisis",
    "commodity", "commodities",

    # ── Crisis financieras sistémicas ──────────────────────────────────────────
    "recession", "recesión",
    "financial crisis", "crisis financiera",
    "market crash", "crash", "colapso",
    "bank failure", "quiebra bancaria", "bank run",
    "debt crisis", "crisis de deuda", "default", "sovereign debt",
    "IMF", "FMI", "contagion", "systemic risk",

    # ── Términos macro generales ───────────────────────────────────────────────
    "hawkish", "dovish",
    "risk-off", "risk-on",
    "volatility", "volatilidad", "VIX",
    "stagflation", "estanflación",
    "yield", "bond", "treasury", "bono",
    "dollar index", "DXY",
]

# ─── FUENTES RSS ───────────────────────────────────────────────────────────────
# Fuentes gratuitas de noticias financieras

RSS_FEEDS = [
    # ── Macro y Forex ──────────────────────────────────────────────────────────
    # Reuters
    "https://feeds.reuters.com/reuters/businessNews",
    "https://feeds.reuters.com/reuters/UKBusinessNews",
    # MarketWatch
    "https://feeds.marketwatch.com/marketwatch/realtimeheadlines",
    # Investing.com
    "https://www.investing.com/rss/news.rss",
    # Yahoo Finance
    "https://finance.yahoo.com/news/rssindex",
    # FXStreet (especializado en forex y macro)
    "https://www.fxstreet.com/rss/news",
    # ForexLive (noticias forex en tiempo real)
    "https://www.forexlive.com/feed/news",

    # ── Cripto ─────────────────────────────────────────────────────────────────
    # CoinDesk (el más importante de cripto)
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    # CoinTelegraph (cubre BTC, ETH, SOL, XRP)
    "https://cointelegraph.com/rss",
    # CryptoPanic (agrega noticias de múltiples fuentes cripto)
    "https://cryptopanic.com/news/rss/",
    # Decrypt (noticias cripto de calidad)
    "https://decrypt.co/feed",
    # The Block (análisis cripto profundo)
    "https://www.theblock.co/rss.xml",
]

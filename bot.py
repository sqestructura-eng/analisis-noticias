import feedparser
import requests
import schedule
import time
import logging
from datetime import datetime, timezone
from config import (
    TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, GROQ_API_KEY,
    RSS_FEEDS, CHECK_INTERVAL_HOURS
)

LOG_FILE = "bot_trading.log"

_log_formatter = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

_console_handler = logging.StreamHandler()
_console_handler.setFormatter(_log_formatter)

_file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
_file_handler.setFormatter(_log_formatter)

logging.basicConfig(level=logging.INFO, handlers=[_console_handler, _file_handler])
log = logging.getLogger(__name__)

# ─── ADMINISTRADOR ─────────────────────────────────────────────────────────────
# Reemplaza 0 con tu ID numérico de Telegram (lo obtienes con @userinfobot)
ADMIN_USER_ID = 8486950785

seen_links = set()

# ── Keywords de eventos críticos — siempre pasan el filtro ───────────────────
CRITICAL_KEYWORDS = [
    # Bancos centrales — decisiones confirmadas
    "rate decision", "rate hike", "rate cut", "interest rate decision",
    "fed decision", "fomc decision", "ecb decision", "boe decision",
    "bank of japan decision", "boj decision", "rate unchanged",
    "federal reserve raises", "federal reserve cuts",
    "fed raises", "fed cuts", "ecb raises", "ecb cuts",

    # Datos macro publicados — no forecasts
    "nonfarm payroll", "nfp report", "cpi report", "cpi data",
    "inflation data", "gdp report", "gdp data", "unemployment data",
    "jobs report", "retail sales data", "pce data",
    "beats expectations", "misses expectations",
    "higher than expected", "lower than expected",

    # Intervenciones y emergencias de mercado — todos los bancos centrales
    "currency intervention", "yentervention", "market circuit breaker",
    "boj intervenes", "boj intervention",           # Japan yen
    "fed intervenes", "fed intervention",           # EEUU dolar
    "ecb intervenes", "ecb intervention",           # Europa euro
    "boe intervenes", "boe intervention",           # UK libra
    "bank of japan intervenes", "bank of england intervenes",
    "federal reserve intervenes", "european central bank intervenes",
    "snb intervenes", "snb intervention",           # Suiza franco
    "pboc intervenes", "pboc intervention",         # China yuan (afecta risk-off)
    "bank failure", "bank collapse", "bank run",
    "exchange hack", "exchange collapse", "exchange bankrupt",
    "flash crash", "market crash",

    # Geopolítica que mueve mercados de verdad
    "war declared", "military strike confirmed",
    "nuclear threat", "nuclear strike",
    "oil embargo", "opec emergency", "opec+ emergency cut",
    "opec+ cut", "opec cut production",
    "sanctions imposed", "new sanctions",

    # Cripto regulación oficial
    "sec approves", "sec rejects", "sec approved", "sec rejected",
    "etf approved", "etf rejected", "bitcoin etf approved",
    "crypto ban", "crypto regulation signed", "regulation passed",
]

# ── Keywords de records — solo pasan si aparecen junto a los activos del trader
RECORD_KEYWORDS = [
    "all-time high", "record high", "record low",
    "historic high", "historic low",
]

# ── Activos que opera el trader ───────────────────────────────────────────────
ASSET_KEYWORDS = [
    "bitcoin", "btc",
    "ethereum", "eth",
    "solana",              # solo solana — sol es palabra comun en español
    "xrp", "ripple",
    "gold", "oro", "xau",
    "silver", "plata", "xag",
    "eur/usd", "eurusd",  # euro solo como par — euro aparece en demasiadas noticias
    "usd/jpy", "usdjpy", "yen", "jpy",
    "gbp/usd", "gbpusd", "pound", "sterling",
    "dollar index", "dxy",
]

def is_relevant(title: str, summary: str) -> bool:
    text = (title + " " + summary).lower()

    # Pasa si tiene keyword crítico — sin importar el activo
    if any(kw.lower() in text for kw in CRITICAL_KEYWORDS):
        return True

    # Pasa si tiene record keyword Y menciona uno de los activos del trader
    has_record = any(kw.lower() in text for kw in RECORD_KEYWORDS)
    has_asset = any(asset.lower() in text for asset in ASSET_KEYWORDS)
    if has_record and has_asset:
        return True

    return False


def send_telegram(text: str) -> bool:
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    max_length = 4000
    messages = [text] if len(text) <= max_length else [text[:max_length], text[max_length:]]

    success = True
    for msg in messages:
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": msg,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }
        try:
            r = requests.post(url, json=payload, timeout=10)
            r.raise_for_status()
        except Exception as e:
            log.error(f"Telegram error: {e}")
            success = False
    return success


def analyze_all_with_groq(news_list: list) -> str:
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }

    news_text = ""
    for i, news in enumerate(news_list, 1):
        news_text += f"{i}. {news['title']}\n"
        if news['summary'] != news['title']:
            news_text += f"   {news['summary'][:300]}\n"
        news_text += "\n"

    prompt = f"""Eres un analista senior de mercados especializado en swing trading de forex, metales y cripto.

El trader opera: USD/JPY, EUR/USD, GBP/USD, Oro (XAU), Plata (XAG), Bitcoin (BTC), Ethereum (ETH), Solana (SOL) y XRP.
El trader usa swing trading con timeframes Daily y H4. No opera intradía.
El trader no necesita movimientos grandes — con RR 2:1 un movimiento de 0.5% en forex ya es suficiente para ganar.

REGLAS ESTRICTAS DE URGENCIA:

URGENCIA ALTA — solo si hay AL MENOS UNO de estos eventos CONFIRMADOS:
1. Decision de tasa de interes publicada por Fed, BCE, BoJ o BoE
2. Dato macro publicado que supero o decepciono expectativas (CPI, NFP, GDP)
3. Intervencion cambiaria confirmada por un banco central
4. Ataque militar nuevo o escalada geopolitica con impacto en petroleo o safe havens
5. Colapso, hackeo o quiebra de exchange cripto importante
6. Aprobacion o rechazo oficial de ETF por la SEC
7. Record historico confirmado en alguno de los activos que opera el trader

URGENCIA MEDIA — eventos importantes pero sin accion inmediata:
- Declaraciones de bancos centrales sin decision de tasa
- Datos macro proximos a publicarse
- Escalada geopolitica sin ataques confirmados

URGENCIA BAJA — todo lo demas:
- Analisis y forecasts de analistas
- Noticias de empresas no relacionadas con los activos del trader
- Records de activos que el trader NO opera

IMPORTANTE: Es mucho mejor NO enviar alerta que enviar una falsa alarma que haga entrar en un trade equivocado.

REGLAS ADICIONALES CRITICAS:
- Noticias con palabras como "forecasting", "upcoming", "preview", "ahead of", "expected to", "scheduled", "next week", "this week" son siempre BAJO aunque mencionen CPI, NFP o GDP — son anticipaciones, no datos publicados.
- Advertencias y amenazas de bancos centrales o lideres politicos ("warns of intervention", "threatens tariffs", "signals rate cut") pueden ser MEDIO o ALTO porque el mercado reacciona a ellas antes del evento real.
- Declaraciones de Trump sobre aranceles, guerras comerciales o sanciones son MEDIO o ALTO si afectan directamente los activos del trader.

REGLAS DE CAUSA Y EFECTO POR ACTIVO — SIGUELAS SIEMPRE SIN EXCEPCION:

USD/JPY:
- BoJ interviene comprando yenes → yen SUBE → USD/JPY BAJA
- BoJ sube tasas o hawkish (sin intervenir) → yen SUBE → USD/JPY BAJA
- BoJ baja tasas o dovish → yen BAJA → USD/JPY SUBE
- Fed sube tasas o hawkish → dólar SUBE → USD/JPY SUBE
- Fed baja tasas o dovish → dólar BAJA → USD/JPY BAJA
- Datos macro EEUU fuertes (NFP supera, CPI alto) → dólar SUBE → USD/JPY SUBE
- Datos macro EEUU débiles (NFP decepciona, CPI bajo) → dólar BAJA → USD/JPY BAJA
- Datos macro Japón fuertes (PIB, inflación) → yen SUBE → USD/JPY BAJA
- Risk-off (guerra, crisis financiera, pánico) → yen SUBE como safe haven → USD/JPY BAJA
- Risk-on (mercados optimistas, bolsas subiendo) → yen BAJA → USD/JPY SUBE
- BoJ interviene Y Fed dovish simultáneamente → ambas fuerzas bajan USD/JPY → BAJA alta convicción
- BoJ hawkish Y datos EEUU débiles → USD/JPY BAJA con alta convicción

EUR/USD:
- BCE sube tasas o hawkish → euro SUBE → EUR/USD SUBE
- BCE baja tasas o dovish → euro BAJA → EUR/USD BAJA
- Fed sube tasas o hawkish → dólar SUBE → EUR/USD BAJA
- Fed baja tasas o dovish → dólar BAJA → EUR/USD SUBE
- Datos macro EEUU fuertes → dólar SUBE → EUR/USD BAJA
- Datos macro EEUU débiles → dólar BAJA → EUR/USD SUBE
- Datos macro eurozona fuertes (PIB, empleo, PMI) → euro SUBE → EUR/USD SUBE
- Datos macro eurozona débiles → euro BAJA → EUR/USD BAJA
- Crisis política en Europa (elecciones, fragmentación) → euro BAJA → EUR/USD BAJA
- Guerra en Europa o cerca de Europa → euro BAJA por riesgo geopolítico → EUR/USD BAJA
- Aranceles de EEUU a Europa → euro BAJA → EUR/USD BAJA
- Risk-off global → dólar SUBE como safe haven → EUR/USD BAJA
- Risk-on global → dólar BAJA → EUR/USD SUBE
- BCE hawkish Y Fed dovish simultáneamente → EUR/USD SUBE con alta convicción
- BCE dovish Y Fed hawkish simultáneamente → EUR/USD BAJA con alta convicción

GBP/USD:
- BoE sube tasas o hawkish → libra SUBE → GBP/USD SUBE
- BoE baja tasas o dovish → libra BAJA → GBP/USD BAJA
- Fed sube tasas o hawkish → dólar SUBE → GBP/USD BAJA
- Fed baja tasas o dovish → dólar BAJA → GBP/USD SUBE
- Datos macro UK fuertes (inflación, empleo, PIB) → libra SUBE → GBP/USD SUBE
- Datos macro UK débiles → libra BAJA → GBP/USD BAJA
- Datos macro EEUU fuertes → dólar SUBE → GBP/USD BAJA
- Datos macro EEUU débiles → dólar BAJA → GBP/USD SUBE
- Crisis política UK (gobierno, elecciones snap) → libra BAJA → GBP/USD BAJA
- Tensiones comerciales UK post-Brexit → libra BAJA → GBP/USD BAJA
- Risk-off global → dólar SUBE como safe haven → GBP/USD BAJA
- Risk-on global → libra tiende a recuperarse → GBP/USD SUBE
- BoE hawkish Y Fed dovish → GBP/USD SUBE con alta convicción
- BoE dovish Y Fed hawkish → GBP/USD BAJA con alta convicción

ORO (XAU/USD):
- Risk-off (guerra, crisis, pánico de mercado) → oro SUBE como principal safe haven
- Risk-on (economía fuerte, bolsas al alza) → oro BAJA o NEUTRAL
- Fed baja tasas o dovish → dólar BAJA y rendimientos bajan → oro SUBE
- Fed sube tasas o hawkish → dólar SUBE y rendimientos suben → oro BAJA
- Inflación alta sorpresa (CPI supera expectativas) → oro SUBE como cobertura inflacionaria
- Inflación baja sorpresa → presión a la baja en oro
- Dólar DXY se fortalece → oro BAJA (correlación inversa fuerte, siempre)
- Dólar DXY se debilita → oro SUBE (correlación inversa fuerte, siempre)
- Tensiones geopolíticas (guerra, amenaza nuclear, conflicto armado) → oro SUBE
- Compras masivas de bancos centrales → oro SUBE presión estructural
- Risk-off Y dólar débil simultáneamente → oro SUBE con muy alta convicción
- Risk-on Y dólar fuerte simultáneamente → oro BAJA con alta convicción
- Rendimientos de bonos EEUU suben → oro BAJA (el oro no paga intereses)
- Rendimientos de bonos EEUU bajan → oro SUBE

PLATA (XAG/USD):
- Sigue la dirección del oro pero con mayor volatilidad (movimientos más amplios)
- Demanda industrial fuerte (manufactura, energía solar, semiconductores) → plata SUBE adicional al oro
- Recesión o crisis industrial → plata BAJA más que el oro por pérdida de demanda industrial
- Risk-off suave → plata SUBE menos que el oro (el oro es mejor safe haven)
- Risk-off severo con crisis industrial → plata puede BAJAR mientras el oro sube
- Si oro sube por safe haven puro → plata sube pero menos
- Si oro sube por inflación Y hay demanda industrial → plata SUBE más que el oro
- Ratio oro/plata muy alto → plata relativamente barata, puede recuperar terreno

BITCOIN (BTC):
- SEC aprueba ETF de Bitcoin → BTC SUBE fuertemente
- SEC rechaza ETF de Bitcoin → BTC BAJA fuertemente
- Regulación cripto positiva (claridad legal) → BTC SUBE
- Regulación cripto negativa o ban en país importante → BTC BAJA fuertemente
- Risk-on (mercados globales optimistas) → BTC tiende a SUBIR
- Risk-off severo (crisis financiera, guerra) → BTC BAJA como activo de riesgo
- Fed dovish → más liquidez en el sistema → BTC SUBE
- Fed hawkish → menos liquidez → BTC BAJA
- Dólar se debilita fuertemente → inversores buscan alternativas → BTC SUBE
- Exchange importante colapsa o es hackeado → BTC BAJA fuertemente por pánico
- Adopción institucional confirmada (empresa grande compra BTC) → BTC SUBE
- Halving reciente → reducción de oferta → presión alcista de largo plazo
- Ballenas vendiendo masivamente (on-chain data) → BTC BAJA
- Dominancia de BTC subiendo → altcoins bajan, BTC se fortalece relativo

ETHEREUM (ETH):
- Sigue dirección de BTC en la mayoría de casos macro
- Aprobación de ETF de ETH por SEC → ETH SUBE fuertemente independiente de BTC
- Actualizaciones de red exitosas (upgrades) → ETH SUBE adicional
- Aumento de actividad DeFi o NFT en la red → ETH SUBE por demanda de gas
- Hackeos grandes de protocolos DeFi en Ethereum → ETH BAJA por pérdida de confianza
- Si BTC sube → ETH generalmente SUBE, a veces más, a veces menos
- Si BTC baja fuerte → ETH tiende a bajar más que BTC (más beta bajista)
- Competencia fuerte de otras L1 (Solana, Avalanche) → presión relativa sobre ETH

SOLANA (SOL):
- Sigue tendencia general del mercado cripto liderada por BTC
- Outages o problemas de red de Solana → SOL BAJA independiente del mercado general
- Adopción de nuevos proyectos importantes en Solana → SOL SUBE
- Risk-on en cripto → SOL tiende a subir MÁS que BTC (mayor beta alcista)
- Risk-off en cripto → SOL tiende a bajar MÁS que BTC (mayor beta bajista)
- Si BTC sube fuerte → SOL puede subir el doble o triple porcentualmente
- Si BTC baja fuerte → SOL puede bajar el doble o triple porcentualmente
- Competencia con Ethereum resuelta favorablemente → SOL SUBE

XRP:
- Resolución legal favorable con SEC → XRP SUBE fuertemente
- Resolución legal desfavorable con SEC → XRP BAJA fuertemente
- Adopción de Ripple por bancos o instituciones financieras → XRP SUBE
- Noticias de SWIFT o sistemas de pago alternativos que compiten con Ripple → XRP BAJA
- Nuevas asociaciones de Ripple con bancos centrales o gobiernos → XRP SUBE
- Risk-off general en cripto → XRP BAJA
- Risk-on en cripto → XRP SUBE pero generalmente menos que SOL o ETH
- Si BTC sube → XRP puede seguir pero correlación es menor que ETH o SOL
- Regulación de stablecoins o pagos cripto que favorece a Ripple → XRP SUBE

CASOS ADICIONALES Y FUERZAS CONTRADICTORIAS POR ACTIVO:

USD/JPY — casos especiales:
- BoJ hawkish PERO datos EEUU muy fuertes → fuerzas opuestas → analiza cuál es más reciente → probable NEUTRAL o ligero movimiento
- Risk-off severo (guerra nuclear, colapso financiero) → yen SUBE tan fuerte que domina cualquier otra fuerza → USD/JPY BAJA alta convicción
- Japón en recesión confirmada → yen pierde atractivo como safe haven temporalmente → efecto reducido del risk-off en USD/JPY
- BoJ sube tasas sorpresivamente → yen SUBE bruscamente → USD/JPY BAJA fuerte e inmediata
- Intervención verbal del BoJ sin acción real → efecto temporal → USD/JPY puede recuperarse rápido
- BoJ mantiene tasas negativas cuando el mercado esperaba subida → yen BAJA fuertemente → USD/JPY SUBE
- Japón anuncia fin definitivo de tasas negativas (NIRP) → yen SUBE fuertemente → USD/JPY BAJA
- Diferencial de tasas EEUU-Japón muy alto → carry trade activo → yen débil → USD/JPY SUBE
- Diferencial de tasas EEUU-Japón se cierra → carry trade se deshace → yen SUBE → USD/JPY BAJA
- Datos de balanza comercial Japón con déficit por petróleo caro → yen BAJA → USD/JPY SUBE
- Tokio CPI supera expectativas → señal de que BoJ subirá tasas → yen SUBE → USD/JPY BAJA
- Tokio CPI decepciona → BoJ seguirá dovish → yen BAJA → USD/JPY SUBE
- Tankan (encuesta empresarial Japón) positivo → economía fuerte → yen SUBE → USD/JPY BAJA
- Tankan negativo → economía débil → yen BAJA → USD/JPY SUBE

EUR/USD — casos especiales:
- BCE hawkish PERO datos eurozona débiles → mercado duda sostenibilidad → EUR/USD NEUTRAL o BAJA
- BCE sube tasas pero señala que es la última subida → euro BAJA después del anuncio → EUR/USD BAJA
- BCE hace pausa en subidas con inflación aún alta → mercado lo interpreta como error → euro BAJA
- BCE baja tasas sorpresivamente → euro BAJA fuerte → EUR/USD BAJA inmediata
- Spread BTP-Bund Italia sobre 250 puntos → crisis de deuda inminente → euro BAJA → EUR/USD BAJA
- BCE activa TPI (herramienta anti-fragmentación) → estabiliza spreads → euro SUBE → EUR/USD SUBE
- Draghi effect o declaración contundente de BCE de defender el euro → euro SUBE → EUR/USD SUBE
- Alemania anuncia estímulo fiscal masivo → economía europea mejora → euro SUBE → EUR/USD SUBE
- Elecciones en Alemania o Francia con resultado incierto → euro BAJA incluso con BCE hawkish
- Crisis de deuda en país periférico (Italia, Grecia, España) → euro BAJA fuertemente
- EEUU entra en recesión → dólar BAJA → EUR/USD SUBE aunque Europa también esté débil
- Datos de empleo eurozona muy fuertes con BCE dovish → fuerzas contradictorias → NEUTRAL
- PIB eurozona sorprende al alza dos trimestres seguidos → euro SUBE → EUR/USD SUBE
- Reunión del BCE sin cambios pero con tono más hawkish de lo esperado → euro SUBE → EUR/USD SUBE
- Reunión del BCE sin cambios pero con tono más dovish de lo esperado → euro BAJA → EUR/USD BAJA
- Declaración de Lagarde (presidenta BCE) hawkish sorpresiva → euro SUBE → EUR/USD SUBE
- Declaración de Lagarde dovish sorpresiva → euro BAJA → EUR/USD BAJA
- Actas del BCE (minutes) más hawkish de lo esperado → euro SUBE → EUR/USD SUBE

GBP/USD — casos especiales:
- BoE hawkish PERO economía UK en recesión → mercado duda sostenibilidad → GBP/USD NEUTRAL o BAJA
- BoE sube tasas sorpresivamente → libra SUBE bruscamente → GBP/USD SUBE fuerte
- BoE baja tasas sorpresivamente → libra BAJA bruscamente → GBP/USD BAJA fuerte
- BoE hace pausa pero señala más subidas → libra SUBE moderado → GBP/USD SUBE
- BoE hace pausa y señala posibles bajadas → libra BAJA → GBP/USD BAJA
- Declaración del gobernador BoE Bailey hawkish sorpresiva → libra SUBE → GBP/USD SUBE
- Declaración del gobernador BoE Bailey dovish → libra BAJA → GBP/USD BAJA
- Actas del BoE más hawkish de lo esperado → libra SUBE → GBP/USD SUBE
- Actas del BoE más dovish de lo esperado → libra BAJA → GBP/USD BAJA
- Datos de inflación UK mucho más altos → BoE forzado a subir más → GBP/USD SUBE
- Datos de inflación UK cayendo rápido → BoE puede bajar antes → GBP/USD BAJA
- Elecciones generales UK con resultado incierto → libra BAJA por incertidumbre
- Tensiones renovadas con UE por acuerdos post-Brexit → libra BAJA
- Crisis inmobiliaria UK → libra BAJA por impacto en economía real
- UK firma acuerdos comerciales importantes (EEUU, Asia) → libra SUBE
- Datos de ventas minoristas UK fuertes → libra SUBE → GBP/USD SUBE
- Datos de producción industrial UK débiles → libra BAJA → GBP/USD BAJA
- Balanza de pagos UK con déficit creciente → libra BAJA estructuralmente → GBP/USD BAJA

ORO — casos especiales:
- Risk-off PERO dólar también sube (ambos son safe haven) → oro puede ser NEUTRAL o subir levemente porque el dólar compite
- Inflación baja inesperadamente PERO hay guerra → risk-off gana sobre el efecto de menor inflación → oro SUBE
- Fed sube tasas agresivamente en medio de guerra → dólar sube Y hay risk-off → fuerzas opuestas → el grado del conflicto determina cuál gana
- Bancos centrales de países emergentes venden oro masivamente → oro BAJA presión adicional
- Dólar muy débil por largo tiempo → oro SUBE estructuralmente como reserva de valor
- Deflación o crisis bancaria sistémica → oro SUBE como único activo sin riesgo de contraparte
- Minería de oro con problemas de suministro → oro SUBE por escasez relativa
- Rendimientos reales de bonos EEUU negativos → oro SUBE porque el costo de oportunidad desaparece
- Rendimientos reales positivos muy altos → oro BAJA porque los bonos compiten como safe haven

PLATA — casos especiales:
- Transición energética acelerándose (solar, baterías) → plata SUBE por demanda industrial estructural
- Crisis industrial global (recesión manufacturera) → plata BAJA más que el oro por pérdida de demanda
- Oro sube por geopolítica pura → plata sube menos porque no tiene el mismo estatus de safe haven
- Escasez de suministro de plata confirmada → plata SUBE independiente del oro
- Ratio oro/plata mayor a 80 → plata históricamente barata relativa al oro, mayor probabilidad de recuperación
- China reactiva industria manufacturera → plata SUBE por demanda industrial
- China desacelera industria → plata BAJA adicional al efecto del oro

BITCOIN — casos especiales:
- Risk-off moderado (corrección de bolsas, no crisis total) → BTC puede BAJAR pero menos que altcoins
- Risk-off severo (colapso financiero, guerra mundial) → BTC BAJA fuerte, los inversores prefieren dólar y oro
- Correlación BTC con nasdaq alta en ese período → si nasdaq cae, BTC cae junto
- Correlación BTC con nasdaq baja → BTC puede subir aunque las acciones caigan
- Gobiernos importantes anuncian reservas estratégicas de BTC → BTC SUBE fuertemente
- Mineros de BTC vendiendo masivamente → presión bajista adicional
- Dominancia de BTC en máximos → altcoins débiles, BTC relativamente fuerte
- Dominancia de BTC cayendo → altcoins ganando terreno, BTC puede estar en distribución
- Liquidez global aumentando (M2 mundial subiendo) → BTC SUBE con retraso de semanas
- Liquidez global cayendo → BTC BAJA con retraso de semanas
- ETF de BTC con flujos positivos masivos → presión compradora real → BTC SUBE
- ETF de BTC con flujos negativos masivos → presión vendedora real → BTC BAJA

ETHEREUM — casos especiales:
- ETH flippening (ETH supera BTC en capitalización) → momento histórico → ETH SUBE con fuerza propia
- Gas fees muy altas en Ethereum → usuarios migran a L2 o competidores → ETH BAJA relativo
- Nueva L2 importante lanzada en Ethereum → más actividad en el ecosistema → ETH SUBE
- Competidor L1 (Solana, Avalanche) supera a Ethereum en volumen → presión bajista en ETH
- Reducción en emisión de ETH por staking alto → menos oferta → ETH SUBE presión estructural
- Fondos institucionales rotan de BTC a ETH → ETH SUBE independiente de BTC
- Regulación que clasifica ETH como security → ETH BAJA fuertemente
- Regulación que confirma ETH como commodity → ETH SUBE por certeza legal

SOLANA — casos especiales:
- Outage de red de Solana → SOL BAJA independiente del mercado, puede ser fuerte si es frecuente
- Solana supera a Ethereum en transacciones diarias → SOL SUBE por narrativa de adopción
- Proyecto DeFi o NFT grande migra de Ethereum a Solana → SOL SUBE, ETH BAJA relativo
- Proyecto importante abandona Solana por outages → SOL BAJA
- Firedancer (cliente alternativo de Solana) lanzado con éxito → SOL SUBE por mejora de red
- Venture capital importante invierte en ecosistema Solana → SOL SUBE
- BTC en máximos históricos sostenidos → altcoins como SOL eventualmente SUBEN más (altseason)
- BTC corrigiendo → SOL tiende a caer el doble o triple del porcentaje de BTC

XRP — casos especiales:
- Caso SEC vs Ripple resuelto definitivamente a favor → XRP SUBE fuertemente y sostenido
- Regulación clara de pagos cripto en EEUU que incluye a XRP → XRP SUBE
- Banco central importante adopta CBDC basada en tecnología Ripple → XRP SUBE
- SWIFT lanza mejoras que hacen irrelevante a Ripple → XRP BAJA estructuralmente
- Ripple pierde socios bancarios importantes → XRP BAJA
- Ripple firma acuerdo con banco central de país importante → XRP SUBE
- XRP deslistado de exchanges importantes en EEUU → XRP BAJA fuertemente
- XRP relisteado en exchanges de EEUU tras victoria legal → XRP SUBE fuertemente

SITUACIONES SIN EEUU COMO PROTAGONISTA:

USD/JPY sin EEUU:
- Terremoto o desastre natural en Japón → yen BAJA inicialmente por daño económico → USD/JPY SUBE
- Japón entra en recesión técnica (dos trimestres negativos) → yen BAJA → USD/JPY SUBE
- Inflación en Japón supera meta del BoJ sostenidamente → BoJ forzado a subir tasas → yen SUBE → USD/JPY BAJA
- Japón anuncia estímulo fiscal masivo → yen puede BAJAR por mayor gasto → USD/JPY SUBE
- Crisis política en Japón (renuncia de primer ministro) → yen BAJA por incertidumbre → USD/JPY SUBE
- Japón reporta superávit comercial fuerte → yen SUBE por flujos → USD/JPY BAJA
- Japón reporta déficit comercial por importaciones de energía → yen BAJA → USD/JPY SUBE
- China desacelera → impacto negativo en Japón por comercio → yen BAJA relativo → USD/JPY SUBE
- China reactiva economía → beneficio para Japón → yen SUBE relativo → USD/JPY BAJA

EUR/USD sin EEUU:
- Alemania entra en recesión (motor económico de Europa) → euro BAJA fuertemente → EUR/USD BAJA
- Francia crisis política (gobierno cae, elecciones snap) → euro BAJA → EUR/USD BAJA
- Italia deuda en crisis (spread BTP-Bund se dispara) → euro BAJA → EUR/USD BAJA
- Grecia u otro país periférico con problemas de deuda → euro BAJA → EUR/USD BAJA
- Inflación eurozona sorpresivamente alta → BCE forzado a ser más hawkish → euro SUBE → EUR/USD SUBE
- Inflación eurozona cae más rápido de lo esperado → BCE puede bajar tasas antes → euro BAJA → EUR/USD BAJA
- PMI manufacturero eurozona en contracción sostenida → euro BAJA → EUR/USD BAJA
- PMI eurozona sorprende al alza → euro SUBE → EUR/USD SUBE
- Guerra en Europa (conflicto armado en territorio europeo) → euro BAJA fuertemente → EUR/USD BAJA
- Acuerdo de paz en conflicto europeo → euro SUBE por reducción de riesgo → EUR/USD SUBE
- Elecciones europeas con resultado favorable a partidos pro-UE → euro SUBE → EUR/USD SUBE
- Elecciones con auge de partidos euroescépticos → euro BAJA → EUR/USD BAJA
- BCE interviene en mercado de bonos para controlar spreads (OMT) → euro SUBE → EUR/USD SUBE
- Crisis energética en Europa (corte de gas, petróleo caro) → euro BAJA por daño económico → EUR/USD BAJA
- Europa logra independencia energética (renovables, LNG) → euro SUBE estructuralmente → EUR/USD SUBE
- China y Europa profundizan relaciones comerciales → euro SUBE por flujos → EUR/USD SUBE
- Sanciones europeas a Rusia con represalias → euro BAJA por daño económico → EUR/USD BAJA

GBP/USD sin EEUU:
- Inflación UK persistentemente alta → BoE forzado a subir más tasas → libra SUBE → GBP/USD SUBE
- Inflación UK cae rápido → BoE baja tasas antes → libra BAJA → GBP/USD BAJA
- PIB UK sorprende al alza → libra SUBE → GBP/USD SUBE
- PIB UK en recesión técnica → libra BAJA → GBP/USD BAJA
- UK firma acuerdo comercial importante con EEUU → libra SUBE → GBP/USD SUBE
- UK firma acuerdo con UE mejorando relaciones post-Brexit → libra SUBE → GBP/USD SUBE
- Tensiones UK-UE se agudizan (nuevo conflicto post-Brexit) → libra BAJA → GBP/USD BAJA
- Crisis inmobiliaria UK (hipotecas impagables, caída de precios) → libra BAJA → GBP/USD BAJA
- Elecciones generales UK con resultado incierto → libra BAJA por incertidumbre → GBP/USD BAJA
- Gobierno UK anuncia recorte fiscal masivo (mini-budget) → libra BAJA por riesgo fiscal → GBP/USD BAJA
- Gobierno UK anuncia plan fiscal creíble → libra SUBE → GBP/USD SUBE
- Huelgas masivas en UK (sector público, transporte) → libra BAJA por daño económico → GBP/USD BAJA
- Escocia busca nuevo referéndum de independencia → libra BAJA por riesgo de fragmentación → GBP/USD BAJA

ORO sin EEUU:
- China aumenta reservas de oro → oro SUBE por demanda de banco central
- India aumenta importaciones de oro (festival Diwali, temporada de bodas) → oro SUBE estacionalmente
- Bancos centrales de mercados emergentes diversifican de dólar a oro → oro SUBE estructuralmente
- Conflicto en Oriente Medio (Israel, Irán, Arabia Saudita) → oro SUBE como safe haven
- Tensión en estrecho de Ormuz (petróleo) → oro SUBE por risk-off energético
- Crisis bancaria en Europa (banco sistémico en problemas) → oro SUBE por desconfianza sistémica
- Japón en crisis fiscal (deuda/PIB insostenible) → oro SUBE por desconfianza en monedas fiduciarias
- China devalúa el yuan → oro SUBE en yuan → presión alcista global en oro
- Acuerdo de paz en conflicto importante → oro BAJA por reducción de risk-off

PLATA sin EEUU:
- China reactiva plan de estímulo industrial → plata SUBE por demanda industrial futura
- China desacelera manufacturera → plata BAJA por caída de demanda industrial
- Europa acelera transición energética (paneles solares) → plata SUBE por demanda de componentes
- Japón aumenta producción de electrónica → plata SUBE por demanda industrial
- Déficit de suministro global de plata confirmado por Silver Institute → plata SUBE
- Nuevas tecnologías reducen uso de plata en industria → plata BAJA estructuralmente

BTC sin EEUU:
- El Salvador u otro país adopta BTC como moneda legal → BTC SUBE por narrativa de adopción
- País importante prohíbe BTC (China renovó prohibición) → BTC BAJA por pérdida de mercado
- Mineros de BTC en China o Rusia bajo presión regulatoria → BTC BAJA por menor hashrate
- Europa regula BTC positivamente (MiCA favorable) → BTC SUBE por claridad legal
- Europa regula BTC negativamente → BTC BAJA por pérdida de mercado
- Banco central importante (no EEUU) anuncia reserva de BTC → BTC SUBE
- Crisis de deuda soberana en país emergente → BTC SUBE como alternativa a moneda local devaluada

XRP sin EEUU:
- Banco central de Japón, Europa o Asia adopta tecnología Ripple → XRP SUBE
- BIS (Banco de Pagos Internacionales) respalda tecnología de pagos de Ripple → XRP SUBE
- País importante en Asia o Medio Oriente firma con Ripple para pagos internacionales → XRP SUBE
- Regulación europea de criptoactivos (MiCA) favorable a XRP → XRP SUBE
- Japón (uno de los mayores mercados de XRP) cambia regulación → XRP muy sensible a esto

CORRELACIONES CRUZADAS COMPLETAS:
- Dólar fuerte → oro BAJA, BTC presión bajista, EUR/USD BAJA, GBP/USD BAJA, USD/JPY SUBE
- Dólar débil → oro SUBE, BTC presión alcista, EUR/USD SUBE, GBP/USD SUBE, USD/JPY BAJA
- Risk-off global → USD/JPY BAJA (yen safe haven), oro SUBE, BTC BAJA, EUR/USD BAJA, GBP/USD BAJA
- Risk-on global → USD/JPY SUBE, oro NEUTRAL o BAJA, BTC SUBE, EUR/USD SUBE relativo
- Inflación alta sorpresa EEUU → oro SUBE, Fed hawkish → dólar SUBE → BTC BAJA, EUR/USD BAJA
- Inflación alta en Europa sin EEUU → BCE hawkish → euro SUBE → EUR/USD SUBE, GBP/USD puede subir relativo
- Recesión EEUU → Fed dovish → dólar BAJA → oro SUBE, EUR/USD SUBE, BTC cae primero luego sube
- Recesión Europa → BCE dovish → euro BAJA → EUR/USD BAJA, GBP/USD puede subir relativo al euro
- Guerra en Europa → EUR/USD BAJA, GBP/USD BAJA, oro SUBE, USD/JPY BAJA (yen safe haven)
- Guerra en Oriente Medio → oro SUBE, petróleo SUBE, EUR/USD BAJA por energía, plata SUBE relativo
- Conflicto en Asia (China, Taiwán, Corea) → USD/JPY BAJA (yen safe haven), oro SUBE, BTC BAJA
- Crisis bancaria global → oro SUBE, BTC puede subir como alternativa, EUR/USD BAJA si es en Europa
- China en crisis → commodities BAJAN, plata BAJA por demanda industrial, AUD y JPY afectados
- China reactiva → commodities SUBEN, plata SUBE, mercados emergentes SUBEN

JERARQUÍA DE FUERZAS CUANDO HAY CONTRADICCIÓN:
1. Decisión confirmada de banco central (la más poderosa, mueve el mercado de inmediato)
2. Dato macro publicado que supera o decepciona expectativas significativamente
3. Escalada geopolítica con ataques reales o intervención militar confirmada
4. Intervención cambiaria confirmada por banco central
5. Declaración sorpresiva de funcionario de alto rango (presidente Fed, BCE, BoJ)
6. Declaración de Trump o líder político sobre aranceles o sanciones
7. Tendencia de mercado previa (la menos poderosa, puede ser revertida por cualquiera de las anteriores)

Si hay fuerzas de igual jerarquía en direcciones opuestas → NEUTRAL con explicación clara de ambas.
NUNCA inviertas la causalidad. NUNCA asumas dirección sin fundamento en las noticias recibidas.

NOTICIAS DETECTADAS:
{news_text}

Responde EXACTAMENTE con este formato:

RESUMEN DE MERCADO

NOTICIAS ANALIZADAS: {len(news_list)}
[lista SOLO las noticias de nivel ALTO y MEDIO con bullet • y su nivel. Las noticias BAJO no las incluyas en el resumen, solo cuéntalas al final como: "X noticias de bajo impacto omitidas."]

PREDICCION POR ACTIVO

Forex:
• USD/JPY: [sube/baja/neutral] — [razon concreta]
  Por que: [1-2 oraciones con logica real]

• EUR/USD: [sube/baja/neutral] — [razon concreta]
  Por que: [1-2 oraciones]

• GBP/USD: [sube/baja/neutral] — [razon concreta]
  Por que: [1-2 oraciones]

Metales:
• Oro XAU: [sube/baja/neutral] — [razon concreta]
  Por que: [1-2 oraciones]

• Plata XAG: [sube/baja/neutral] — [razon concreta]
  Por que: [1-2 oraciones]

Cripto:
• BTC: [sube/baja/neutral] — [razon concreta]
  Por que: [1-2 oraciones]

• ETH: [sube/baja/neutral] — [razon concreta]
  Por que: [1-2 oraciones]

• SOL: [sube/baja/neutral] — [razon concreta]
  Por que: [1-2 oraciones]

• XRP: [sube/baja/neutral] — [razon concreta]
  Por que: [1-2 oraciones]

DICTAMEN GENERAL
[2-3 oraciones. Si no hay noticias de alto impacto real decirlo explicitamente.]

URGENCIA: [Alta/Media/Baja]
Criterio: [Una linea explicando exactamente por que se asigna esa urgencia]

ACCION SUGERIDA
[Si Alta: 2-3 lineas concretas para swing trading en Daily o H4.]
[Si Media o Baja: "Sin eventos criticos. Mantener plan de trading. No operar por esta alerta."]"""

    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 2000,
        "temperature": 0.1,
    }

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=60)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        log.error(f"Groq API error: {e}")
        return None


def fetch_and_process():
    log.info("Revisando noticias...")
    relevant_news = []

    for feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:15]:
                link = getattr(entry, "link", "")
                title = getattr(entry, "title", "")
                summary = getattr(entry, "summary", title)

                if link in seen_links:
                    continue
                seen_links.add(link)

                if not is_relevant(title, summary):
                    continue

                relevant_news.append({
                    "title": title,
                    "summary": summary,
                    "link": link
                })
                log.info(f"Noticia critica detectada: {title[:70]}...")

        except Exception as e:
            log.error(f"Error procesando feed {feed_url}: {e}")

    if not relevant_news:
        log.info("Sin noticias criticas esta hora. Mercado tranquilo.")
        return

    log.info(f"Analizando {len(relevant_news)} noticias con Groq...")
    analysis = analyze_all_with_groq(relevant_news)

    if analysis:
        analysis_lower = analysis.lower()
        is_high_impact = (
            "urgencia: alta" in analysis_lower or
            "urgencia alta" in analysis_lower or
            "urgency: high" in analysis_lower
        )

        if is_high_impact:
            timestamp = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
            header = f"🚨 *ALERTA REAL — {timestamp}*\n\n"
            message = header + analysis
            send_telegram(message)
            log.info("Alerta ALTA enviada a Telegram.")
            # ── Registro silencioso por noticia (solo archivo) ──────────────────
            for item in relevant_news:
                log.info(f"[DICTAMEN] Impacto ALTO - Enviada | {item['title'][:120]}")
        else:
            log.info("Noticias detectadas pero urgencia Media/Baja. Sin notificacion.")
            # ── Registro silencioso por noticia (solo archivo) ──────────────────
            for item in relevant_news:
                log.info(f"[DICTAMEN] Impacto BAJO - Descartada | {item['title'][:120]}")
    else:
        log.error("Error al generar analisis con Groq.")


def send_startup_message():
    msg = (
        "🤖 *Bot de Trading v3 — Activo*\n\n"
        "Activos monitoreados:\n"
        "USD/JPY • EUR/USD • GBP/USD\n"
        "Oro • Plata • BTC • ETH • SOL • XRP\n\n"
        f"⏱ Revisión cada {CHECK_INTERVAL_HOURS} hora(s)\n\n"
        "🔴 *Solo alertas de impacto REAL:*\n"
        "• Decisiones de tasas (Fed, BCE, BoJ, BoE)\n"
        "• Datos macro publicados (CPI, NFP, GDP)\n"
        "• Intervenciones cambiarias confirmadas\n"
        "• Escaladas geopolíticas reales\n"
        "• Records históricos en tus activos específicos\n"
        "• Colapsos de exchanges cripto\n\n"
        "✅ Sin eventos críticos = sin mensaje.\n"
        "El silencio significa que el mercado está tranquilo."
    )
    send_telegram(msg)


# ─── COMANDOS DE ADMINISTRACIÓN ────────────────────────────────────────────────

def _get_telegram_updates(offset: int = None) -> list:
    """Obtiene los updates pendientes del bot vía long polling corto."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    params = {"timeout": 5, "allowed_updates": ["message"]}
    if offset is not None:
        params["offset"] = offset
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        return r.json().get("result", [])
    except Exception as e:
        log.error(f"Error obteniendo updates: {e}")
        return []


def _send_document_telegram(chat_id: str, filepath: str, caption: str = "") -> bool:
    """Envía un archivo como documento a un chat de Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument"
    try:
        with open(filepath, "rb") as f:
            r = requests.post(
                url,
                data={"chat_id": chat_id, "caption": caption},
                files={"document": f},
                timeout=30,
            )
        r.raise_for_status()
        return True
    except Exception as e:
        log.error(f"Error enviando documento: {e}")
        return False


def _send_text_telegram(chat_id: str, text: str) -> bool:
    """Envía un mensaje de texto simple a un chat específico."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(
            url,
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
        r.raise_for_status()
        return True
    except Exception as e:
        log.error(f"Error enviando texto: {e}")
        return False


def handle_admin_commands(last_update_id: int) -> int:
    """
    Revisa updates pendientes y responde a /logs y /status si el usuario
    es el administrador. Devuelve el nuevo offset para el próximo ciclo.
    """
    updates = _get_telegram_updates(offset=last_update_id)
    for update in updates:
        last_update_id = update["update_id"] + 1
        message = update.get("message", {})
        user_id = message.get("from", {}).get("id")
        chat_id = str(message.get("chat", {}).get("id", ""))
        text = message.get("text", "").strip().lower()

        # Filtro de seguridad: solo el administrador puede usar estos comandos
        if user_id != ADMIN_USER_ID:
            continue

        if text == "/logs":
            import os
            if os.path.exists(LOG_FILE):
                log.info(f"Comando /logs ejecutado por admin (user_id={user_id})")
                _send_document_telegram(
                    chat_id,
                    LOG_FILE,
                    caption="📋 Historial de logs — bot_trading.log"
                )
            else:
                _send_text_telegram(chat_id, "⚠️ El archivo de logs aún no existe.")

        elif text == "/status":
            log.info(f"Comando /status ejecutado por admin (user_id={user_id})")
            _send_text_telegram(
                chat_id,
                "🟢 Bot de Trading v3 — Operando en línea correctamente."
            )

    return last_update_id


def main():
    log.info("Iniciando bot v3...")
    send_startup_message()
    fetch_and_process()

    schedule.every(CHECK_INTERVAL_HOURS).hours.do(fetch_and_process)
    log.info(f"Programado para correr cada {CHECK_INTERVAL_HOURS} hora(s).")

    last_update_id = None
    while True:
        schedule.run_pending()
        last_update_id = handle_admin_commands(last_update_id)
        time.sleep(60)


if __name__ == "__main__":
    main()

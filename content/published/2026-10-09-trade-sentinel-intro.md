---
id: 2026-10-09-trade-sentinel-intro
source: project_intro
source_ref: RevxngeDev/trade-sentinel@17fcf820c438cdd018b30b46f359b67a6391a1e3
status: published
created_at: '2026-10-09T16:16:12+00:00'
claimed_at: '2026-10-10T15:23:31.837354+00:00'
linkedin_urn: urn:li:share:7514707201144541184
published_at: '2026-10-10T15:23:33.817184+00:00'
---

Una señal determinista para BTC/USDT que no ejecuta trades, solo explica y registra lo que ocurre.

He construido TradeSentinel como un sistema educativo asistido por IA. Parte de datos de mercado (ccxt) → indicadores → reglas de régimen (EMA/RSI 4 h, ejecutado en 1 h) → señal BUY / HOLD / CASH, que se persiste en Supabase y se envía por Telegram. Un agente LLM lee esa señal, la comenta y responde preguntas sobre tu historial, pero nunca decide la acción; su opinión se guarda para medir su valor en futuro.

Corre sin supervisión desde el 22-06-2026: en ese periodo real la estrategia lleva +15.9 % frente a +28.5 % de comprar y mantener, así que va por detrás del mercado. En el test walk-forward, en mercado bajista, superó a comprar y mantener. Es un protector de caídas, no un generador de rentabilidad. La infraestructura permite validar cualquier cambio porque el mismo código alimenta la API en vivo y los backtests.

Tecnologías: Python 3.12, FastAPI, ccxt, Supabase, APScheduler, python-telegram-bot, Groq, SQLAlchemy + Alembic y pytest. Las capturas de datos se programan con GitHub Actions cada 2 h, sin necesidad de un servidor permanente.

https://github.com/RevxngeDev/trade-sentinel

#Python #FastAPI #Crypto #AI #DesarrolloDeSoftware

---
id: 2026-10-09-trade-sentinel-intro
source: project_intro
source_ref: RevxngeDev/trade-sentinel@17fcf820c438cdd018b30b46f359b67a6391a1e3
status: queued
created_at: '2026-10-09T16:16:12+00:00'
---

Una señal determinista para BTC/USDT que no ejecuta trades, solo explica y registra lo que ocurre.

He construido TradeSentinel como un sistema educativo asistido por IA. Parte de datos de mercado (ccxt) → indicadores → reglas de régimen (EMA/RSI 4 h, ejecutado en 1 h) → señal BUY / HOLD / CASH, que se persiste en Supabase y se envía por Telegram. Un agente LLM lee esa señal, la comenta y responde preguntas sobre tu historial, pero nunca decide la acción; su opinión se guarda para medir su valor en futuro.

El proyecto corre sin supervisión desde el 22-06-2026. En el periodo de prueba la estrategia obtuvo +15.9 % (vs +28.5 % de comprar y mantener), demostrando que protege de drawdowns aunque no genere retornos superiores. La infraestructura permite validar cualquier cambio porque el mismo código alimenta la API en vivo y los backtests.

Tecnologías: Python 3.12, FastAPI, ccxt, Supabase, APScheduler, python-telegram-bot, Groq, SQLAlchemy + Alembic y pytest. Las capturas de datos se programan con GitHub Actions cada 2 h, sin necesidad de un servidor permanente.

https://github.com/RevxngeDev/trade-sentinel

#Python #FastAPI #Crypto #AI #DesarrolloDeSoftware

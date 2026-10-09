---
id: 2026-10-09-kakao-intro
source: project_intro
source_ref: RevxngeDev/Kakao@6aa0aeb8184d964cf45f691d71d3b19119c0651b
status: queued
created_at: '2026-10-09T16:16:46+00:00'
---

Capturo el audio que reproduce mi PC — YouTube, una videollamada o una película — y le superpongo subtítulos traducidos en tiempo real, sin depender de la nube ni de claves de API.

El pipeline funciona offline: el sonido se captura con WASAPI loopback, pasa por un VAD de Silero, luego por Whisper (int8, modelo medium) que genera texto en inglés y, finalmente, una capa transparente de PySide6 muestra los subtítulos encima de la ventana activa. Todo corre en una GPU NVIDIA (probado en una GTX 1650 4 GB) con un factor de tiempo real de 0.10, es decir, diez veces más rápido que la reproducción.

Lo que me gusta es que el proceso nunca abre el micrófono, garantizado por diseño y pruebas automatizadas, y que la superposición es click-through, por lo que sigo controlando el video sin interrupciones. El control se hace desde un ícono en la bandeja del sistema o con Ctrl+Alt+K para iniciar/detener al vuelo.

Aún en fase MVP, lo uso a diario en Windows 10/11 y lo lanzo desde la terminal con `uv run python -m kakao.app`. Si te interesa probar una solución de subtítulos totalmente local, aquí tienes el repositorio:

https://github.com/RevxngeDev/Kakao

#Python #Whisper #GPU #Subtitles #OpenSource

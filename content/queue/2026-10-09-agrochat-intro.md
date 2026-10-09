---
id: 2026-10-09-agrochat-intro
source: project_intro
source_ref: RevxngeDev/AgroChat@d916b34d7f985d79444cc8b1503b57f99d0195fc
status: queued
created_at: '2026-10-09T16:16:18+00:00'
---

Una conversación que realmente entiende a los caficultores y cacaoteros colombianos: un asistente que responde con recomendaciones agronómicas respaldadas por documentos oficiales de AGROSAVIA.

Construí AgroChat como un MVP de Retrieval-Augmented Generation. El flujo offline transforma los PDFs de AGROSAVIA en fragmentos, genera embeddings con sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 y los almacena en un índice FAISS en disco. Cuando el usuario formula una pregunta, el pipeline online consulta el índice, recupera los fragmentos más relevantes, arma el prompt y delega la generación a la API de Groq (Llama 3.1 8B/70B). Cada respuesta incluye citas de la fuente, garantizando trazabilidad.

El proyecto está escrito en Python, con una CLI interactiva en JavaScript/HTML/CSS para pruebas rápidas, y la arquitectura está preparada para escalar a más cultivos, idiomas y canales como REST, WhatsApp o Telegram.

Si les interesa explorar cómo combinar RAG y datos oficiales para generar valor en la agricultura, pueden clonar el repositorio y probarlo siguiendo los pasos del Quick Start.

https://github.com/RevxngeDev/AgroChat

#Python #FAISS #RAG #AgriculturaInteligente #LLM

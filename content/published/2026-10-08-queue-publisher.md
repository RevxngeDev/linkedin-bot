---
id: 2026-10-08-queue-publisher
source: note
source_ref: Phase 1 gate test (written in session 2)
status: published
created_at: '2026-10-07T22:23:30+00:00'
claimed_at: '2026-10-08T12:13:07.585342+00:00'
linkedin_urn: urn:li:share:7513934509323649025
published_at: '2026-10-08T12:13:09.498571+00:00'
---

Avance en linkedin-bot: ahora cada post vive como un archivo en el repositorio y solo se publica si llegó a la rama principal mediante un Pull Request que yo aprobé. El código lo comprueba con la API de GitHub antes de publicar.

Tampoco puede publicar el mismo post dos veces: antes de llamar a la API de LinkedIn, el bot reserva el post con un commit, y si algo falla a mitad del proceso se detiene en lugar de reintentar a ciegas.

Este es el primer post que pasa por ese flujo completo. #Python #GitHubActions

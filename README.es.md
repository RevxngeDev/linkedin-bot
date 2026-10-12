# linkedin-bot

**Un pipeline de publicación asistido por IA y aprobado por mí para mi perfil personal de LinkedIn.**

Convierte mis notas y la actividad de mis proyectos públicos de GitHub en borradores de
posts, abre cada borrador como un Pull Request para que yo lo revise y lo edite, y
publica solo lo que fusiono, a través de la API oficial de LinkedIn. Todo corre en
GitHub Actions.

🇬🇧 [Read in English](README.md)

---

## Por qué

Quería tener presencia constante y creíble en LinkedIn sin entregar mi perfil a un bot
autónomo. El texto genérico de IA se reconoce enseguida y un mal post cuesta más
credibilidad de la que ganan diez buenos, así que la regla de diseño es simple:
**la IA redacta, yo decido.**

## Qué hace

```
 FUENTES                    GENERADOR                  REVISIÓN (yo)            PUBLICADOR
 ───────                    ─────────                  ─────────────            ──────────
 content/ideas/*.md   ──►   LLM + perfil de voz  ──►   un Pull Request    ──►   API de LinkedIn
 (mis notas)                + reglas de veracidad      por borrador             (crear post)
                            + verificación automática  editar → merge = sí      máx. 1/día
 repos de GitHub                                       cerrar = no              registra el URN
 vigilados (README,                                                             en el repo
 commits, archivos)
```

1. **Notas**: dejo una nota en `content/ideas/` y el generador redacta un post a partir de ella.
2. **Proyectos**: para cada repo de `config/watched_repos.yml`, el generador escribe
   primero un post de presentación y después, como mucho, una actualización por semana
   cuando hay commits nuevos (lee los mensajes de commit y la lista de archivos cambiados).
3. **Revisión**: cada borrador es su propio Pull Request, con el material de origen y un
   informe de verificación automática que marca las afirmaciones que el material no respalda.
4. **Publicación**: fusionar el PR aprueba el post; `publish.yml` lo publica (como mucho
   un post por día UTC) y mueve el archivo a `content/published/` con su URN de LinkedIn.

## Garantías (aplicadas en el código, no por convención)

| Garantía | Cómo |
|---|---|
| **Nada se publica sin mi aprobación** | Antes de publicar, el publicador pregunta a la API de GitHub si el commit que añadió el archivo del post pertenece a un PR fusionado. Un archivo subido directamente a la cola se rechaza. |
| **Cada post se publica como mucho una vez** | El post se *reserva* (`status: publishing`) y se sube **antes** de llamar a LinkedIn. Si una ejecución se corta a mitad, el post queda bloqueado para revisión manual en lugar de reintentarse a ciegas. |
| **Como mucho un post al día** | La selección revisa el registro de publicados del día UTC actual. |
| **Sin datos inventados** | Las reglas que no se negocian viven en el código (no en el archivo de estilo editable): solo hechos del material, sin cifras, circunstancias ni comparaciones inventadas, y cada cifra con su contexto. Una segunda pasada de IA lista las afirmaciones dudosas en el PR. |
| **Solo publica** | La única escritura en LinkedIn es "crear post". Sin likes, comentarios, mensajes, lectura del feed ni scraping. Solo la API oficial. |
| **Sin borradores duplicados** | Cada nota o repo corresponde a un nombre de rama fijo; antes se comprueban los PRs existentes (abiertos, fusionados o cerrados = rechazados). Sin archivo de estado. |

## Cómo está construido

| Área | Elección |
|---|---|
| Lenguaje | Python 3.12, gestionado con [uv](https://docs.astral.sh/uv/) |
| HTTP | httpx (en los tests todas las llamadas externas están simuladas) |
| LLM | Groq (`openai/gpt-oss-120b`) detrás de una interfaz `LLMClient` independiente del proveedor; modelo y parámetros en `config/llm.yml` |
| LinkedIn | API REST oficial: Posts API con `w_member_social`; OpenID Connect para el id de miembro |
| Almacenamiento | Archivos Markdown con frontmatter YAML en este repo, sin base de datos |
| Ejecución | GitHub Actions (disparadores por push, programaciones diarias, ejecuciones manuales) |
| Tests | pytest (tests unitarios y operaciones de git contra repositorios temporales reales) |

```
src/linkedin_bot/
├── auth/        script OAuth local para obtener el token de LinkedIn (nunca corre en CI)
├── sources/     lee datos públicos de los repos (README, lenguajes, commits, archivos cambiados)
├── generator/   prompts, perfil de voz, redacción, verificación, ejecuciones de notas y proyectos
├── llm/         interfaz LLMClient + cliente de Groq (reintenta ante límites de uso)
├── store/       archivos de post: leer, validar, escribir, mover cola → publicados
├── publisher/   reglas de selección, verificación de PR, cliente de LinkedIn, publicación
├── repo/        envoltorio de git y cliente REST de GitHub compartidos por ambos pipelines
├── notify/      avisos opcionales por Telegram (solo salida)
└── ops/         aviso de caducidad del token, resumen semanal, comprobación de Telegram
config/          llm.yml · voice_profile.md · watched_repos.yml · linkedin_token.yml
content/         ideas/ · queue/ · published/  (el registro de publicados solo crece)
```

| Workflow | Disparador | Qué hace |
|---|---|---|
| `generate.yml` | nota nueva, cambio en los repos vigilados, diario, manual | redacta posts y abre un PR por borrador |
| `publish.yml` | merge a la cola, diario, manual | publica el siguiente post aprobado y vencido |
| `preview-draft.yml` | manual | muestra un borrador y su verificación para una nota o un repo; no abre nada ni publica |
| `llm-check.yml` | manual | una generación corta para comprobar la clave y el modelo de IA |
| `token-reminder.yml` | diario, manual | abre un Issue de GitHub con los pasos de renovación 14 días antes de que caduque el token de LinkedIn |
| `weekly-summary.yml` | semanal, manual | resumen por Telegram: publicados, en cola, borradores pendientes, caducidad del token |
| `telegram-check.yml` | manual | configuración de Telegram: muestra tu chat id o envía un mensaje de prueba |

## Ponerlo en marcha

1. **Crea una app de desarrollador de LinkedIn** y añade los productos *Share on LinkedIn*
   y *Sign In with LinkedIn using OpenID Connect*. Registra la URL de redirección
   `http://localhost:8765/callback`.
2. **Obtén un token en local:** `cp .env.example .env`, rellena el client id y el secret,
   ejecuta `uv run linkedin-bot-auth`, inicia sesión y pulsa *Allow*. Muestra tu URN de
   miembro y la caducidad del token, y guarda el token en `.linkedin_token.json` (ignorado
   por git). Los tokens de LinkedIn duran 60 días; repite este paso antes de que caduquen.
   El script también escribe la nueva fecha en `config/linkedin_token.yml` (haz commit)
   para que el workflow de aviso sepa cuándo avisarte.
3. **Secrets del repositorio** (Settings → Secrets and variables → Actions):
   `LINKEDIN_ACCESS_TOKEN`, `LINKEDIN_MEMBER_URN`, `GROQ_API_KEY`; opcionalmente
   `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` para los avisos (ejecuta `telegram-check.yml`
   una vez para saber tu chat id).
4. **Ajustes del repositorio:** permite que GitHub Actions cree pull requests
   (Settings → Actions → General) y activa "Automatically delete head branches".
5. Edita `config/voice_profile.md` (tu tono y al menos 3 posts escritos por ti) y
   `config/watched_repos.yml`.

Ejecutar los tests:

```bash
uv run pytest -q
```

## Estado

- ✅ Publicación desde la cola con verificación de aprobación, sin duplicados y con límite diario.
- ✅ Borradores desde notas, un PR por borrador, verificación automática.
- ✅ Presentaciones de proyectos desde los repos vigilados; actualizaciones semanales implementadas.
- ✅ Aviso automático (Issue de GitHub) antes de que caduque el token de LinkedIn.
- ✅ Avisos por Telegram (opcionales): borradores nuevos con botón al PR, posts publicados con
  botón a LinkedIn, problemas y resumen semanal; los envía GitHub Actions, sin servidor.
- 🔜 Ideas para más adelante: aprobar y programar desde Telegram (necesita un proceso siempre a la escucha).

## Lo que no hace

Sin likes, comentarios, solicitudes de conexión, mensajes, lectura del feed ni scraping.
Sin automatización del navegador ni APIs no oficiales. Sin publicación autónoma: cada post
pasa por un Pull Request fusionado.

---

Sin relación con LinkedIn. Usa solo la API oficial de LinkedIn dentro de sus términos.
Licencia [MIT](LICENSE).

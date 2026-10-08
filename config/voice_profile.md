# Perfil de voz

Este archivo define CÓMO suenan los posts. Para que los borradores mejoren, se edita este
archivo, no el código (ROADMAP, riesgo de la Fase 2). Las reglas de veracidad, idioma y
formato no están aquí: viven en el código del generador y no se pueden desactivar desde
este archivo.

## Reglas

### Tono
- Primera persona, directo, cercano y con carisma: tiene que enganchar y sentirse real,
  como un desarrollador contando a colegas lo que hizo, lo que le costó y lo que aprendió.
  Mostrar emociones y reacciones ante los hechos (frustración, alivio, sorpresa) está bien.
  El ambiente (momento del día, lugar, situación) solo si la nota lo cuenta.
  Sin tono de anuncio corporativo ni de vendedor.
- Seguro pero honesto: contar lo que se hizo tal como fue, sin exagerar su importancia.
- Español neutro, entendible en España y Latinoamérica. Tratar a la audiencia de "ustedes".

### Estructura
- Gancho en las 1-2 primeras líneas, construido con un hecho, un problema o un contraste
  que esté en la nota. No inventar escenas ni circunstancias para el gancho. Nunca empezar
  con un saludo ni con "Hoy quiero compartir".
- Párrafos cortos (1-3 líneas) separados por una línea en blanco.
- Usar listas solo cuando ordenan pasos o puntos reales, con "-" o con un emoji como
  marcador.
- Incluir una idea central en una frase memorable: qué se aprendió o por qué importa.
- Cerrar con una pregunta concreta a la audiencia solo cuando encaje con el tema (por
  ejemplo, una decisión técnica discutible). Si no encaja, cerrar con la idea central o
  con el siguiente paso del proyecto. Nunca una pregunta genérica tipo "¿Qué opinan?".
- Longitud: entre 120 y 250 palabras.

### Emojis
- Entre 0 y 4 por post, y solo como marcadores de sección o de lista. Nunca varios
  seguidos ni al final de cada frase.

### Hashtags (D-025)
- Entre 3 y 5, todos en la última línea, separados por espacios.
- Elegirlos según el contenido: las tecnologías, herramientas o temas que aparecen en la
  nota (por ejemplo #Python, #GitHubActions), más como mucho uno general
  (#DesarrolloDeSoftware, #Backend o #IA).
- Escribirlos en CamelCase y sin tildes. Nunca un hashtag de una tecnología que no aparezca
  en la nota.

### Frases prohibidas
No usar estas expresiones ni variantes cercanas:
- "En el vertiginoso mundo de…", "En la era digital", "En el panorama actual"
- "Me complace anunciar", "Estoy emocionado de compartir", "¡Grandes noticias!"
- "revolucionar", "cambiar las reglas del juego", "game changer", "sinergia",
  "desbloquear", "potenciar al máximo", "llevar al siguiente nivel"
- "Sin más preámbulos", "En resumen", "En conclusión"
- "No es solo X, es Y" como muletilla
- Guiones largos (—) para intercalar ideas.

### Uso de los ejemplos
- Los ejemplos de abajo son SOLO referencia de estilo. Nunca son fuente de datos: años de
  experiencia, ciudad, tecnologías o cifras que aparezcan en ellos no se usan en un post.

## Ejemplos escritos por el autor (few-shot, D-011)

### Ejemplo 1

Un asistente de IA acaba de escupir 850 líneas de código en 30 segundos.
El desarrollador tardó 15 segundos en mirarlo por encima y el revisor metió un "LGTM" por agotamiento.
Bienvenido a la era de la revisión ciega.

Picar código ya no es el cuello de botella en los equipos de desarrollo. El verdadero tapón ahora es leerlo, entenderlo y mantenerlo vivo.

Nos estamos encontrando con una avalancha de Pull Requests gigantescos donde:
   - El autor confía a ciegas porque "pasó los tests unitarios" (que también escribió la IA).
   - El revisor se encuentra con un muro inabarcable de diffs y aprueba por inercia para no frenar la entrega.
   - Nadie en el equipo tiene el mapa mental de qué efectos colaterales esconde esa lógica en producción.

El código generado por IA entra por los ojos: nombres de variables impolutos, estructura limpia y comentarios impecables.
Pero una sintaxis bonita no arregla una arquitectura rota por debajo.

Si nadie en el equipo comprende de verdad esas 800 líneas que acaban de fusionarse a main, el autor real de tu sistema ya no trabaja en la empresa.

¿Estáis limitando en vuestro equipo el tamaño de los PRs generados con IA o se aprueban asumiendo que "si compila y pasa el pipeline, va para adelante"?

### Ejemplo 2

🌟 Arquitectura de Netflix: Qué Hay Detrás de Darle Play 🌟

Abrir el catálogo y reproducir una película parecen parte de una sola operación.
Detrás hay sistemas con responsabilidades distintas: mostrar contenido, gestionar solicitudes, preparar archivos de video y entregarlos al dispositivo.

La imagen permite explorar esas áreas, aunque simplifica la arquitectura y contiene tecnologías históricas.

➡️ 1. Frontend: la experiencia del usuario
📱 Las aplicaciones presentan el catálogo, reciben interacciones y controlan la reproducción.

Cada dispositivo tiene restricciones diferentes de memoria, conectividad y capacidades de video. La experiencia debe funcionar en todos ellos.

➡️ 2. Backend: coordinar servicios y datos
⚙️ Los servicios atienden solicitudes y aplican la lógica del producto.

Netflix ha documentado el uso de GraphQL Federation en su ecosistema. Eso no significa que todas sus aplicaciones utilicen una única API o el mismo patrón de comunicación.

➡️ 3. Preparación y entrega del video
🎬 Antes de reproducirse, el contenido necesita versiones compatibles con distintas condiciones de reproducción.

Para la distribución, Netflix cuenta con Open Connect, su propia CDN, que acerca contenido a las redes de los proveedores de internet.

Esta separación ayuda a entender por qué atender una solicitud del catálogo y entregar video son problemas de infraestructura diferentes.

➡️ 4. Datos y eventos
📊 Las interacciones generan información que puede alimentar análisis y otros sistemas.
Netflix ha descrito arquitecturas que utilizan Kafka para transportar eventos y procesamiento de streams para actualizar datos conforme ocurren las acciones.

Aquí importan también los retrasos, los duplicados y la recuperación ante fallos.

➡️ 5. Entrega y operación del software
🚀 Construir una funcionalidad es una parte del trabajo.
También hay que probarla, desplegarla, observar su comportamiento y poder revertirla si introduce problemas.

Las herramientas del diagrama representan funciones diferentes: compilación, despliegue, colaboración y respuesta a incidentes.

💡 Lo más útil de estudiar Netflix es entender qué responsabilidad resuelve cada componente y cómo se conecta con los demás.

Copiar una lista de tecnologías no reproduce su arquitectura.

Para un proyecto más pequeño, la pregunta sería: ¿qué separación necesitamos hoy y qué complejidad podemos evitar hasta que exista un motivo concreto?

¿Qué parte te interesa profundizar: entrega de video, servicios, datos o despliegues?

### Ejemplo 3

Un desarrollador tardó 4 meses en levantar una plataforma desde cero. Otro tardó un fin de semana en crear una extensión para un ecosistema que ya existía. Solo uno de los dos tiene usuarios de pago hoy. El primero siguió todas las reglas del libro:

-Arquitectura limpia en capas.
-Índices ultra optimizados en PostgreSQL.
-Pipelines de CI/CD impecables con Docker.
-Resultado: 6 visitas al mes (la mitad eran de su propia IP).

El segundo no intentó reinventar la rueda. Se apalancó del tráfico de un marketplace donde ya operan miles de empresas y resolvió un dolor puntual en 200 líneas de código. A los ingenieros nos enseñan a enamorarnos de la complejidad técnica. Pero en producción manda una regla más fría: la distribución siempre le gana al código perfecto. El cliente no compra tu Dockerfile; compra el problema resuelto en el lugar donde ya pasa su jornada de trabajo. ¿Prefieren construir plataformas aisladas desde cero o apalancarse en herramientas ya consolidadas?

### Ejemplo 4

Hoy quiero compartir con mi red que estoy en búsqueda de nuevas oportunidades laborales 💼🚀

Soy desarrollador de software con 3 años de experiencia construyendo aplicaciones web y móviles. He trabajado con Angular, Ionic, React, Node.js y PHP, y me interesa seguir creciendo en roles donde pueda aportar tanto en el front-end como en el back-end.
Me interesa formar parte de equipos donde pueda aportar mis conocimientos en desarrollo de software, participar en proyectos desafiantes y seguir fortaleciendo mis habilidades técnicas.
Estoy ubicado en Bogotá y abierto a oportunidades presenciales, híbridas o remotas.
Si conoces alguna oportunidad que pueda encajar con mi perfil o puedes ayudarme compartiendo esta publicación, te lo agradecería mucho. 🙌

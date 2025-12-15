# Asistente RAG/Cypher para contratos (Huelva)

Este repositorio contiene un asistente conversacional construido con [Chainlit](https://docs.chainlit.io/) para explorar un grafo de contratación pública en Neo4j. El bot combina búsquedas vectoriales (GraphRAG), generación de consultas Cypher de solo lectura y un generador de borradores de Pliegos de Prescripciones Técnicas (PPT).

## Estructura principal

- `app.py`: orquesta el ciclo de chat en Chainlit, enruta intenciones y muestra evidencias en la barra lateral.
- `config.py`: variables de entorno y constantes (Neo4j, LLM, embeddings y límites de tokens).
- `clients.py`: inicializa los clientes compartidos de Neo4j y servicios OpenAI-compatibles.
- `services/`: lógica de negocio (RAG, generación y validación de Cypher, embeddings, generación de PPT, follow-ups y construcción de contexto).
- `chat_utils/`: utilidades de texto y parsing robusto de JSON devuelto por el modelo.
- `ui/`: helpers para renderizar evidencias en la UI de Chainlit.
- `public/`: recursos estáticos para el visor de grafo y elementos personalizados.

## Puesta en marcha

1. Instala las dependencias de Python:
   ```bash
   pip install -r requirements.txt
   ```
2. Configura las variables de entorno necesarias (ver sección siguiente) para tu instancia de Neo4j y los endpoints OpenAI-compatibles.
3. Ejecuta Chainlit apuntando al archivo de aplicación:
   ```bash
   chainlit run app.py -w
   ```
   El flag `-w` activa recarga en caliente durante el desarrollo.

### Despliegue paso a paso en un servidor Ubuntu 24.04

1. **Instala dependencias del sistema** (Python 3.10+, `pip`, `git`, `systemd` viene de serie):
   ```bash
   sudo apt update
   sudo apt install -y python3 python3-venv python3-pip git
   ```
2. **Clona el repositorio** (ajusta la URL a tu origen de GitHub):
   ```bash
   git clone https://github.com/tu-org/tu-repo.git
   cd tu-repo
   ```
3. **Crea y activa un entorno virtual** para aislar dependencias:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```
4. **Instala las dependencias del proyecto**:
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```
5. **Configura las variables de entorno** en un archivo `.env` o exportándolas antes de lanzar el servicio (ver sección siguiente).
6. **Prueba localmente** que Chainlit arranca:
   ```bash
   chainlit run app.py -w
   ```
   Accede desde el navegador a `http://<IP-del-servidor>:8000`.

### Ejecutar Chainlit como servicio persistente (systemd)

Para que Chainlit siga activo después de cerrar la terminal, crea un servicio `systemd` que use el entorno virtual y cargue las variables de entorno.

1. **Crea un archivo de servicio** (ajusta rutas a tu usuario y ubicación del repo):
   ```bash
   sudo tee /etc/systemd/system/chainlit.service >/dev/null <<'EOF'
   [Unit]
   Description=Chainlit RAG Huelva
   After=network.target

   [Service]
   Type=simple
   User=ubuntu
   WorkingDirectory=/home/ubuntu/tu-repo
   Environment="PYTHONUNBUFFERED=1"
   EnvironmentFile=/home/ubuntu/tu-repo/.env
   ExecStart=/home/ubuntu/tu-repo/.venv/bin/chainlit run /home/ubuntu/tu-repo/app.py --host 0.0.0.0 --port 8000
   Restart=on-failure

   [Install]
   WantedBy=multi-user.target
   EOF
   ```
   - `EnvironmentFile` debe apuntar a un archivo `.env` con las variables sensibles.
   - Usa `User` y `WorkingDirectory` acordes al usuario que alojará el servicio.
2. **Recarga la configuración de systemd y habilita el servicio**:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now chainlit.service
   ```
3. **Verifica el estado y los logs**:
   ```bash
   systemctl status chainlit.service
   journalctl -u chainlit.service -f
   ```
4. **Actualizar el servicio tras cambiar el código o el `.env`**:
   ```bash
   sudo systemctl restart chainlit.service
   ```

Con esta configuración, Chainlit se iniciará automáticamente al arrancar el servidor y seguirá ejecutándose aunque cierres la sesión SSH.

## Variables de entorno clave

- **Neo4j**: `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `NEO4J_DB` (por defecto `huelva`).
- **LLM (chat)**: `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`.
- **Embeddings**: `EMB_BASE_URL`, `EMB_API_KEY`, `EMB_MODEL`, `EMB_DIM`.
- **Límites y parámetros RAG**: `K_CONTRATOS`, `K_CAPITULOS`, `K_EXTRACTOS`, `MAX_HISTORY_TURNS`, `MODEL_MAX_CONTEXT_TOKENS`, `RESERVE_FOR_ANSWER_TOKENS`, `RAG_CONTEXT_MAX_TOKENS`, entre otros definidos en `config.py`.

## Flujos principales

- **RAG (contratos/capítulos/extractos)**: `services.context_builder.build_context` compone el contexto a partir de resultados de búsqueda y `app.py` lo envía al LLM junto con el historial de chat.
- **Consultas Cypher**: `services.cypher.generate_cypher_plan` crea consultas de solo lectura, las valida con `cypher_is_safe_readonly` y se ejecutan vía `services.neo4j_queries.neo4j_query`.
- **Búsqueda de empresas**: `services.neo4j_queries.search_empresas` y `search_contratos_by_empresa` resuelven adjudicatarias por nombre o CIF y devuelven contratos asociados.
- **Generación de PPT**: `services.ppt_generation.plan_ppt_clarifications` decide si pedir aclaraciones; `handle_generate_ppt` (en `app.py`) busca un PPT de referencia, genera el texto capítulo a capítulo y opcionalmente exporta a Word con `python-docx`.
- **Evidencias en la UI**: `ui.evidence` prepara markdown y componentes para mostrar las fuentes y el contexto usado en cada respuesta.

## Notas adicionales

- El proyecto usa endpoints compatibles con la API de OpenAI para chat y embeddings; puedes apuntar a servidores locales u otras implementaciones que respeten el mismo contrato.
- La generación de documentos `.docx` es opcional y depende de tener instalada la librería `python-docx` (incluida en `requirements.txt`).
- El grafo Neo4j se asume poblado con nodos `ContratoRAG`, `EmpresaRAG`, `DocumentoRAG`, `Capitulo` y `Extracto`, además de índices vectoriales definidos para las consultas.

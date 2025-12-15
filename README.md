# Asistente RAG/Cypher para contratos (Huelva)

Este repositorio contiene un asistente conversacional construido con [Chainlit](https://docs.chainlit.io/) para explorar un grafo de contratación pública en Neo4j. El bot combina búsquedas vectoriales (GraphRAG), generación de consultas Cypher de solo lectura y un generador de borradores de Pliegos de Prescripciones Técnicas (PPT).

## Estructura principal

* `app.py`: orquesta el ciclo de chat en Chainlit, enruta intenciones y muestra evidencias en la barra lateral.
* `config.py`: variables de entorno y constantes (Neo4j, LLM, embeddings y límites de tokens).
* `clients.py`: inicializa los clientes compartidos de Neo4j y servicios OpenAI-compatibles.
* `services/`: lógica de negocio (RAG, generación y validación de Cypher, embeddings, generación de PPT, follow-ups y construcción de contexto).
* `chat_utils/`: utilidades de texto y parsing robusto de JSON devuelto por el modelo.
* `ui/`: helpers para renderizar evidencias en la UI de Chainlit.
* `public/`: recursos estáticos para el visor de grafo y elementos personalizados.

## Puesta en marcha (desarrollo)

1. Crea y activa un entorno virtual:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```
2. Instala dependencias:

   ```bash
   pip install -U pip
   pip install -r requirements.txt
   ```
3. Crea un `.env` (opcional pero recomendado) con las variables necesarias (ver sección "Variables de entorno").
4. Ejecuta:

   ```bash
   chainlit run app.py -w
   ```

   El flag `-w` activa recarga en caliente durante el desarrollo.

## Despliegue en Ubuntu (servidor)

### 1) Dependencias del sistema

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git rsync
```

### 2) Clonar repositorio

```bash
git clone https://github.com/techfriendly/Xpider_Huelva.git
cd Xpider_Huelva
```

> Nota: para clonar por HTTPS, GitHub no usa contraseña de cuenta; usa un token (PAT) como password. Si prefieres no gestionar tokens, usa SSH.

### 3) Ejecución expuesta “hacia fuera”

Por defecto, un servicio puede quedarse escuchando solo en `127.0.0.1`. Para acceder desde fuera, Chainlit debe bindear en `0.0.0.0`:

```bash
chainlit run app.py --host 0.0.0.0 --port 8000
```

Verifica que está escuchando correctamente:

```bash
sudo ss -tulpn | grep ":8000"
```

Deberías ver `0.0.0.0:8000` (o la IP del servidor), no `127.0.0.1:8000`.

## Ejecutar Chainlit como servicio persistente (systemd)

Esta es la configuración recomendada para que el asistente siga activo tras cerrar la sesión SSH y arranque automáticamente al reiniciar.

### 1) Crear usuario de servicio (sin login interactivo)

```bash
sudo adduser --disabled-password --gecos "" chainlit
```

### 2) Copiar el proyecto al home del usuario de servicio

Si tu working copy actual está en otra ruta (por ejemplo `/root/Xpider_Huelva`), copia el contenido:

```bash
sudo mkdir -p /home/chainlit/Xpider_Huelva
sudo rsync -a /root/Xpider_Huelva/ /home/chainlit/Xpider_Huelva/
sudo chown -R chainlit:chainlit /home/chainlit/Xpider_Huelva
```

> Importante: ejecutar un servicio como usuario no-root contra rutas en `/root/...` suele fallar por permisos. Por eso movemos el repo a `/home/chainlit/...`.

### 3) Crear entorno virtual e instalar dependencias (como `chainlit`)

```bash
sudo su - chainlit -c 'cd /home/chainlit/Xpider_Huelva && rm -rf .venv && python3 -m venv .venv && . .venv/bin/activate && pip install -U pip && pip install -r requirements.txt'
```

### 4) Variables de entorno en `.env` (opcional)

Crea `/home/chainlit/Xpider_Huelva/.env` con tus credenciales y endpoints.

Recomendación de permisos:

```bash
sudo chown chainlit:chainlit /home/chainlit/Xpider_Huelva/.env
sudo chmod 600 /home/chainlit/Xpider_Huelva/.env
```

> Si no tienes `.env` aún, el servicio puede arrancar igualmente si usas `EnvironmentFile=-...` (ver unidad más abajo).

### 5) Crear unidad systemd

```bash
sudo tee /etc/systemd/system/chainlit.service >/dev/null <<'EOF'
[Unit]
Description=Chainlit RAG Huelva
After=network.target

[Service]
Type=simple
User=chainlit
WorkingDirectory=/home/chainlit/Xpider_Huelva
Environment="PYTHONUNBUFFERED=1"
EnvironmentFile=-/home/chainlit/Xpider_Huelva/.env
ExecStart=/home/chainlit/Xpider_Huelva/.venv/bin/chainlit run app.py --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
```

Puntos clave:

* `User=chainlit`: evita correr como root.
* `WorkingDirectory` y `ExecStart` apuntan a rutas accesibles por el usuario.
* `EnvironmentFile=-...` (con guion) evita que el servicio falle si el `.env` no existe aún.
* Se fuerza el bind público con `--host 0.0.0.0`.

### 6) Habilitar y arrancar

```bash
sudo systemctl daemon-reload
sudo systemctl reset-failed chainlit.service
sudo systemctl enable --now chainlit.service
```

### 7) Operación y diagnóstico

Estado:

```bash
systemctl status chainlit.service --no-pager
```

Logs:

```bash
journalctl -u chainlit.service -n 200 --no-pager
```

Reiniciar tras cambios en código o `.env`:

```bash
sudo systemctl restart chainlit.service
```

Comprobar puerto:

```bash
sudo ss -tulpn | grep ":8000"
```

## Firewall y acceso externo

Aunque el proceso escuche en `0.0.0.0:8000`, puede seguir sin ser accesible desde Internet si:

* hay firewall local (UFW/nftables/iptables), o
* hay firewall del proveedor (cloud).

Comprobación rápida en servidor:

```bash
curl -v http://127.0.0.1:8000
```

Si en local funciona, pero desde fuera no, revisa firewall.

Si usas UFW:

```bash
sudo ufw status verbose
sudo ufw allow 8000/tcp
```

### Acceso sin abrir puertos (túnel SSH)

Para usarlo sin exponer el puerto 8000 públicamente:

En tu PC:

```bash
ssh -L 8000:127.0.0.1:8000 root@IP_DEL_SERVIDOR
```

Luego abre:
`http://127.0.0.1:8000`

## Variables de entorno clave

* **Neo4j**: `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `NEO4J_DB` (por defecto `huelva`).
* **LLM (chat)**: `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`.
* **Embeddings**: `EMB_BASE_URL`, `EMB_API_KEY`, `EMB_MODEL`, `EMB_DIM`.
* **Límites y parámetros RAG**: `K_CONTRATOS`, `K_CAPITULOS`, `K_EXTRACTOS`, `MAX_HISTORY_TURNS`, `MODEL_MAX_CONTEXT_TOKENS`, `RESERVE_FOR_ANSWER_TOKENS`, `RAG_CONTEXT_MAX_TOKENS`, entre otros definidos en `config.py`.

## Flujos principales

* **RAG (contratos/capítulos/extractos)**: `services.context_builder.build_context` compone el contexto a partir de resultados de búsqueda y `app.py` lo envía al LLM junto con el historial de chat.
* **Consultas Cypher**: `services.cypher.generate_cypher_plan` crea consultas de solo lectura, las valida con `cypher_is_safe_readonly` y se ejecutan vía `services.neo4j_queries.neo4j_query`.
* **Búsqueda de empresas**: `services.neo4j_queries.search_empresas` y `search_contratos_by_empresa` resuelven adjudicatarias por nombre o CIF y devuelven contratos asociados.
* **Generación de PPT**: `services.ppt_generation.plan_ppt_clarifications` decide si pedir aclaraciones; `handle_generate_ppt` (en `app.py`) busca un PPT de referencia, genera el texto capítulo a capítulo y opcionalmente exporta a Word con `python-docx`.
* **Evidencias en la UI**: `ui.evidence` prepara markdown y componentes para mostrar las fuentes y el contexto usado en cada respuesta.

## Notas adicionales

* El proyecto usa endpoints compatibles con la API de OpenAI para chat y embeddings; puedes apuntar a servidores locales u otras implementaciones compatibles.
* La generación de documentos `.docx` es opcional y depende de `python-docx` (incluida en `requirements.txt`).
* El grafo Neo4j se asume poblado con nodos `ContratoRAG`, `EmpresaRAG`, `DocumentoRAG`, `Capitulo` y `Extracto`, además de índices vectoriales definidos para las consultas.
* Para entornos productivos, se recomienda poner un reverse proxy (por ejemplo Nginx) con HTTPS delante de Chainlit.

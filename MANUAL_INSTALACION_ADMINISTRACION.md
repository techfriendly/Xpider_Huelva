# 📘 Manual de Instalación y Administración - Xpider Huelva

Este documento detalla los procedimientos para instalar, configurar, ejecutar y mantener el Asistente Inteligente de Contratación (Xpider Huelva).

---

## 1. Requisitos del Sistema

Antes de comenzar, asegúrate de que el servidor o máquina local cumpla con lo siguiente:

*   **Sistema Operativo**: Linux (Ubuntu 22.04+ recomendado) o macOS.
*   **Python**: Versión 3.10 o superior.
*   **Base de Datos**: Neo4j (Community o Enterprise) con plugin GDS (Graph Data Science) y APOC instalados.
*   **Git**: Para control de versiones.

---

## 2. Instalación Paso a Paso

### 2.1. Clonar el Repositorio
Descarga el código fuente desde GitHub:

```bash
cd /ruta/donde/quieras/instalar
git clone https://github.com/techfriendly/Xpider_Huelva.git
cd Xpider_Huelva
```

### 2.2. Crear Entorno Virtual
Es **crítico** aislar las dependencias del proyecto para evitar conflictos con el sistema:

```bash
# Crear el entorno (.venv)
python3 -m venv .venv

# Activar el entorno
source .venv/bin/activate
```
*(Deberás ver `(.venv)` al principio de tu línea de comandos).*

### 2.3. Instalar Dependencias
Instala las librerías necesarias listadas en `requirements.txt`:

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

---

## 3. Configuración

### 3.1. Variables de Entorno (`.env`)
Crea un archivo llamado `.env` en la raíz del proyecto. **Este archivo contiene secretos y NO debe subirse a Git.**

Usa el siguiente modelo:

```ini
# --- NEO4J (Base de Grafos) ---
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=tu_contraseña_secreta
NEO4J_DB=huelva

# --- LLM y Embeddings (OpenAI compatible) ---
LLM_BASE_URL=http://tu-servidor-llm:8002/v1
LLM_API_KEY=dummy-key
LLM_MODEL=nombre-del-modelo

EMB_BASE_URL=http://tu-servidor-llm:8003/v1
EMB_API_KEY=dummy-key
EMB_MODEL=nombre-del-modelo-embedding

# --- Observabilidad (Opcional) ---
# Activar si tienes cuenta en LangSmith
LANGSMITH_TRACING_V2=true
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_API_KEY=tu_api_key_langsmith
LANGSMITH_PROJECT=Xpider_Huelva

# Activar si usas Literal AI
LITERAL_API_KEY=tu_api_key_literal
```

### 3.2. Gestión de Usuarios del Chatbot (`users.json`)
El chatbot tiene su propio sistema de autenticación simple. Los usuarios se guardan en `users.json`.
**No edites este archivo a mano si no quieres errores de formato.** Usa la herramienta incluida:

```bash
# Listar usuarios
python manage_users.py list

# Añadir o cambiar contraseña de un usuario
python manage_users.py add nombre_usuario contraseña123
```

### 3.3. Configuración Avanzada (`config.py`)
Si necesitas ajustar límites de tokens, número de documentos a recuperar (RAG) o timeouts, edita `config.py`. Las variables allí toman su valor por defecto o del `.env` si se definen.

---

## 4. Ejecución

### 4.1. Modo Desarrollo (Local)
Para probar cambios con recarga automática:

```bash
chainlit run app.py -w
```
El chatbot estará disponible en `http://localhost:8000`.

### 4.2. Modo Producción (Servidor)
Se recomienda usar `systemd` para que el servicio arranque automáticamente y se reinicie si falla.

**Archivo de servicio: `/etc/systemd/system/chainlit.service`**
*(Asegúrate de ajustar las rutas a donde hayas clonado el repo)*

```ini
[Unit]
Description=Chainlit RAG Huelva
After=network.target

[Service]
User=chainlit
Group=chainlit
WorkingDirectory=/home/chainlit/Xpider_Huelva
# Ejecuta usando el Python del entorno virtual
ExecStart=/home/chainlit/Xpider_Huelva/.venv/bin/chainlit run app.py --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

**Comandos de gestión:**
```bash
sudo systemctl start chainlit    # Iniciar
sudo systemctl stop chainlit     # Parar
sudo systemctl restart chainlit  # Reiniciar
sudo systemctl status chainlit   # Ver estado y logs recientes
```

---

## 5. Mantenimiento y Solución de Problemas

### 5.1. Actualizar la Aplicación
Para traer los últimos cambios del repositorio:

```bash
cd /ruta/Xpider_Huelva
git pull origin main

# Si hubo cambios en librerías, actualiza:
source .venv/bin/activate
pip install -r requirements.txt

# Reinicia el servicio
sudo systemctl restart chainlit
```

### 5.2. Error: "OS file watch limit reached"
Si ves este error al arrancar, significa que Chainlit intenta vigilar demasiados archivos. Aumenta el límite del sistema:

```bash
echo fs.inotify.max_user_watches=524288 | sudo tee -a /etc/sysctl.conf
sudo sysctl -p
```

### 5.3. Activar/Desactivar Autoscroll
Si el chatbot no hace scroll automático al recibir respuestas, revisa la configuración de JavaScript personalizado.

1.  Asegúrate de que existe el archivo `public/force_scroll.js`.
2.  Edita `.chainlit/config.toml` y descomenta/configura la línea:
    ```toml
    custom_js = "/public/force_scroll.js"
    ```
3.  Además, en la sección `[features]` mantén:
    ```toml
    assistant_message_autoscroll = true
    user_message_autoscroll = true
    ```
4.  **Importante**: Forzar recarga del navegador (Ctrl+Shift+R) tras cambios.

### 5.4. Error de Permisos
Si el servicio falla con "Permission denied", asegúrate de que el usuario `chainlit` es dueño de la carpeta:

```bash
sudo chown -R chainlit:chainlit /home/chainlit/Xpider_Huelva
```

### 5.4. Faltan Usuarios o Configuración tras Actualizar
Recuerda que `.env` y `users.json` **no se actualizan con git** (por seguridad están en `.gitignore`).
*   Si borras la carpeta y clonas de nuevo, tendrás que volver a crear el `.env` y ejecutar `python manage_users.py add ...`.

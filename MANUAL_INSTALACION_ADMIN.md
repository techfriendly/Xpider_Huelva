# Manual de instalación y administración del chatbot

## 1. Objetivo
Este documento describe cómo **instalar**, **configurar** y **administrar** el chatbot de contratación de la Diputación de Huelva, incluyendo la puesta en marcha, la base de datos de historial y la gestión de usuarios.

---

## 2. Requisitos previos
- **Python 3.10+** y acceso a `pip` para instalar dependencias (ver `requirements.txt`).
- **Neo4j** accesible vía Bolt (URI, usuario, contraseña y base de datos configurables).
- **Servidor LLM** compatible con OpenAI API para chat y **servidor de embeddings** compatible con OpenAI API.

El backend lee estas variables desde el entorno (o usa valores por defecto):
- **Neo4j**: `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `NEO4J_DB`.
- **LLM**: `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`.
- **Embeddings**: `EMB_BASE_URL`, `EMB_API_KEY`, `EMB_MODEL`, `EMB_DIM`.
- **Parámetros RAG/Historial**: `K_CONTRATOS`, `K_CAPITULOS`, `K_EXTRACTOS`, `MAX_HISTORY_TURNS`, `MODEL_MAX_CONTEXT_TOKENS`, `RESERVE_FOR_ANSWER_TOKENS`, `MEMORY_SUMMARY_TOKENS`, `RAG_CONTEXT_MAX_TOKENS`.

> Nota: si no defines variables de entorno, se usan los valores por defecto definidos en `config.py`.

---

## 3. Instalación local
1. **Crear entorno virtual e instalar dependencias**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Configurar variables de entorno**
   Crea un archivo `.env` (o exporta las variables en tu shell) con los valores de conexión y modelo. Ejemplo mínimo:
   ```bash
   export NEO4J_URI="bolt://tu-host:7687"
   export NEO4J_USER="neo4j"
   export NEO4J_PASSWORD="tu_password"
   export NEO4J_DB="huelva"

   export LLM_BASE_URL="http://tu-llm:8002/v1"
   export LLM_API_KEY="tu_api_key"
   export LLM_MODEL="llm"

   export EMB_BASE_URL="http://tu-embeddings:8003/v1"
   export EMB_API_KEY="tu_emb_key"
   export EMB_MODEL="embedding"
   export EMB_DIM="1024"
   ```

3. **Inicializar la base de datos de historial (SQLite)**
   El historial del chat se guarda en `chat_history.db` en el directorio actual. Para crear las tablas:
   ```bash
   python create_tables.py
   ```

4. **Arrancar la aplicación**
   ```bash
   chainlit run app.py -w
   ```

---

## 4. Despliegue en servidor (systemd)
Crea un servicio para mantener el chatbot activo. Ejemplo de unidad:

```ini
[Unit]
Description=Chainlit Chatbot Xpider Huelva
After=network.target

[Service]
User=chainlit
WorkingDirectory=/home/chainlit/Xpider_Huelva
EnvironmentFile=/home/chainlit/Xpider_Huelva/.env
ExecStart=/home/chainlit/Xpider_Huelva/.venv/bin/chainlit run app.py --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

**Activación:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now chainlit
sudo systemctl status chainlit
```

---

## 5. Administración diaria

### 5.1 Gestión de usuarios y contraseñas
La autenticación se basa en el archivo `users.json`. Para dar de alta un usuario, añade un par `"usuario": "contraseña"` en el JSON. El login compara credenciales contra ese fichero.

**Ejemplo (`users.json`):**
```json
{
  "admin": "cambia_esta_password",
  "contratacion": "otra_password"
}
```

### 5.2 Base de datos del historial
- **Ubicación**: `chat_history.db` en el directorio de trabajo.
- **Creación**: `python create_tables.py`.
- **Inicialización forzada**: `python force_db_init.py` (usa los modelos internos de Chainlit).
- **Seed de ejemplo**: `python seed_db.py`.
- **Diagnóstico**: `python test_db.py`.

> Recomendación: incluye `chat_history.db` en tus rutinas de backup si necesitas conservar el histórico de conversaciones.

### 5.3 Logs y diagnóstico
El backend imprime mensajes de estado en consola. Si tienes problemas de persistencia, revisa la salida de la aplicación y considera habilitar los logs comentados en `app.py` para ver operaciones de la capa de datos.

### 5.4 Cambios de configuración
Las variables de entorno controlan el comportamiento del sistema (modelos LLM, embeddings y parámetros RAG). Para cambios de producción:
1. Actualiza `.env`.
2. Reinicia el servicio (`systemctl restart chainlit`).

---

## 6. Operación segura y mantenimiento
- **Rotación de credenciales**: actualiza periódicamente `users.json` y las claves de los servicios LLM/Embeddings.
- **Neo4j**: asegúrate de mantener restricciones de acceso solo lectura si el entorno lo requiere.
- **Backups**: guarda `chat_history.db` y la configuración `.env` en un lugar seguro.

---

## 7. Comandos rápidos (resumen)
```bash
# Instalar dependencias
pip install -r requirements.txt

# Crear tablas de historial
python create_tables.py

# Arrancar app en desarrollo
chainlit run app.py -w

# Verificar estado de la BD
python test_db.py
```

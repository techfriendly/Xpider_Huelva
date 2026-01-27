# 🦅 Chatbot de Contratación Pública (Huelva V2)

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python)](https://www.python.org/)
[![Neo4j](https://img.shields.io/badge/Neo4j-5.x-green?logo=neo4j)](https://neo4j.com/)
[![Chainlit](https://img.shields.io/badge/Chainlit-UI-orange)](https://chainlit.io/)
[![LLM](https://img.shields.io/badge/LLM-Qwen3--A30--3B-purple)](https://github.com/QwenLM/Qwen)

Asistente Virtual inteligente diseñado para el **Área de Contratación de la Diputación Provincial de Huelva**. Este sistema permite explorar licitaciones, analizar datos económicos de empresas y generar borradores de pliegos técnicos utilizando **IA Generativa (RAG)** y **Grafos de Conocimiento**.

---

## 📋 Tabla de Contenidos

1.  [Funcionalidades](#-funcionalidades)
2.  [Requisitos Previos](#-requisitos-previos)
3.  [Instalación](#-instalación)
4.  [Configuración](#-configuración)
5.  [Ejecución](#-ejecución)
6.  [Ejemplos de Uso](#-ejemplos-de-uso)
7.  [Arquitectura](#-arquitectura)
8.  [Estructura del Proyecto](#-estructura-del-proyecto)
9.  [Solución de Problemas](#-solución-de-problemas)
10. [Contribuir](#-contribuir)
11. [Licencia](#-licencia)

---

## 🚀 Funcionalidades

### 🔍 Búsqueda Híbrida de Contratos
Localiza contratos utilizando múltiples estrategias:
- **Búsqueda Semántica (RAG)**: Encuentra contratos por similitud de significado, no solo palabras clave.
- **Búsqueda Exacta**: Detecta automáticamente números de expediente (`2024/CMY_03/000034`) o NIFs de empresa.
- **Filtrado por Extractos**: Busca dentro de cláusulas técnicas, requisitos de solvencia o condiciones ambientales.

### 🧠 Inteligencia de Grafos (Neo4j)
Consultas analíticas en lenguaje natural traducidas automáticamente a Cypher:
- Rankings de empresas adjudicatarias.
- Volúmenes de contratación por año, tipo o sector (CPV).
- Navegación de relaciones (Empresa → Contratos → Pliegos → Capítulos).

### 📄 Generador de Pliegos Técnicos (PPT)
- Redacción automática de **Pliegos de Prescripciones Técnicas**.
- Basado en contratos históricos similares (Few-Shot RAG).
- Exportación directa a **Microsoft Word (.docx)**.
- Flujo interactivo con preguntas de clarificación.

### 🤖 Stack 100% Local y Privado
- Compatible con modelos Open Source (**Qwen3-A30-3B**, **Llama 3**, **Mistral**).
- Embeddings locales (**qwen-0.6-embedding**, **multilingual-e5**).
- API compatible con OpenAI (funciona con vLLM, Ollama, LM Studio, etc.).
- **Sin datos enviados a terceros**.

---

## 🛠️ Requisitos Previos

| Componente | Versión Mínima | Notas |
|------------|----------------|-------|
| Python | 3.10+ | Recomendado 3.11 |
| Neo4j | 5.x | Community o Enterprise |
| Servidor LLM | - | Cualquier endpoint compatible OpenAI API |
| RAM | 16 GB+ | Para modelos locales pequeños o embeddings |
| GPU | 24 GB+ VRAM | Acelera inferencia LLM |

### Modelos Recomendados
- **LLM**: `Qwen/Qwen3-A30-3B`, `mistralai/Mistral-7B-Instruct-v0.3` (cuantizados)
- **Embeddings**: `qwen-0.6-embedding`, `intfloat/multilingual-e5-large` (cuantizados)

---

## 📦 Instalación

### 1. Clonar el Repositorio
```bash
git clone https://github.com/tu-usuario/chatbot-huelva-v2.git
cd chatbot-huelva-v2
```

### 2. Crear Entorno Virtual
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows
```

### 3. Instalar Dependencias
```bash
pip install -r requirements.txt
```

**Dependencias principales:**
- `chainlit` - Framework de UI conversacional
- `openai` - Cliente para APIs compatibles
- `neo4j` - Driver oficial de Neo4j
- `pandas` - Manipulación de datos y tablas
- `python-docx` - Generación de documentos Word

### 4. Preparar Neo4j
Asegúrate de que tu base de datos Neo4j contiene:
- Nodos `:ContratoRAG` con propiedades: `expediente`, `titulo`, `cpv_principal`, `valor_estimado`, etc.
- Nodos `:EmpresaRAG` con propiedades: `nombre`, `nif`.
- Relaciones `(:EmpresaRAG)-[:ADJUDICATARIA_RAG {importe_adjudicado}]->(:ContratoRAG)`.
- Índices vectoriales sobre `embedding` (si usas búsqueda semántica).

---

## ⚙️ Configuración

Crea un archivo `.env` en la raíz del proyecto:

```ini
# ═══════════════════════════════════════════════════════════════
# CONEXIÓN NEO4J
# ═══════════════════════════════════════════════════════════════
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=tu_password_seguro
NEO4J_DB=huelva  # Nombre de la base de datos

# ═══════════════════════════════════════════════════════════════
# LLM (API Compatible con OpenAI)
# ═══════════════════════════════════════════════════════════════
LLM_BASE_URL=http://localhost:8000/v1
LLM_API_KEY=dummy-key  # Requerido por el cliente, puede ser cualquier string
LLM_MODEL=Qwen/Qwen3-A30-3B  # Nombre exacto del modelo en tu servidor

# ═══════════════════════════════════════════════════════════════
# EMBEDDINGS
# ═══════════════════════════════════════════════════════════════
EMB_BASE_URL=http://localhost:8003/v1  # Puede ser el mismo que LLM_BASE_URL
EMB_API_KEY=dummy-key
EMB_MODEL=qwen-0.6-embedding
EMB_DIM=1024  # Dimensión del vector de embedding
```

### Variables Opcionales
```ini
# Número de resultados por búsqueda
K_CONTRATOS=10
K_CAPITULOS=5
K_EXTRACTOS=5
```

---

## ▶️ Ejecución

### Modo Desarrollo (con recarga automática)
```bash
chainlit run app.py -w
```

### Modo Producción
```bash
chainlit run app.py --host 0.0.0.0 --port 8000
```

Abre tu navegador en `http://localhost:8000`.

---

## 💬 Ejemplos de Uso

### Búsqueda de Contratos
```
Usuario: Busca contratos de suministro de vehículos eléctricos
Usuario: Contratos que incluyan requisitos de solvencia medioambiental
Usuario: Expediente 2024/CMY_03/000034
```

### Análisis de Empresas
```
Usuario: ¿Qué contratos ha ganado Techfriendly?
Usuario: Muestra el perfil de la empresa con NIF B21368246
Usuario: Top 10 empresas por importe adjudicado en obras
```

### Consultas Analíticas
```
Usuario: ¿Cuál es el volumen total adjudicado en suministros en 2024?
Usuario: Ranking de empresas en contratos de servicios informáticos
Usuario: ¿Cuántos contratos de obra hay por encima de 100.000€?
```

### Generación de Documentos
```
Usuario: Hazme un pliego para material informático
Usuario: Genera un PPT para suministro de mobiliario de oficina
Usuario: [Tras ver un contrato] Genera un PPT basado en este contrato
```

---

## 📐 Arquitectura

El sistema sigue un patrón de **Agente Orquestado** donde el LLM decide qué herramienta utilizar según la intención del usuario.

```
┌──────────────┐     ┌─────────────────┐     ┌────────────────┐
│   Usuario    │────▶│ Chainlit (UI)   │────▶│  Orquestador   │
└──────────────┘     └─────────────────┘     └───────┬────────┘
                                                     │
                     ┌───────────────────────────────┼───────────────────────────────┐
                     │                               │                               │
              ┌──────▼──────┐               ┌────────▼────────┐             ┌────────▼────────┐
              │ Búsqueda    │               │ Generador       │             │ Cypher QA       │
              │ Híbrida     │               │ de PPT          │             │ (Text-to-SQL)   │
              └──────┬──────┘               └────────┬────────┘             └────────┬────────┘
                     │                               │                               │
                     └───────────────────────────────┼───────────────────────────────┘
                                                     │
                                              ┌──────▼──────┐
                                              │   Neo4j     │
                                              │  (Grafos)   │
                                              └─────────────┘
```

Para detalles técnicos completos, consulta: 👉 **[architecture.md](./architecture.md)**

---

## 📂 Estructura del Proyecto

```
chatbot-huelva-v2/
├── app.py                    # Punto de entrada (Frontend Chainlit)
├── config.py                 # Configuración desde variables de entorno
├── clients.py                # Inicialización de clientes (LLM, Embeddings)
├── chainlit.md               # Mensaje de bienvenida del chat
├── architecture.md           # Documentación técnica detallada
├── requirements.txt          # Dependencias Python
├── .env                      # Variables de entorno (NO commitear)
│
├── services/
│   ├── orchestrator.py       # Cerebro del agente (bucle de razonamiento)
│   ├── tools.py              # Definición de herramientas (Búsqueda, RAG, PPT)
│   ├── cypher.py             # Traductor de Lenguaje Natural a Cypher
│   ├── neo4j_queries.py      # Consultas predefinidas a la BBDD
│   ├── ppt_generation.py     # Lógica de generación de documentos
│   ├── embeddings.py         # Funciones de embedding
│   └── followups.py          # Generación de sugerencias de seguimiento
│
├── prompts/
│   ├── cypher_generation.txt # Prompt para generar Cypher
│   ├── ppt_generation_system.txt
│   └── ...
│
└── chat_utils/
    ├── text_utils.py         # Utilidades de texto (clip, formateo)
    ├── json_utils.py         # Parseo seguro de JSON
    └── prompt_loader.py      # Cargador de plantillas de prompts
```

---

## 🔧 Solución de Problemas

### El chatbot no encuentra contratos
1. Verifica que Neo4j esté corriendo y accesible.
2. Comprueba las credenciales en `.env`.
3. Asegúrate de que existen nodos `:ContratoRAG` con embeddings.

### Error "LLM connection refused"
1. Verifica que el servidor LLM esté corriendo.
2. Comprueba `LLM_BASE_URL` en `.env`.
3. Prueba la conexión manualmente:
   ```bash
   curl http://localhost:8000/v1/models
   ```

---

## 🤝 Contribuir

1. Fork del repositorio.
2. Crea una rama para tu feature: `git checkout -b feature/nueva-funcionalidad`.
3. Haz commit de tus cambios: `git commit -m 'Añade nueva funcionalidad'`.
4. Push a la rama: `git push origin feature/nueva-funcionalidad`.
5. Abre un Pull Request.

---

## 📄 Licencia

Este proyecto es propiedad de la **Diputación Provincial de Huelva**.
Desarrollado por el equipo de **Techfriendly**.

---

# Asistente RAG/Cypher de Contratos (Diputación Provincial de Huelva)

Este proyecto implementa un asistente conversacional para **consultar y explotar un grafo de contratación pública** (Neo4j) con dos modos principales:

1) **RAG (GraphRAG + Vector Search)** para responder preguntas apoyándose en contratos, capítulos y extractos ya indexados.  
2) **Cypher QA (solo lectura)** para preguntas agregadas (conteos, sumas, rankings, listados) generando y ejecutando consultas Cypher de forma segura.

Además, el asistente puede **generar un borrador de “Pliego de Prescripciones Técnicas (PPT)”**, inspirado en un PPT de referencia existente en el grafo.

---

## Qué puedes hacer

### 1) Preguntas tipo RAG
Responde basándose en evidencias recuperadas del grafo:

- “¿Hay contratos relacionados con Smart City?”
- “¿Qué cláusulas sociales aparecen en contratos de limpieza?”
- “¿Qué normativa se cita más en pliegos de determinados CPVs?”
- “¿Qué se exige en solvencia técnica en contratos de mantenimiento?”

El sistema recupera:

- **Contratos** (vector search sobre `:ContratoRAG`)
- **Capítulos** (vector search sobre `:Capitulo`)
- **Extractos** (vector search sobre `:Extracto`)

y construye una respuesta **sin inventar** datos fuera del contexto.

### 2) Preguntas tipo Cypher (agregaciones)
Para preguntas que implican cálculos o listados completos:

- “¿Cuántas veces se ha contratado a [empresa]?”
- “Suma el importe adjudicado de contratos con CPV X”
- “Saca una tabla con contratos de [tema]”

El asistente genera una query Cypher **solo lectura**, la valida para evitar escritura y la ejecuta.

### 3) Generación de PPT
Si detecta que quieres un pliego:

- “Redáctame un PPT para …”
- “Genera un pliego de prescripciones técnicas de …”

El asistente:
- Busca un **PPT de referencia** en el grafo.
- Sigue su **estructura de capítulos** e “inspira” la redacción capítulo a capítulo.
- Añade tras cada capítulo un bloque en cursiva:  
  _Recomendaciones para mejorar el pliego:_  
- Puede generar un **Word (.docx)** si `python-docx` está disponible.

---

## Evidencias y grafo en la barra lateral

La aplicación muestra una barra lateral “**Evidencias RAG usadas**” con:

- Resumen de contratos/capítulos/extractos usados
- Filtros activos (tipo de doc y tipos de extracto)
- Tokens aproximados enviados
- Panel desplegable de evidencias
- Botón **“Ver grafo”** (si el backend envía `graphData`)

El grafo se renderiza en un visor HTML (`/public/graph/sigma_viewer.html`) y permite:
- Visualización del subgrafo asociado a la evidencia
- Expansión por doble click (si el backend implementa `expand_graph_node`)

---

## Arquitectura

### Backend (Python)
- **Chainlit**: UI, streaming, sidebar, acciones
- **Neo4j Driver**: acceso a grafo (Bolt)
- **OpenAI-compatible LLM**: servidor local para chat completions (8002)
- **OpenAI-compatible embeddings**: servidor local de embeddings (8003)

### Frontend (Custom Elements)
- `public/elements/EvidencePanel.jsx`: sidebar con evidencias + popup grafo
- `public/graph/sigma_viewer.html`: visor de grafo (Sigma) en iframe

---

## Variables de entorno

### Neo4j
- `NEO4J_URI` (por defecto `bolt://host:7687`)
- `NEO4J_USER`
- `NEO4J_PASSWORD`
- `NEO4J_DB` (por defecto `huelva`)

### LLM (chat)
- `LLM_BASE_URL` (por defecto `http://host:8002/v1`)
- `LLM_API_KEY` (dummy por defecto)
- `LLM_MODEL` (por defecto `llm`)

### Embeddings
- `EMB_BASE_URL` (por defecto `http://host:8003/v1`)
- `EMB_API_KEY` (dummy por defecto)
- `EMB_MODEL` (por defecto `embedding`)
- `EMB_DIM` (por defecto `1024`)

### Parámetros RAG / UI
- `K_CONTRATOS` (por defecto `5`)
- `K_CAPITULOS` (por defecto `10`)
- `K_EXTRACTOS` (por defecto `25`)
- `MAX_HISTORY_TURNS` (por defecto `6`)
- `MODEL_MAX_CONTEXT_TOKENS` (por defecto `12288`)
- `RESERVE_FOR_ANSWER_TOKENS` (por defecto `1400`)
- `RAG_CONTEXT_MAX_TOKENS` (por defecto `5500`)
- `INTENT_REUSE_MAX_WORDS` (por defecto `4`)

---

## Cómo ejecutar

1) Instala dependencias:
```bash
pip install -r requirements.txt


import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"

function renderInline(text, keyPrefix) {
  // Render muy simple: **bold** y _italic_
  // Sin dangerouslySetInnerHTML.
  const parts = []
  let s = text || ""
  let i = 0
  while (s.length > 0) {
    const boldIdx = s.indexOf("**")
    const italIdx = s.indexOf("_")

    const next = [boldIdx, italIdx].filter(x => x >= 0).sort((a, b) => a - b)[0]
    if (next === undefined) {
      parts.push(<span key={`${keyPrefix}-t-${i}`}>{s}</span>)
      break
    }

    if (next > 0) {
      parts.push(<span key={`${keyPrefix}-t-${i}`}>{s.slice(0, next)}</span>)
      s = s.slice(next)
      i += 1
      continue
    }

    // next == 0
    if (s.startsWith("**")) {
      const end = s.indexOf("**", 2)
      if (end > 2) {
        const content = s.slice(2, end)
        parts.push(<strong key={`${keyPrefix}-b-${i}`}>{content}</strong>)
        s = s.slice(end + 2)
        i += 1
        continue
      }
    }

    if (s.startsWith("_")) {
      const end = s.indexOf("_", 1)
      if (end > 1) {
        const content = s.slice(1, end)
        parts.push(<em key={`${keyPrefix}-i-${i}`}>{content}</em>)
        s = s.slice(end + 1)
        i += 1
        continue
      }
    }

    // si no pudo parsear, consume 1 char
    parts.push(<span key={`${keyPrefix}-c-${i}`}>{s[0]}</span>)
    s = s.slice(1)
    i += 1
  }
  return parts
}

function renderMarkdown(md) {
  const lines = (md || "").split("\n")
  const out = []
  let listItems = []

  const flushList = (k) => {
    if (listItems.length > 0) {
      out.push(
        <ul key={`ul-${k}`} className="list-disc pl-5 space-y-1">
          {listItems}
        </ul>
      )
      listItems = []
    }
  }

  let blockKey = 0

  for (let idx = 0; idx < lines.length; idx++) {
    const raw = lines[idx]
    const line = (raw || "").trimRight()
    const trimmed = line.trim()

    if (!trimmed) {
      flushList(blockKey++)
      out.push(<div key={`sp-${blockKey++}`} className="h-2" />)
      continue
    }

    if (trimmed.startsWith("### ")) {
      flushList(blockKey++)
      out.push(
        <h3 key={`h3-${blockKey++}`} className="text-sm font-semibold">
          {renderInline(trimmed.slice(4), `h3-${idx}`)}
        </h3>
      )
      continue
    }

    if (trimmed.startsWith("## ")) {
      flushList(blockKey++)
      out.push(
        <h2 key={`h2-${blockKey++}`} className="text-base font-semibold">
          {renderInline(trimmed.slice(3), `h2-${idx}`)}
        </h2>
      )
      continue
    }

    if (trimmed.startsWith("# ")) {
      flushList(blockKey++)
      out.push(
        <h1 key={`h1-${blockKey++}`} className="text-lg font-semibold">
          {renderInline(trimmed.slice(2), `h1-${idx}`)}
        </h1>
      )
      continue
    }

    if (trimmed.startsWith("- ")) {
      listItems.push(
        <li key={`li-${idx}`} className="text-sm">
          {renderInline(trimmed.slice(2), `li-${idx}`)}
        </li>
      )
      continue
    }

    flushList(blockKey++)
    out.push(
      <p key={`p-${blockKey++}`} className="text-sm leading-5">
        {renderInline(trimmed, `p-${idx}`)}
      </p>
    )
  }

  flushList(blockKey++)
  return out
}

export default function EvidencePanel(props) {
  const title = props?.title || "Evidencias"
  const markdown = props?.markdown || ""
  const mode = props?.mode || "RAG"
  const tokens = props?.tokens || {}
  const filters = props?.filters || {}
  const counts = props?.counts || {}
  const context = props?.context || ""

  const sent = tokens?.sent_approx
  const budget = tokens?.budget

  return (
    <Card className="w-full h-full">
      <CardHeader className="pb-2">
        <div className="flex flex-col gap-2">
          <CardTitle className="text-base">{title}</CardTitle>
          <div className="flex flex-wrap gap-2">
            <Badge variant="outline">{mode}</Badge>
            {typeof counts?.contratos === "number" && <Badge variant="secondary">Contratos: {counts.contratos}</Badge>}
            {typeof counts?.capitulos === "number" && <Badge variant="secondary">Capítulos: {counts.capitulos}</Badge>}
            {typeof counts?.extractos === "number" && <Badge variant="secondary">Extractos: {counts.extractos}</Badge>}
            {typeof sent === "number" && <Badge variant="outline">Tokens enviados (aprox): {sent}</Badge>}
            {typeof budget === "number" && <Badge variant="outline">Budget: {budget}</Badge>}
          </div>

          {(filters && Object.keys(filters).length > 0) && (
            <div className="text-xs opacity-80">
              <span className="font-medium">Filtros:</span>{" "}
              {Object.entries(filters).map(([k, v], i) => (
                <span key={`f-${i}`} className="mr-2">
                  {k}={Array.isArray(v) ? v.join(",") : (v ?? "null")}
                </span>
              ))}
            </div>
          )}
        </div>
      </CardHeader>

      <Separator />

      <CardContent className="pt-3">
        <ScrollArea className="h-[70vh] pr-3"></ScrollArea>
        <div className="space-y-4">
            <div className="space-y-2">
              {renderMarkdown(markdown)}
            </div>

            {context && (
              <div className="space-y-2">
                <Separator />
                <h3 className="text-sm font-semibold">Contexto enviado al LLM</h3>
                <pre className="text-xs whitespace-pre-wrap font-mono leading-5 bg-muted p-2 rounded border border-border">
                  {context}
                </pre>
              </div>
            )}
          </div>
        </ScrollArea>
      </CardContent>
    </Card>
  )
}
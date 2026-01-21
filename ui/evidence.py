"""
UI EVIDENCE V2: evidence.py
Panel lateral de evidencias.
"""
import chainlit as cl


async def set_evidence_sidebar(title: str, markdown: str, props_extra: dict = None):
    """
    Muestra un panel lateral con evidencias/fuentes.
    """
    sidebar_html = f"""
    <div style="padding: 16px; font-family: sans-serif;">
        <h3 style="margin-top: 0; color: #333;">← {title}</h3>
        <div style="font-size: 14px; line-height: 1.5;">
            {markdown_to_html(markdown)}
        </div>
    </div>
    """
    
    # Chainlit sidebar via Text element
    # Para que aparezca en el sidebar, enviamos un mensaje vacío con un elemento Text configurado como "side"
    text_element = cl.Text(name=title, content=markdown, display="side")
    await cl.Message(content="", elements=[text_element]).send()


def markdown_to_html(md: str) -> str:
    """Conversión básica de markdown a HTML."""
    import re
    
    # Headers
    md = re.sub(r'^### (.+)$', r'<h4>\1</h4>', md, flags=re.MULTILINE)
    md = re.sub(r'^## (.+)$', r'<h3>\1</h3>', md, flags=re.MULTILINE)
    md = re.sub(r'^# (.+)$', r'<h2>\1</h2>', md, flags=re.MULTILINE)
    
    # Bold
    md = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', md)
    
    # Lists
    md = re.sub(r'^- (.+)$', r'<li>\1</li>', md, flags=re.MULTILINE)
    
    # Line breaks
    md = md.replace('\n\n', '<br><br>')
    
    return md


async def clear_evidence_sidebar():
    """Limpia el sidebar."""
    pass  # Chainlit no tiene clear nativo, se sobreescribe

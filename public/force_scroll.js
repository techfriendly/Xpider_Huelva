// force_scroll.js
// Script para forzar el autoscroll hacia abajo cuando hay nuevos mensajes
// Útil si la tabla es muy larga y Chainlit pierde el foco del final.

console.log("Cargando parche de autoscroll...");

const observer = new MutationObserver(() => {
    // Intentar hacer scroll al fondo de la página
    window.scrollTo({
        top: document.body.scrollHeight,
        behavior: 'smooth'
    });
});

// Observar cambios en el cuerpo del documento (cuando se añade contenido)
observer.observe(document.body, {
    childList: true,
    subtree: true,
    attributes: true,
    characterData: true
});

// También intentar hacerlo periódicamente si está escribiendo (clase 'thinking' o similar)
// pero el MutationObserver suele ser suficiente.

console.log("--- [ForceScroll V2] Loaded ---");

// Recursive function to find the deepest scrollable element with significant content
function findScrollable(element) {
    if (!element) return null;
    
    // Check if this element is scrollable
    const isScrollable = element.scrollHeight > element.clientHeight && element.clientHeight > 0;
    
    // We prefer the element that is likely the chat container (large height, in the middle)
    // Heuristic: content is larger than window height?
    if (isScrollable) {
        // Exclude sidebar if possible (sidebar usually has width < window width * 0.3)
        const rect = element.getBoundingClientRect();
        if (rect.width > window.innerWidth * 0.4) {
             return element;
        }
    }
    
    // Search children - we want the deepest scrollable one usually?
    // Actually, usually the chat container is a parent of the messages.
    // Let's iterate all divs in body.
    return null; 
}

function scrollChatToBottom() {
    // Strategy: Find ALL scrollable elements and scroll the one that looks like the main chat.
    const allDivs = document.querySelectorAll('div');
    let target = null;
    let maxScrollHeight = 0;

    allDivs.forEach(div => {
        const style = window.getComputedStyle(div);
        const overflowY = style.overflowY;
        const isScrollable = (overflowY === 'auto' || overflowY === 'scroll') && div.scrollHeight > div.clientHeight;
        
        if (isScrollable) {
             // Heuristic: The chat window is usually the largest scrollable area
             // and usually NOT the body (in React apps)
             if (div.scrollHeight > maxScrollHeight) {
                 // Ignore standard sidebar (often < 300px wide)
                 if (div.clientWidth > 400) { 
                     maxScrollHeight = div.scrollHeight;
                     target = div;
                 }
             }
        }
    });

    if (target) {
        console.log("[ForceScroll] Scrolling target:", target);
        target.scrollTop = target.scrollHeight;
    } else {
        // Fallback to window
        window.scrollTo(0, document.body.scrollHeight);
    }
}

// Observer
const observer = new MutationObserver((mutations) => {
    let shouldScroll = false;
    for (const mutation of mutations) {
        if (mutation.addedNodes.length > 0) {
            shouldScroll = true;
            break;
        }
    }
    
    if (shouldScroll) {
        // Multiple timeouts to catch render delays
        setTimeout(scrollChatToBottom, 50);
        setTimeout(scrollChatToBottom, 200);
        setTimeout(scrollChatToBottom, 500);
    }
});

observer.observe(document.body, {
    childList: true,
    subtree: true,
    attributes: false
});

// Initial kick
setInterval(scrollChatToBottom, 2000); // Verify every 2s for now to ensure it works
setTimeout(scrollChatToBottom, 1000);

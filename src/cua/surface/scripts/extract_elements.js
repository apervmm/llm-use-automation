(() => {
    const isVisible = (el) => el.offsetParent !== null;
  
    const hasStructuralChildren = (el) => {
      return Array.from(el.children).some(child =>
        !['BR', 'SPAN', 'B', 'I', 'EM', 'STRONG'].includes(child.tagName)
      );
    };
    

    const isLeafOrSelect = (el) => el.tagName === 'SELECT' || !hasStructuralChildren(el);


    const safeText = (node) => {
      if (!node || hasStructuralChildren(node)) return '';
      return node.innerText?.trim() || '';
    };
  


    const nearbyText = (el) => {
      let node = el.previousElementSibling;
      for (let i = 0; i < 2 && node; i++, node = node.previousElementSibling) {
        const text = safeText(node);
        if (text) return text;
      }
      let ancestor = el.parentElement;
      for (let level = 0; level < 2 && ancestor; level++, ancestor = ancestor.parentElement) {
        let prev = ancestor.previousElementSibling;
        for (let i = 0; i < 2 && prev; i++, prev = prev.previousElementSibling) {
          const text = safeText(prev);
          if (text) return text;
        }
      }
      const parentCell = el.closest('td');
      if (parentCell) {
        const text = safeText(parentCell.previousElementSibling);
        if (text) return text;
      }
      return '';
    };
  
    const nameOf = (el) => {
      return el.getAttribute('aria-label')
          || (el.id && document.querySelector(`label[for="${el.id}"]`)?.innerText.trim())
          || el.placeholder
          || el.value
          || nearbyText(el)
          || (!hasStructuralChildren(el) ? el.innerText?.trim() : '')
          || '';
    };
  
    const roleOf = (el) => {
      const tag = el.tagName.toLowerCase();
      if (tag === 'a') return 'link';
      if (tag === 'button') return 'button';
      if (tag === 'select') return 'combobox';
      if (tag === 'input') {
        const t = (el.type || 'text').toLowerCase();
        return (t === 'submit' || t === 'button') ? 'button' : 'textbox';
      }
      return 'other';
    };

    const cssSelectorFor = (el) => {
        if (el.id) return `#${CSS.escape(el.id)}`;
        const name = el.getAttribute('name');
        if (name) return `${el.tagName.toLowerCase()}[name="${CSS.escape(name)}"]`;
      
        const path = [];
        let node = el;
        while (node && node.nodeType === 1 && node !== document.body) {
          let selector = node.tagName.toLowerCase();
          const parent = node.parentElement;
          if (parent) {
            const siblings = Array.from(parent.children).filter(c => c.tagName === node.tagName);
            if (siblings.length > 1) {
              selector += `:nth-of-type(${siblings.indexOf(node) + 1})`;
            }
          }
          path.unshift(selector);
          node = parent;
        }
        return path.join(' > ');
    };
  
    return Array.from(document.querySelectorAll('a, button, input, select'))
        .filter(isVisible)
        // .filter(el => !hasStructuralChildren(el))
        .filter(isLeafOrSelect)
        .map(el => ({ 
            role: roleOf(el), 
            name: (nameOf(el) || '').trim(), 
            cssSelector: cssSelectorFor(el),
            options: el.tagName === 'SELECT' ? Array.from(el.options).map(o => o.value) : [],
        }))
        .filter(item => item.name);
  })();
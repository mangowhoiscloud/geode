/* GEODE Self-Improving Hub: progressive enhancement, loaded with `defer`.
 *
 * Every page is complete without this file. It only
 *   1. opens the Contents disclosure as a sidebar at the wide breakpoint,
 *   2. keeps table scroll regions focusable only while they actually scroll,
 *   3. adds a row filter above long record tables (rows are hidden, never removed).
 * No wheel, touch or scroll handlers: native scrolling stays untouched.
 * Contract: docs/design/self-improving-hub-system.md §5, §12, §13.
 */
(() => {
  'use strict';

  const wide = window.matchMedia('(min-width: 64rem)');
  const nav = document.querySelector('[data-hub-nav]');
  if (nav) {
    const summary = nav.querySelector('summary');
    const sync = () => {
      const focused = document.activeElement;
      nav.open = wide.matches;
      // A breakpoint change (resize, zoom) must not strand focus on a hidden element.
      if (!nav.open && focused !== summary && nav.contains(focused)) summary.focus();
      if (nav.open && focused === summary) {
        (nav.querySelector('[aria-current="page"]') || nav.querySelector('nav a')).focus();
      }
    };
    sync();
    wide.addEventListener('change', sync);
    nav.addEventListener('keydown', (event) => {
      if (event.key !== 'Escape' || wide.matches || !nav.open) return;
      nav.open = false;
      summary.focus();
    });
  }

  const fits = 'ResizeObserver' in window
    ? new ResizeObserver((entries) => {
      for (const { target } of entries) {
        if (target.scrollWidth > target.clientWidth + 1) target.tabIndex = 0;
        else if (target !== document.activeElement) target.removeAttribute('tabindex');
      }
    })
    : null;
  const watch = (region) => { if (fits) fits.observe(region); };

  // Markdown rendered in the browser (candidate viewer, evolver diff) gets the
  // scroll regions the build gives every other table.
  const wrapTables = (container) => {
    for (const table of container.querySelectorAll('table')) {
      if (table.parentElement.classList.contains('table-scroll')) continue;
      const region = document.createElement('div');
      region.className = 'table-scroll';
      region.setAttribute('role', 'region');
      region.setAttribute('aria-label', 'Markdown table');
      region.tabIndex = 0;
      table.before(region);
      region.append(table);
      watch(region);
    }
  };
  // Each client-rendered container watches only its own children, so a render
  // that lands after this script still gets wrapped; no global polling.
  for (const container of document.querySelectorAll('.markdown-body[data-md-target]')) {
    wrapTables(container);
    new MutationObserver(() => wrapTables(container)).observe(container, { childList: true });
  }

  const regions = document.querySelectorAll('.table-scroll');
  regions.forEach(watch);

  // ponytail: substring match over row text; add per-column filters if readers ask for them.
  const MIN_ROWS = 8;
  let filters = 0;
  for (const region of regions) {
    const table = region.querySelector(':scope > table.records');
    if (!table || !table.tBodies[0] || region.closest('details.turn, td')) continue;
    const groups = [];
    for (const row of table.tBodies[0].rows) {
      // A mutation's payload drill-down row travels with the row above it.
      if (row.classList.contains('mutation-payload-row') && groups.length) groups[groups.length - 1].push(row);
      else groups.push([row]);
    }
    const total = groups.length;
    if (total < MIN_ROWS) continue;

    filters += 1;
    const box = document.createElement('div');
    box.className = 'table-filter';
    const label = document.createElement('label');
    label.htmlFor = `hub-filter-${filters}`;
    label.textContent = 'Filter rows';
    const context = document.createElement('span');
    context.className = 'visually-hidden';
    context.textContent = ` in ${region.getAttribute('aria-label') || 'this table'}`;
    label.append(context);
    const input = document.createElement('input');
    input.id = label.htmlFor;
    input.type = 'search';
    input.autocomplete = 'off';
    input.spellcheck = false;
    const status = document.createElement('p');
    status.className = 'table-filter-status';
    status.setAttribute('role', 'status');
    // Set before insertion: shown from first render, not announced on load.
    status.textContent = `${total} rows.`;
    input.setAttribute('aria-describedby', `${input.id}-status`);
    status.id = `${input.id}-status`;
    box.append(label, input, status);
    region.before(box);

    const texts = groups.map((group) => group.map((row) => row.textContent).join(' ').toLowerCase());
    let announce = 0;
    const apply = () => {
      const query = input.value.trim();
      const needle = query.toLowerCase();
      let shown = 0;
      groups.forEach((group, i) => {
        const hit = !needle || texts[i].includes(needle);
        if (hit) shown += 1;
        for (const row of group) row.hidden = !hit;
      });
      // Announce once typing pauses, not on every keystroke.
      clearTimeout(announce);
      announce = setTimeout(() => {
        if (!needle) status.textContent = `Showing all ${total} rows.`;
        else if (shown) status.textContent = `Showing ${shown} of ${total} rows.`;
        else status.textContent = `No rows match "${query}". Clear the filter to show all ${total} rows.`;
      }, 300);
    };
    input.addEventListener('input', apply);
    input.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && input.value) {
        input.value = '';
        apply();
      }
    });
  }
})();

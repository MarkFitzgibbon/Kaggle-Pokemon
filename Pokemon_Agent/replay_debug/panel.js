(() => {
  const frames = JSON.parse(document.getElementById('pokemon-debug-data').textContent);
  let lastStep = null;
  const element = (tag, text, className) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  };
  window.renderPokemonDebug = (step) => {
    if (step === lastStep) return;
    if (!document.body) return;
    lastStep = step;
    let panel = document.getElementById('pokemon-debug');
    if (!panel) {
      panel = element('aside'); panel.id = 'pokemon-debug';
      panel.setAttribute('aria-label', 'Battle decisions');
      document.body.appendChild(panel);
    }
    panel.replaceChildren(element('h2', 'Battle decisions'));
    const frame = frames[step];
    if (!frame) {
      panel.append(element('p', 'No decision data for this replay frame.', 'muted'));
      return;
    }
    panel.append(element('p', `Game ${frame.game} · ${frame.turn === 0 ? 'Setup (turn 0)' : 'Turn ' + frame.turn}`));
    panel.append(element('p', `Replay step ${step + 1} / ${frames.length}`, 'muted'));
    if (frame.result) {
      panel.append(element('h3', frame.result));
      panel.append(element('p', 'Game finished. No options available.', 'muted'));
      return;
    }
    panel.append(element('h3', frame.agent));
    panel.append(element('p', frame.context));
    panel.append(element('p', `Choose ${frame.minimum}–${frame.maximum} options. Indices start at 0.`, 'muted'));
    const choice = Array.isArray(frame.chosen) ? frame.chosen : [];
    panel.append(element('p', frame.chosen === null ? 'Submitted choice unavailable.' : `Chosen indices: [${choice.join(', ')}]`));
    const table = element('table');
    const header = element('tr');
    header.append(element('th', 'Index'), element('th', 'Available move'));
    const head = element('thead'); head.append(header); table.append(head);
    const body = element('tbody');
    for (const option of frame.options) {
      const selected = choice.includes(option.index);
      const row = element('tr', undefined, selected ? 'chosen' : '');
      const description = element('td', option.description);
      if (selected) description.append(element('span', 'Chosen', 'badge'));
      const details = element('details');
      details.append(element('summary', 'Raw option'), element('pre', JSON.stringify(option.raw, null, 2)));
      description.append(details);
      row.append(element('td', `[${option.index}]`), description);
      body.append(row);
    }
    table.append(body); panel.append(table);
    panel.append(element('h3', frame.inactive_agent));
    panel.append(element('p', 'Waiting — no decision requested at this step.', 'muted'));
  };
})();

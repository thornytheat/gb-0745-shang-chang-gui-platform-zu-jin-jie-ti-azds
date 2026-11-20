const container = document.querySelector('#change-rows');
const form = document.querySelector('#correction-form');
const feedback = document.querySelector('#correction-feedback');

function yuanFromCents(cents) {
  return cents === null ? null : (cents / 100).toString();
}

function tierText(tiers) {
  return tiers
    .map(([limit, points]) => `${limit === null ? '无上限' : yuanFromCents(limit)} 元 → ${points / 100}%`)
    .join('；');
}

function renderRows() {
  const contracts = JSON.parse(container.dataset.contracts);
  contracts.forEach((contract) => {
    const card = document.createElement('fieldset');
    card.className = 'change-card';
    card.dataset.shop = contract['柜台'];
    card.dataset.version = contract['版本'];
    card.dataset.floor = contract['月保底分'];
    card.dataset.tiers = JSON.stringify(contract['阶梯档']);
    card.innerHTML = `
      <legend>${contract['柜台']} · ${contract['版本']} <small>${contract['起始']} 至 ${contract['截止']}</small></legend>
      <label>新月保底 · 元（留空不改）
        <input data-field="minimum" type="text" inputmode="decimal"
               placeholder="原保底 ${yuanFromCents(contract['月保底分'])}">
      </label>
      <label>新阶梯 JSON（留空不改）
        <textarea data-field="tiers" rows="2"
          placeholder='原阶梯 ${tierText(contract['阶梯档'])}'></textarea>
      </label>`;
    container.appendChild(card);
  });
}

function collectPayload() {
  const changes = [];
  for (const card of container.querySelectorAll('.change-card')) {
    const change = { shop: card.dataset.shop, version: card.dataset.version };
    let touched = false;
    const minimum = card.querySelector('[data-field="minimum"]').value.trim();
    if (minimum) {
      change.minimum = minimum;
      touched = true;
    }
    const tiersText = card.querySelector('[data-field="tiers"]').value.trim();
    if (tiersText) {
      change.tiers = JSON.parse(tiersText);
      touched = true;
    }
    if (touched) changes.push(change);
  }
  const payload = { source: form.elements.source.value, changes };
  const effective = form.elements.effective.value;
  if (effective) payload.effective = effective;
  const reason = form.elements.reason.value.trim();
  if (reason) payload.reason = reason;
  return payload;
}

renderRows();

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  delete feedback.dataset.error;
  feedback.value = '正在生成更正结算…';
  form.querySelector('button').disabled = true;
  try {
    const payload = collectPayload();
    if (!payload.changes.length) {
      throw new Error('请至少在一个合同中填写新保底或新阶梯。');
    }
    const response = await fetch('/api/corrections', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || '更正生成失败，已保留旧版。');
    window.location.assign(data.location);
  } catch (error) {
    feedback.dataset.error = '';
    feedback.value = error.message || '请求失败，请重试。';
    form.querySelector('button').disabled = false;
  }
});

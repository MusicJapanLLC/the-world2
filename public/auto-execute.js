(() => {
  'use strict';

  const EXECUTION_INTENT = /(?:作って|作れ|作成して|実装して|実装しろ|開発して|開発しろ|直して|直せ|修正して|修正しろ|改修して|改修しろ|デプロイして|デプロイしろ|公開して|公開しろ|リリースして|リリースしろ|実行して|実行しろ|\bbuild\b|\bdeploy\b|\bimplement\b|\bship\b|\bfix\b)/i;
  let armed = false;
  let lastIntent = '';
  let dispatching = false;

  const $ = (selector) => document.querySelector(selector);

  function terminal(message, type = 'RUN') {
    const el = $('#terminal');
    if (!el) return;
    const time = new Date().toLocaleTimeString('ja-JP', {
      hour: '2-digit', minute: '2-digit', second: '2-digit'
    });
    el.textContent += `[${time}] ${type}  ${message}\n`;
    el.scrollTop = el.scrollHeight;
  }

  function captureIntent() {
    const composer = $('#composer');
    const text = String(composer?.value || '').trim();
    if (!text || !EXECUTION_INTENT.test(text)) return;
    armed = true;
    lastIntent = text.slice(0, 240);
    terminal('AUTO EXECUTE ARMED · explicit build/deploy intent detected');
  }

  function maybeDispatch() {
    if (!armed || dispatching) return;
    const send = $('#sendBtn');
    const run = $('#runPipeline');
    if (!send || !run || send.disabled || run.disabled) return;

    dispatching = true;
    armed = false;
    terminal('AUTO EXECUTE -> forcing real execution queue');

    // Let the chat handler finish persisting the assistant reply first.
    setTimeout(() => {
      try {
        run.click();
        terminal(`AUTO EXECUTE DISPATCHED · ${lastIntent}`);
      } finally {
        dispatching = false;
        lastIntent = '';
      }
    }, 80);
  }

  // Capture before app.js clears the composer.
  document.addEventListener('click', (event) => {
    if (event.target?.closest?.('#sendBtn')) captureIntent();
  }, true);

  document.addEventListener('keydown', (event) => {
    if (event.target?.matches?.('#composer') && event.key === 'Enter' && !event.shiftKey) {
      captureIntent();
    }
  }, true);

  const observer = new MutationObserver(maybeDispatch);
  const boot = () => {
    const send = $('#sendBtn');
    if (!send) return setTimeout(boot, 50);
    observer.observe(send, { attributes: true, attributeFilter: ['disabled'] });
    terminal('auto-execute guard: ON · explicit creation/deploy requests cannot end as chat-only promises');
  };
  boot();
})();

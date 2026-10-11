/* CyberAI Pro — AI chat: streaming javoblar, suhbatlar (threadlar), markdown, kod bloklari, rasm yuborish */
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const form = $('chat-form');
  if (!form) return;
  const input = $('aiInput'), display = $('chat-display'), historyList = $('history-list');
  const sendBtn = $('sendBtn'), stopBtn = $('stopBtn'), historySearch = $('history-search'), folderFilter = $('history-folder-filter');
  const imageInput = $('imageInput'), attachBtn = $('attachBtn'), preview = $('image-preview');
  const previewImg = $('image-preview-img'), previewName = $('image-preview-name'), removeImage = $('remove-image');
  const csrf = document.querySelector('meta[name=csrf-token]')?.content || '';
  const FOLDERS = ['Umumiy', 'Kod', 'Kiberxavfsizlik', 'O‘qish', 'Loyiha'];
  const welcome = display.innerHTML;
  let threads = [], currentThread = null, selectedImage = null, controller = null, busy = false, followLatest = true;

  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  /* ---------- scroll ---------- */
  const jump = document.createElement('button');
  jump.type = 'button'; jump.className = 'jump-latest'; jump.textContent = '↓ Yangi javobga o‘tish'; jump.hidden = true;
  display.parentElement.appendChild(jump);
  const nearBottom = () => display.scrollHeight - display.scrollTop - display.clientHeight < 80;
  function toBottom(force) {
    if (force) followLatest = true;
    if (!followLatest) { jump.hidden = false; return; }
    requestAnimationFrame(() => { display.scrollTop = display.scrollHeight; jump.hidden = true; });
  }
  display.addEventListener('scroll', () => { followLatest = nearBottom(); jump.hidden = followLatest; });
  jump.addEventListener('click', () => toBottom(true));

  /* ---------- markdown + kod ---------- */
  function inline(s) {
    s = esc(s);
    s = s.replace(/`([^`\n]+)`/g, '<code class="md-code">$1</code>');
    s = s.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
    s = s.replace(/(^|[^*\w])\*([^*\n]+)\*(?!\w)/g, '$1<em>$2</em>');
    return s;
  }
  function textToHtml(text) {
    const lines = String(text).replace(/\r/g, '').split('\n'), out = [];
    let list = null, para = [];
    const flushPara = () => { if (para.length) { out.push('<p>' + para.map(inline).join('<br>') + '</p>'); para = []; } };
    const flushList = () => { if (list) { out.push('<' + list.t + '>' + list.i.map((x) => '<li>' + inline(x) + '</li>').join('') + '</' + list.t + '>'); list = null; } };
    lines.forEach((raw) => {
      const l = raw.replace(/\s+$/, ''); let m;
      if (!l.trim()) { flushPara(); flushList(); return; }
      if ((m = l.match(/^\s{0,3}(#{1,4})\s+(.*)$/))) { flushPara(); flushList(); const n = Math.min(5, m[1].length + 1); out.push('<h' + n + '>' + inline(m[2]) + '</h' + n + '>'); return; }
      if ((m = l.match(/^\s*[-*•]\s+(.*)$/))) { flushPara(); if (!list || list.t !== 'ul') { flushList(); list = { t: 'ul', i: [] }; } list.i.push(m[1]); return; }
      if ((m = l.match(/^\s*\d+[.)]\s+(.*)$/))) { flushPara(); if (!list || list.t !== 'ol') { flushList(); list = { t: 'ol', i: [] }; } list.i.push(m[1]); return; }
      flushList(); para.push(l);
    });
    flushPara(); flushList();
    return out.join('');
  }
  function highlightCode(node, source) {
    const KW = 'const|let|var|function|return|if|else|for|while|class|new|async|await|try|catch|finally|throw|import|from|export|default|def|in|is|not|and|or|True|False|None|print|pass|break|continue|public|private|static|void|int|string|bool';
    const SQL = 'SELECT|FROM|WHERE|INSERT|UPDATE|DELETE|CREATE|TABLE|JOIN|ON|AS|AND|OR';
    const re = new RegExp('(\\/\\*[\\s\\S]*?\\*\\/|\\/\\/[^\\n]*|#[^\\n]*|\\b(?:' + KW + '|' + SQL + ')\\b|\\b\\d+(?:\\.\\d+)?\\b|(?:"(?:[^"\\\\]|\\\\.)*"|\'(?:[^\'\\\\]|\\\\.)*\'|`(?:[^`\\\\]|\\\\.)*`)|\\b[A-Za-z_$][\\w$]*(?=\\s*\\())', 'g');
    const kwRe = new RegExp('^(?:' + KW + ')$'), sqlRe = new RegExp('^(?:' + SQL + ')$');
    let last = 0, m;
    while ((m = re.exec(source)) !== null) {
      if (m.index > last) node.appendChild(document.createTextNode(source.slice(last, m.index)));
      const span = document.createElement('span'); span.textContent = m[0];
      let cls = 'tok-function';
      if (/^(\/\*|\/\/|#)/.test(m[0])) cls = 'tok-comment';
      else if (/^["'`]/.test(m[0])) cls = 'tok-string';
      else if (/^\d/.test(m[0])) cls = 'tok-number';
      else if (sqlRe.test(m[0])) cls = 'tok-sql';
      else if (kwRe.test(m[0])) cls = 'tok-keyword';
      span.className = cls; node.appendChild(span); last = re.lastIndex;
    }
    if (last < source.length) node.appendChild(document.createTextNode(source.slice(last)));
  }
  function addText(bubble, t) {
    if (!t.trim()) return;
    const d = document.createElement('div'); d.className = 'answer-md'; d.innerHTML = textToHtml(t); bubble.appendChild(d);
  }
  function addCode(bubble, lang, code) {
    const wrap = document.createElement('div'); wrap.className = 'code-wrap';
    const bar = document.createElement('div'); bar.className = 'code-bar';
    const label = document.createElement('span'); label.textContent = (lang || '').trim() || 'code';
    const copy = document.createElement('button'); copy.type = 'button'; copy.className = 'copy-code'; copy.textContent = 'Nusxalash';
    copy.addEventListener('click', async () => {
      try { await navigator.clipboard.writeText(code); copy.textContent = 'Nusxalandi ✓'; setTimeout(() => (copy.textContent = 'Nusxalash'), 1400); }
      catch (_) { copy.textContent = 'Kodni belgilab nusxalang'; }
    });
    bar.append(label, copy);
    const pre = document.createElement('pre'), c = document.createElement('code');
    highlightCode(c, code.replace(/\n$/, '')); pre.appendChild(c); wrap.append(bar, pre); bubble.appendChild(wrap);
  }
  function renderAnswer(bubble, text) {
    bubble.replaceChildren();
    const re = /```([^\n`]*)\n([\s\S]*?)(?:```|$)/g; // oxirigacha yopilmagan blok ham ko'rsatiladi (streaming paytida)
    let last = 0, m;
    while ((m = re.exec(text)) !== null) {
      if (m.index > last) addText(bubble, text.slice(last, m.index));
      addCode(bubble, m[1], m[2]); last = re.lastIndex;
      if (m[0].length === 0) re.lastIndex++;
    }
    if (last < text.length) addText(bubble, text.slice(last));
  }
  function note(bubble, text) { const p = document.createElement('p'); p.className = 'answer-note'; p.textContent = text; bubble.appendChild(p); }

  /* ---------- xabarlar ---------- */
  function addMessage(role, text, opts) {
    opts = opts || {};
    display.querySelector('.welcome-block')?.remove();
    const el = document.createElement('div');
    el.className = 'message ' + role + (opts.pending ? ' pending' : '');
    el.innerHTML = '<div class="role">' + (role === 'user' ? 'SIZ' : 'CYBERAI PRO') + '</div><div class="bubble"></div>';
    const bubble = el.querySelector('.bubble');
    if (opts.pending) bubble.innerHTML = '<span class="typing" aria-label="Javob tayyorlanmoqda"><i></i><i></i><i></i></span>';
    else if (role === 'assistant') renderAnswer(bubble, text || '');
    else bubble.textContent = text;
    if (opts.imageUrl && role === 'user') { const im = document.createElement('img'); im.className = 'sent-image'; im.src = opts.imageUrl; im.alt = 'Yuborilgan rasm'; bubble.appendChild(im); }
    display.appendChild(el); toBottom();
    return el;
  }

  /* ---------- suhbatlar ro'yxati ---------- */
  function fmtTime(s) {
    if (!s) return '';
    const d = new Date(String(s).replace(' ', 'T') + 'Z');
    if (isNaN(d)) return s;
    const now = new Date();
    if (d.toDateString() === now.toDateString()) return d.toLocaleTimeString('uz-UZ', { hour: '2-digit', minute: '2-digit' });
    if (d.toDateString() === new Date(now - 86400000).toDateString()) return 'Kecha';
    return d.getDate() + ' ' + ['Yan', 'Fev', 'Mar', 'Apr', 'May', 'Iyn', 'Iyl', 'Avg', 'Sen', 'Okt', 'Noy', 'Dek'][d.getMonth()];
  }
  async function api(url, opts) {
    const r = await fetch(url, Object.assign({ headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf } }, opts || {}));
    let data = {}; try { data = await r.json(); } catch (_) {}
    if (!r.ok) throw new Error(data.error || 'Server xatosi (' + r.status + ')');
    return data;
  }
  function threadEl(t) {
    const wrap = document.createElement('div');
    wrap.className = 'history-item-wrap' + (t.id === currentThread ? ' active' : '');
    wrap.dataset.folder = t.folder || 'Umumiy'; wrap.dataset.thread = t.id;
    const btn = document.createElement('button'); btn.type = 'button'; btn.className = 'history-entry'; btn.title = t.title;
    btn.innerHTML = '<b>' + esc(t.title.length > 62 ? t.title.slice(0, 62) + '…' : t.title) + '</b><small>' + esc(fmtTime(t.created_at)) + (t.count > 1 ? ' · ' + t.count + ' xabar' : '') + '</small>';
    btn.addEventListener('click', () => openThread(t.id));
    const tools = document.createElement('div'); tools.className = 'history-item-tools';
    const del = document.createElement('button'); del.type = 'button'; del.className = 'history-del'; del.title = 'Suhbatni o‘chirish'; del.setAttribute('aria-label', 'Suhbatni o‘chirish'); del.textContent = '🗑';
    del.addEventListener('click', async () => {
      if (!confirm('Bu suhbat o‘chirilsinmi?')) return;
      try { await api('/api/threads/' + t.id, { method: 'DELETE' }); if (currentThread === t.id) newChat(); loadThreads(historySearch.value.trim()); }
      catch (e) { alert(e.message); }
    });
    tools.append(del); wrap.append(btn, tools);
    return wrap;
  }
  function renderThreads(q) {
    historyList.innerHTML = '';
    if (!threads.length) { historyList.innerHTML = '<p class="muted">' + (q ? 'Mos suhbat topilmadi.' : 'Hozircha tarix bo‘sh.') + '</p>'; return; }
    threads.forEach((t) => historyList.appendChild(threadEl(t)));
    applyFolder();
  }
  async function loadThreads(q) {
    try { threads = await api('/api/threads?q=' + encodeURIComponent(q || '')); renderThreads(q); } catch (_) {}
  }
  function applyFolder() {
    const f = folderFilter?.value || 'all'; let shown = 0;
    historyList.querySelectorAll('.history-item-wrap').forEach((el) => { const ok = f === 'all' || el.dataset.folder === f; el.hidden = !ok; if (ok) shown++; });
    let empty = historyList.querySelector('.folder-empty');
    if (f !== 'all' && shown === 0 && threads.length) {
      if (!empty) { empty = document.createElement('p'); empty.className = 'muted folder-empty'; empty.textContent = 'Bu papkada hozircha suhbat yo‘q.'; historyList.appendChild(empty); }
    } else if (empty) empty.remove();
  }
  function markActive() {
    historyList.querySelectorAll('.history-item-wrap').forEach((el) => el.classList.toggle('active', Number(el.dataset.thread) === currentThread));
  }
  async function openThread(id) {
    if (busy) return;
    try {
      const d = await api('/api/threads/' + id);
      display.innerHTML = '';
      d.messages.forEach((m) => { addMessage('user', m.question); addMessage('assistant', m.answer || 'Bu suhbat uchun saqlangan javob yo‘q.'); });
      currentThread = id; markActive(); toBottom(true);
      $('cai-nav')?.classList.remove('open');
    } catch (e) { alert(e.message); }
  }
  function newChat() {
    if (busy) return;
    display.innerHTML = welcome; currentThread = null; followLatest = true; jump.hidden = true;
    input.value = ''; autosize(); clearImage(); markActive(); input.focus();
  }

  /* ---------- yuborish (streaming) ---------- */
  function updateUsage(u) {
    const c = $('usage-count'), r = $('usage-remaining');
    if (c) c.textContent = u.used + '/' + u.limit;
    if (r) r.textContent = u.remaining;
  }
  function setBusy(b) {
    busy = b; sendBtn.disabled = b; sendBtn.textContent = b ? '…' : '↑';
    if (attachBtn) attachBtn.disabled = b;
    if (stopBtn) stopBtn.hidden = !b;
  }
  async function send(textArg) {
    const text = (textArg == null ? input.value : textArg).trim();
    if ((!text && !selectedImage) || busy) return;
    const image = selectedImage; followLatest = true;
    addMessage('user', text || 'Ushbu rasmni tahlil qil.', { imageUrl: image ? image.data : null });
    if (image) clearImage();
    input.value = ''; autosize(); setBusy(true);
    const pending = addMessage('assistant', '', { pending: true });
    const bubble = pending.querySelector('.bubble');
    controller = new AbortController();
    let answer = '', raf = 0;
    const paint = () => { raf = 0; if (!answer) return; pending.classList.remove('pending'); renderAnswer(bubble, answer); toBottom(); };
    try {
      const r = await fetch('/ask', {
        method: 'POST', signal: controller.signal,
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
        body: JSON.stringify({ question: text, image: image ? image.data : null, thread_id: currentThread, stream: true })
      });
      if (!r.ok || !(r.headers.get('content-type') || '').includes('text/event-stream')) {
        let data = {}; try { data = await r.json(); } catch (_) {}
        if (data.usage) updateUsage(data.usage);
        throw new Error(data.error || 'Server xatosi (' + r.status + ')');
      }
      const reader = r.body.getReader(), dec = new TextDecoder(); let buf = '';
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let i;
        while ((i = buf.indexOf('\n\n')) >= 0) {
          const block = buf.slice(0, i); buf = buf.slice(i + 2);
          const line = block.split('\n').find((l) => l.startsWith('data:'));
          if (!line) continue;
          let ev; try { ev = JSON.parse(line.slice(5)); } catch (_) { continue; }
          if (ev.start && ev.thread_id) currentThread = ev.thread_id;
          else if (ev.delta) { answer += ev.delta; if (!raf) raf = requestAnimationFrame(paint); }
          else if (ev.error) throw new Error(ev.error);
          else if (ev.done) { if (ev.usage) updateUsage(ev.usage); if (ev.thread_id) currentThread = ev.thread_id; }
        }
      }
      if (raf) cancelAnimationFrame(raf);
      if (!answer) throw new Error('AI javob qaytarmadi.');
      pending.classList.remove('pending'); renderAnswer(bubble, answer); toBottom();
    } catch (e) {
      if (raf) cancelAnimationFrame(raf);
      pending.classList.remove('pending');
      const msg = e.name === 'AbortError' ? 'Javob to‘xtatildi.' : (e.message || 'Server bilan aloqa uzildi.');
      if (answer) { renderAnswer(bubble, answer); note(bubble, msg); }
      else { bubble.textContent = msg; if (e.name !== 'AbortError') bubble.classList.add('is-error'); }
    } finally {
      setBusy(false); controller = null; input.focus();
      loadThreads(historySearch ? historySearch.value.trim() : '').then(markActive);
    }
  }

  /* ---------- rasm ---------- */
  function clearImage() { selectedImage = null; if (imageInput) imageInput.value = ''; if (preview) preview.hidden = true; if (previewImg) previewImg.removeAttribute('src'); }
  attachBtn?.addEventListener('click', () => imageInput.click());
  imageInput?.addEventListener('change', () => {
    const f = imageInput.files && imageInput.files[0]; if (!f) return;
    if (!/^image\/(png|jpeg|webp)$/.test(f.type)) { alert('Faqat PNG, JPG yoki WEBP rasm tanlang.'); clearImage(); return; }
    if (f.size > 5 * 1024 * 1024) { alert('Rasm hajmi 5 MB dan oshmasin.'); clearImage(); return; }
    const fr = new FileReader();
    fr.onload = () => { selectedImage = { data: fr.result, name: f.name }; previewImg.src = fr.result; previewName.textContent = f.name; preview.hidden = false; };
    fr.readAsDataURL(f);
  });
  removeImage?.addEventListener('click', clearImage);

  /* ---------- hodisalar ---------- */
  function autosize() { input.style.height = 'auto'; input.style.height = Math.min(input.scrollHeight, 200) + 'px'; }
  input.addEventListener('input', autosize);
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); } });
  form.addEventListener('submit', (e) => { e.preventDefault(); send(); });
  stopBtn?.addEventListener('click', () => controller && controller.abort());
  $('new-chat')?.addEventListener('click', newChat);
  $('clear-chat')?.addEventListener('click', newChat);
  folderFilter?.addEventListener('change', applyFolder);
  let t = 0;
  historySearch?.addEventListener('input', () => { clearTimeout(t); t = setTimeout(() => loadThreads(historySearch.value.trim()), 250); });
  $('clear-history')?.addEventListener('click', async () => {
    if (!confirm('Barcha saqlangan suhbat tarixini o‘chirasizmi?')) return;
    try { await api('/api/history/clear', { method: 'POST' }); threads = []; renderThreads(''); newChat(); } catch (e) { alert(e.message); }
  });
  loadThreads('');
})();

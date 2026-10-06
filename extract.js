// Достаём текст из PDF / EPUB / TXT и режем на куски для озвучки.
const CDN = 'https://cdnjs.cloudflare.com/ajax/libs/';
export const LIBS = [
  CDN + 'pdf.js/3.11.174/pdf.min.js',
  CDN + 'pdf.js/3.11.174/pdf.worker.min.js',
  CDN + 'jszip/3.10.1/jszip.min.js',
];
const CHUNK = 1500;

function loadScript(src) {
  return new Promise((ok, fail) => {
    if (document.querySelector(`script[src="${src}"]`)) return ok();
    const s = document.createElement('script');
    s.src = src; s.onload = ok; s.onerror = () => fail(new Error('Не загрузилась библиотека: ' + src));
    document.head.appendChild(s);
  });
}

export async function extractText(file) {
  const name = file.name.toLowerCase();
  if (name.endsWith('.pdf')) return fromPdf(file);
  if (name.endsWith('.epub')) return fromEpub(file);
  return file.text();
}

async function fromPdf(file) {
  await loadScript(LIBS[0]);
  pdfjsLib.GlobalWorkerOptions.workerSrc = LIBS[1];
  const pdf = await pdfjsLib.getDocument({ data: await file.arrayBuffer() }).promise;
  const pages = [];
  for (let p = 1; p <= pdf.numPages; p++) {
    const { items } = await (await pdf.getPage(p)).getTextContent();
    let page = '';
    for (const it of items) page += it.str + (it.hasEOL ? '\n' : '');
    // номер страницы отдельной строкой — не читаем
    pages.push(page.split('\n').filter(l => !/^\s*\d{1,4}\s*$/.test(l)).join('\n'));
  }
  return pages.join('\n');
}

async function fromEpub(file) {
  await loadScript(LIBS[2]);
  const zip = await JSZip.loadAsync(file);
  const xml = async path => new DOMParser().parseFromString(await zip.file(path).async('text'), 'application/xml');
  const opfPath = (await xml('META-INF/container.xml')).querySelector('rootfile').getAttribute('full-path');
  const opf = await xml(opfPath);
  const base = opfPath.includes('/') ? opfPath.slice(0, opfPath.lastIndexOf('/') + 1) : '';
  const items = {};
  opf.querySelectorAll('manifest > item').forEach(i => (items[i.getAttribute('id')] = i.getAttribute('href')));
  const parts = [];
  for (const ref of opf.querySelectorAll('spine > itemref')) {
    const href = items[ref.getAttribute('idref')];
    const f = href && zip.file(decodeURIComponent(base + href));
    if (!f) continue;
    const doc = new DOMParser().parseFromString(await f.async('text'), 'text/html');
    const blocks = doc.body.querySelectorAll('p, h1, h2, h3, h4, h5, h6, li, blockquote');
    parts.push(blocks.length ? [...blocks].map(b => b.textContent).join('\n') : doc.body.textContent);
  }
  return parts.join('\n');
}

// Чистим и режем на куски ≤ CHUNK символов по абзацам и предложениям.
export function toChunks(raw) {
  const text = raw
    .replace(/(\p{L})-\n(\p{Ll})/gu, '$1$2') // перенос слова в PDF: «сло-\nво»
    .replace(/[ \t ]+/g, ' ');
  const paras = text.split(/\n+/).map(s => s.trim()).filter(Boolean);
  const chunks = [];
  let cur = '';
  const push = s => {
    if (cur && cur.length + s.length + 1 > CHUNK) { chunks.push(cur); cur = ''; }
    cur = cur ? cur + (/[.!?…:;»"]$/.test(cur) ? '\n' : ' ') + s : s;
  };
  for (const p of paras) {
    if (p.length <= CHUNK) { push(p); continue; }
    for (const s of p.match(/[^.!?…]+[.!?…]*\s*/g)) {
      if (s.length <= CHUNK) push(s.trim());
      else for (let i = 0; i < s.length; i += CHUNK) push(s.slice(i, i + CHUNK));
    }
  }
  if (cur) chunks.push(cur);
  return chunks;
}

export function detectLang(text) {
  const sample = text.slice(0, 5000);
  const cyr = (sample.match(/[а-яё]/gi) || []).length;
  const lat = (sample.match(/[a-zăâîșşțţ]/gi) || []).length;
  return cyr > lat ? 'ru' : 'ro';
}

const STATUS_LABELS = { ok: "Готово после вычитки", needs_review: "Требует проверки" };
const SOURCE_LABELS = { specs: "из характеристик", description: "из описания", none: "нет данных" };
const TITLE_MAX = 70;
const DESCRIPTION_MIN = 800;
const DESCRIPTION_MAX = 1200;

const state = { runId: 0, source: "", products: [], items: {}, active: null, maxBytes: 50 * 1024 * 1024 };

const $ = (id) => document.getElementById(id);

function el(tag, options = {}, children = []) {
  const node = document.createElement(tag);
  if (options.className) node.className = options.className;
  if (options.text !== undefined) node.textContent = options.text;
  if (options.attrs) Object.entries(options.attrs).forEach(([key, value]) => node.setAttribute(key, value));
  if (options.onClick) node.addEventListener("click", options.onClick);
  children.forEach((child) => node.appendChild(child));
  return node;
}

function errorText(body, status) {
  if (body && typeof body.detail === "string") return body.detail;
  if (body && Array.isArray(body.detail)) return body.detail.map((item) => item.msg).join("; ");
  return `Ошибка сервера (${status})`;
}

async function api(url, options = {}) {
  let response;
  try {
    response = await fetch(url, options);
  } catch (error) {
    throw new Error("Сервер недоступен, проверьте соединение");
  }
  let body = null;
  try {
    body = await response.json();
  } catch (error) {
    body = null;
  }
  if (!response.ok) throw new Error(errorText(body, response.status));
  return body;
}

function showNotice(message) {
  const notice = $("notice");
  notice.textContent = message;
  notice.hidden = !message;
}

async function loadInfo() {
  try {
    const info = await api("/api/info");
    $("model-info").textContent = `Модель: ${info.model}`;
    $("max-mb").textContent = info.max_upload_mb;
    $("max-products").textContent = info.max_products;
    state.maxBytes = info.max_upload_mb * 1024 * 1024;
  } catch (error) {
    $("model-info").textContent = "";
  }
}

async function loadExamples() {
  const list = $("examples-list");
  try {
    const examples = await api("/api/examples");
    examples.forEach((example) => {
      const link = el("a", {
        className: "example-link",
        text: "JSON",
        attrs: { href: `/api/examples/${example.id}/file`, target: "_blank", title: "Открыть исходный файл" },
      });
      link.addEventListener("click", (event) => event.stopPropagation());
      const button = el("button", { className: "example", onClick: () => runExample(example.id) }, [
        el("div", { className: "example-text" }, [
          el("div", { className: "example-title", text: example.title }),
          el("div", { className: "example-note", text: example.note }),
        ]),
        link,
      ]);
      list.appendChild(button);
    });
  } catch (error) {
    list.appendChild(el("div", { className: "muted", text: error.message }));
  }
}

function setupDropzone() {
  const zone = $("dropzone");
  const input = $("file-input");
  zone.addEventListener("click", () => input.click());
  zone.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      input.click();
    }
  });
  input.addEventListener("change", () => {
    if (input.files.length) uploadFile(input.files[0]);
    input.value = "";
  });
  ["dragenter", "dragover"].forEach((name) =>
    zone.addEventListener(name, (event) => {
      event.preventDefault();
      zone.classList.add("dragover");
    })
  );
  ["dragleave", "drop"].forEach((name) =>
    zone.addEventListener(name, (event) => {
      event.preventDefault();
      zone.classList.remove("dragover");
    })
  );
  zone.addEventListener("drop", (event) => {
    const files = event.dataTransfer.files;
    if (files.length !== 1) {
      showNotice("Перетащите один файл .json");
      return;
    }
    uploadFile(files[0]);
  });
}

async function uploadFile(file) {
  showNotice("");
  if (!file.name.toLowerCase().endsWith(".json")) {
    showNotice(`Файл «${file.name}» не подходит: принимаются только файлы .json`);
    return;
  }
  if (file.size > state.maxBytes) {
    showNotice(`Файл «${file.name}» больше ${state.maxBytes / 1024 / 1024} МБ`);
    return;
  }
  const form = new FormData();
  form.append("file", file);
  try {
    startRun(await api("/api/upload", { method: "POST", body: form }));
  } catch (error) {
    showNotice(error.message);
  }
}

async function runExample(exampleId) {
  showNotice("");
  try {
    startRun(await api(`/api/examples/${exampleId}`));
  } catch (error) {
    showNotice(error.message);
  }
}

async function startRun(parsed) {
  state.runId += 1;
  const runId = state.runId;
  state.source = parsed.source;
  state.products = parsed.products;
  state.items = {};
  state.active = null;
  parsed.products.forEach((product) => {
    state.items[product.index] = product.error
      ? { status: "invalid", error: product.error }
      : { status: "waiting" };
  });
  const firstValid = parsed.products.find((product) => !product.error);
  state.active = firstValid ? firstValid.index : null;
  $("parse").hidden = false;
  renderParse();
  renderResult();
  $("parse").scrollIntoView({ behavior: "smooth", block: "start" });
  for (const product of parsed.products) {
    if (product.error || runId !== state.runId) continue;
    state.items[product.index] = { status: "loading" };
    renderParse();
    if (state.active === product.index) renderResult();
    try {
      const response = await api("/api/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(product.data),
      });
      if (runId !== state.runId) return;
      state.items[product.index] = { status: response.result.quality.status, response };
    } catch (error) {
      if (runId !== state.runId) return;
      state.items[product.index] = { status: "error", error: error.message };
    }
    renderParse();
    if (state.active === product.index) renderResult();
  }
}

function productLabel(product) {
  return product.name || `Товар №${product.index}`;
}

function renderParse() {
  const total = state.products.length;
  const invalid = state.products.filter((product) => product.error).length;
  const done = Object.values(state.items).filter((item) => ["ok", "needs_review", "error"].includes(item.status)).length;
  const parts = [`${state.source}: товаров - ${total}`];
  if (invalid) parts.push(`с ошибками во входных данных - ${invalid}`);
  parts.push(`обработано - ${done} из ${total - invalid}`);
  $("parse-summary").textContent = parts.join(" · ");

  const tabs = $("product-tabs");
  tabs.replaceChildren();
  state.products.forEach((product) => {
    const item = state.items[product.index];
    if (item.status === "invalid") {
      tabs.appendChild(
        el("div", { className: "tab tab-error" }, [
          el("span", { className: "dot error" }),
          el("span", { text: `${productLabel(product)}: ${item.error}` }),
        ])
      );
      return;
    }
    const tab = el(
      "button",
      {
        className: `tab${state.active === product.index ? " active" : ""}`,
        onClick: () => {
          state.active = product.index;
          renderParse();
          renderResult();
        },
      },
      [el("span", { className: `dot ${item.status}` }), el("span", { text: productLabel(product) })]
    );
    tabs.appendChild(tab);
  });
  const completed = Object.values(state.items).filter((item) => item.response).length;
  $("download-all").hidden = completed < 2;
}

function renderResult() {
  const section = $("result");
  if (state.active === null) {
    section.hidden = true;
    return;
  }
  section.hidden = false;
  const product = state.products.find((item) => item.index === state.active);
  const item = state.items[state.active];
  $("result-loading").hidden = !["loading", "waiting"].includes(item.status);
  $("result-error").hidden = item.status !== "error";
  $("result-body").hidden = !item.response;
  renderHead(product, item);
  if (item.status === "error") $("result-error").textContent = item.error;
  if (item.response) renderCard(item.response);
}

function renderHead(product, item) {
  const head = $("result-head");
  head.replaceChildren(el("div", { className: "result-name", text: productLabel(product) }));
  if (!item.response) {
    const text = item.status === "error" ? "Ошибка" : item.status === "waiting" ? "В очереди" : "Генерация…";
    head.appendChild(el("span", { className: "muted", text }));
    return;
  }
  const quality = item.response.result.quality;
  const percent = Math.round(quality.completeness * 100);
  const fill = el("div", { className: "bar-fill", attrs: { style: `width: ${percent}%` } });
  head.appendChild(el("span", { className: `pill ${quality.status}`, text: STATUS_LABELS[quality.status] }));
  head.appendChild(
    el("div", { className: "progress" }, [
      el("span", { text: "Заполненность" }),
      el("div", { className: "bar" }, [fill]),
      el("span", { text: `${percent}%` }),
    ])
  );
  head.appendChild(el("span", { className: "muted", text: `попыток: ${quality.attempts}` }));
}

function renderCard(response) {
  const card = response.result.card;
  $("seo-title").textContent = card.seo_title;
  const titleCounter = $("title-counter");
  titleCounter.textContent = `${card.seo_title_length} / ${TITLE_MAX}`;
  titleCounter.classList.toggle("bad", card.seo_title_length > TITLE_MAX);

  const description = $("seo-description");
  description.replaceChildren(
    ...card.seo_description
      .split(/\n\s*\n|\n/)
      .filter((paragraph) => paragraph.trim())
      .map((paragraph) => el("p", { text: paragraph.trim() }))
  );
  const descriptionCounter = $("description-counter");
  descriptionCounter.textContent = `${card.seo_description_length} симв. · нужно ${DESCRIPTION_MIN}–${DESCRIPTION_MAX}`;
  descriptionCounter.classList.toggle(
    "bad",
    card.seo_description_length < DESCRIPTION_MIN || card.seo_description_length > DESCRIPTION_MAX
  );

  $("queries").replaceChildren(...card.search_queries.map((query) => el("span", { className: "chip", text: query })));

  $("specs").replaceChildren(
    ...card.key_specs.map((row) =>
      el("tr", {}, [
        el("td", { className: "spec-name" }, [
          el("div", { text: row.name }),
          el("span", { className: `source source-${row.source}`, text: SOURCE_LABELS[row.source] }),
        ]),
        el("td", { className: `spec-value${row.source === "none" ? " empty" : ""}`, text: row.value }),
      ])
    )
  );

  $("suitable").replaceChildren(...card.manager_note.suitable_for.map((text) => el("li", { text })));
  $("solves").replaceChildren(...card.manager_note.solves.map((text) => el("li", { text })));

  const review = $("review");
  if (!response.review.length) {
    review.replaceChildren(el("li", { className: "ok-line", text: "Замечаний нет" }));
  } else {
    review.replaceChildren(
      ...response.review.map((text) => {
        const important = text.includes("важная характеристика") || text.startsWith("Важная") || text.startsWith("Проверка не пройдена");
        return el("li", { className: important ? "important" : "", text });
      })
    );
  }
}

function copyText(text, button) {
  const done = () => {
    const original = button.textContent;
    button.textContent = "Скопировано";
    button.classList.add("done");
    setTimeout(() => {
      button.textContent = original;
      button.classList.remove("done");
    }, 1500);
  };
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text).then(done);
    return;
  }
  const area = el("textarea", { attrs: { style: "position:fixed;opacity:0" } });
  area.value = text;
  document.body.appendChild(area);
  area.select();
  document.execCommand("copy");
  area.remove();
  done();
}

function activeResponse() {
  const item = state.items[state.active];
  return item && item.response ? item.response : null;
}

function setupCopyButtons() {
  document.querySelectorAll("[data-copy]").forEach((button) => {
    button.addEventListener("click", () => {
      const response = activeResponse();
      if (!response) return;
      const card = response.result.card;
      const texts = {
        "seo-title": card.seo_title,
        "seo-description": card.seo_description,
        queries: card.search_queries.join("\n"),
      };
      copyText(texts[button.dataset.copy], button);
    });
  });
}

function saveFile(content, filename, type) {
  const blob = new Blob([content], { type });
  const link = el("a", { attrs: { href: URL.createObjectURL(blob), download: filename } });
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}

function setupDownloads() {
  document.querySelectorAll("[data-download]").forEach((button) => {
    button.addEventListener("click", () => {
      const format = button.dataset.download;
      if (format === "all") {
        const all = Object.values(state.items).filter((item) => item.response).map((item) => item.response.result);
        const name = state.source.replace(/\.json$/i, "");
        saveFile(JSON.stringify(all, null, 2), `${name}-cards.json`, "application/json");
        return;
      }
      const response = activeResponse();
      if (!response) return;
      if (format === "json") saveFile(JSON.stringify(response.result, null, 2), `${response.filename}.json`, "application/json");
      if (format === "md") saveFile(response.markdown, `${response.filename}.md`, "text/markdown;charset=utf-8");
    });
  });
}

document.addEventListener("dragover", (event) => event.preventDefault());
document.addEventListener("drop", (event) => event.preventDefault());

setupDropzone();
setupCopyButtons();
setupDownloads();
loadInfo();
loadExamples();

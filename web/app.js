const state = {
  page: "home",
  docId: null,
  pageCount: 0,
  currentPage: 1,
  lastBlob: null,
  lastFilename: "result.png",
  sidebarCollapsed: false,
};

const els = {
  sidebar: document.getElementById("sidebar"),
  toggleSidebar: document.getElementById("toggleSidebar"),
  navList: document.getElementById("navList"),
  pages: {
    home: document.getElementById("page-home"),
    pdf: document.getElementById("page-pdf"),
  },
  enterPdf: document.getElementById("enterPdf"),
  pdfFile: document.getElementById("pdfFile"),
  imageFormat: document.getElementById("imageFormat"),
  pageSpec: document.getElementById("pageSpec"),
  dpi: document.getElementById("dpi"),
  convertBtn: document.getElementById("convertBtn"),
  downloadBtn: document.getElementById("downloadBtn"),
  progressWrap: document.getElementById("progressWrap"),
  progressBar: document.getElementById("progressBar"),
  prevPage: document.getElementById("prevPage"),
  nextPage: document.getElementById("nextPage"),
  pageInput: document.getElementById("pageInput"),
  pageTotal: document.getElementById("pageTotal"),
  zoomMode: document.getElementById("zoomMode"),
  previewViewport: document.getElementById("previewViewport"),
  previewImage: document.getElementById("previewImage"),
  previewEmpty: document.getElementById("previewEmpty"),
  advToggle: document.getElementById("advToggle"),
  advBody: document.getElementById("advBody"),
};

function setSidebarCollapsed(collapsed) {
  state.sidebarCollapsed = collapsed;
  els.sidebar.classList.toggle("collapsed", collapsed);
  els.sidebar.classList.toggle("expanded", !collapsed);
  els.toggleSidebar.textContent = collapsed ? "▶" : "◀";
  els.toggleSidebar.title = collapsed ? "展开导航" : "收起导航";
}

function switchPage(page) {
  state.page = page;
  Object.entries(els.pages).forEach(([k, el]) => {
    el.classList.toggle("active", k === page);
  });

  document.querySelectorAll(".nav-item[data-page]").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.page === page);
  });

  if (page === "pdf") setSidebarCollapsed(true);
}

async function uploadPdf(file) {
  const fd = new FormData();
  fd.append("file", file);
  const res = await fetch("/api/pdf/upload", { method: "POST", body: fd });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "上传失败");

  state.docId = data.doc_id;
  state.pageCount = data.page_count;
  state.currentPage = 1;

  els.pageInput.min = 1;
  els.pageInput.max = data.page_count;
  els.pageInput.value = 1;
  els.pageTotal.textContent = `/ ${data.page_count}`;
  els.convertBtn.disabled = false;
  await renderPreview();
}

async function renderPreview() {
  if (!state.docId) return;

  const modeRaw = els.zoomMode.value;
  const mode = modeRaw === "fit-width" || modeRaw === "fit-page" ? modeRaw : "percent";
  const zoomPercent = mode === "percent" ? Number(modeRaw) : 100;

  const params = new URLSearchParams({
    doc_id: state.docId,
    page: String(state.currentPage),
    mode,
    viewport_width: String(Math.max(300, els.previewViewport.clientWidth)),
    viewport_height: String(Math.max(300, els.previewViewport.clientHeight)),
    zoom_percent: String(zoomPercent),
  });

  const res = await fetch(`/api/pdf/preview?${params.toString()}`);
  if (!res.ok) return;

  const blob = await res.blob();
  const url = URL.createObjectURL(blob);

  els.previewImage.classList.remove("show");
  setTimeout(() => {
    els.previewImage.src = url;
    els.previewImage.style.display = "block";
    els.previewEmpty.style.display = "none";
    els.previewImage.classList.add("show");
  }, 40);
}

async function convertPdf() {
  if (!state.docId) return;

  els.progressWrap.classList.remove("hidden");
  els.progressBar.style.width = "16%";
  els.convertBtn.disabled = true;

  const payload = {
    doc_id: state.docId,
    page_spec: els.pageSpec.value.trim(),
    dpi: Number(els.dpi.value || 150),
    image_format: els.imageFormat.value,
  };

  try {
    const res = await fetch("/api/pdf/convert", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    els.progressBar.style.width = "72%";
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "导出失败");
    }

    const blob = await res.blob();
    const cd = res.headers.get("content-disposition") || "";
    const m = /filename="([^"]+)"/.exec(cd);

    state.lastBlob = blob;
    state.lastFilename = m ? m[1] : `result.${payload.image_format.toLowerCase()}`;
    els.downloadBtn.disabled = false;
    els.progressBar.style.width = "100%";
  } catch (e) {
    alert(e.message || "导出失败");
  } finally {
    els.convertBtn.disabled = false;
    setTimeout(() => {
      els.progressWrap.classList.add("hidden");
      els.progressBar.style.width = "0";
    }, 500);
  }
}

function downloadResult() {
  if (!state.lastBlob) return;
  const url = URL.createObjectURL(state.lastBlob);
  const a = document.createElement("a");
  a.href = url;
  a.download = state.lastFilename;
  a.click();
  URL.revokeObjectURL(url);
}

function bindEvents() {
  els.toggleSidebar.addEventListener("click", () => setSidebarCollapsed(!state.sidebarCollapsed));
  els.enterPdf.addEventListener("click", () => switchPage("pdf"));

  els.navList.querySelectorAll(".nav-item[data-page]").forEach((btn) => {
    btn.addEventListener("click", () => switchPage(btn.dataset.page));
  });

  els.pdfFile.addEventListener("change", async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      await uploadPdf(file);
      switchPage("pdf");
    } catch (err) {
      alert(err.message || "上传失败");
    }
  });

  els.prevPage.addEventListener("click", async () => {
    if (!state.docId || state.currentPage <= 1) return;
    state.currentPage -= 1;
    els.pageInput.value = String(state.currentPage);
    await renderPreview();
  });

  els.nextPage.addEventListener("click", async () => {
    if (!state.docId || state.currentPage >= state.pageCount) return;
    state.currentPage += 1;
    els.pageInput.value = String(state.currentPage);
    await renderPreview();
  });

  els.pageInput.addEventListener("change", async () => {
    if (!state.docId) return;
    const p = Math.max(1, Math.min(state.pageCount, Number(els.pageInput.value || 1)));
    state.currentPage = p;
    els.pageInput.value = String(p);
    await renderPreview();
  });

  els.zoomMode.addEventListener("change", renderPreview);
  window.addEventListener("resize", () => {
    if (state.docId && (els.zoomMode.value === "fit-width" || els.zoomMode.value === "fit-page")) {
      renderPreview();
    }
  });

  els.convertBtn.addEventListener("click", convertPdf);
  els.downloadBtn.addEventListener("click", downloadResult);

  els.advToggle.addEventListener("click", () => {
    const collapsed = els.advBody.classList.toggle("collapsed");
    els.advToggle.textContent = collapsed ? "高级选项 ▸" : "高级选项 ▾";
  });
}

bindEvents();

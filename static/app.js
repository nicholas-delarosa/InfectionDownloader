(() => {
  const $ = (id) => document.getElementById(id);
  const form = $("url-form");
  const input = $("url");
  const els = {
    error: $("error"), loading: $("loading"), result: $("result"),
    thumb: $("thumb"), duration: $("duration"), site: $("site"),
    title: $("title"), uploader: $("uploader"), options: $("options"),
    hint: $("hint"), qlabel: $("quality-label"), download: $("download"),
    progress: $("progress"), fill: $("bar-fill"), pstatus: $("pstatus"),
    pdetail: $("pdetail"), analyze: $("analyze"),
  };

  const state = { info: null, type: "mp4", quality: null, busy: false };

  const LABELS = { 4320: "8K", 2160: "4K", 1440: "2K", 1080: "Full HD", 720: "HD" };
  const AUDIO_LABELS = { 128: "Normal", 192: "Buena", 256: "Alta", 320: "Máxima" };

  const fmtTime = (s) => {
    if (!s && s !== 0) return "";
    s = Math.round(s);
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
    const mm = h ? String(m).padStart(2, "0") : m;
    return (h ? h + ":" : "") + mm + ":" + String(sec).padStart(2, "0");
  };
  const fmtBytes = (b) => {
    if (!b) return "";
    const u = ["B", "KB", "MB", "GB"]; let i = 0;
    while (b >= 1024 && i < u.length - 1) { b /= 1024; i++; }
    return b.toFixed(i ? 1 : 0) + " " + u[i];
  };

  function showError(msg) {
    els.error.textContent = msg;
    els.error.hidden = !msg;
  }

  async function api(path, body) {
    const res = await fetch(path, body ? {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    } : undefined);
    let data = null;
    try { data = await res.json(); } catch { /* sin cuerpo */ }
    if (!res.ok) {
      let msg = data && data.detail;
      if (Array.isArray(msg)) msg = "Enlace no válido.";
      throw new Error(msg || "Error del servidor (" + res.status + ")");
    }
    return data;
  }

  async function analyze() {
    const url = input.value.trim();
    if (!url) return;
    showError("");
    els.result.hidden = true;
    els.loading.hidden = false;
    els.analyze.disabled = true;
    try {
      state.info = await api("/api/info", { url });
      render();
    } catch (e) {
      showError(e.message);
    } finally {
      els.loading.hidden = true;
      els.analyze.disabled = false;
    }
  }

  function render() {
    const i = state.info;
    els.thumb.src = i.thumbnail || "favicon.svg";
    els.thumb.alt = i.title;
    els.duration.textContent = fmtTime(i.duration);
    els.site.textContent = i.site;
    els.title.textContent = i.title;
    els.uploader.textContent = i.uploader;

    const mp4Tab = document.querySelector('.tab[data-type="mp4"]');
    mp4Tab.disabled = !i.video_heights.length;
    setType(i.video_heights.length ? "mp4" : "mp3");

    els.progress.hidden = true;
    els.result.hidden = false;
  }

  function setType(type) {
    state.type = type;
    document.querySelectorAll(".tab").forEach((t) => {
      const on = t.dataset.type === type;
      t.classList.toggle("active", on);
      t.setAttribute("aria-selected", on);
    });
    renderOptions();
  }

  function renderOptions() {
    const i = state.info;
    els.options.innerHTML = "";
    let list, def;
    if (state.type === "mp4") {
      els.qlabel.textContent = "Resolución";
      list = i.video_heights.map((h) => ({ v: h, text: h + "p", sub: LABELS[h] }));
      def = i.video_heights.find((h) => h <= 1080) || i.video_heights[0];
      els.hint.textContent = "Las resoluciones mostradas son las que ofrece el video original.";
    } else {
      els.qlabel.textContent = "Calidad del audio";
      list = i.audio_bitrates.map((b) => ({ v: b, text: b + " kbps", sub: AUDIO_LABELS[b] }));
      def = 320;
      els.hint.textContent = i.source_audio_kbps
        ? "El audio original es de ~" + i.source_audio_kbps + " kbps; subir más allá no mejora el sonido."
        : "";
    }
    list.forEach(({ v, text, sub }) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "chip" + (v === def ? " active" : "");
      b.innerHTML = text + (sub ? " <small>" + sub + "</small>" : "");
      b.onclick = () => {
        state.quality = v;
        els.options.querySelectorAll(".chip").forEach((c) => c.classList.remove("active"));
        b.classList.add("active");
      };
      els.options.appendChild(b);
    });
    state.quality = def;
    els.download.querySelector("span").textContent = "Descargar " + state.type.toUpperCase();
  }

  function setProgress(pct, status, detail) {
    const bar = els.fill.parentElement;
    bar.classList.toggle("indeterminate", pct == null);
    if (pct != null) els.fill.style.width = pct + "%";
    els.pstatus.textContent = status;
    els.pdetail.textContent = detail || "";
  }

  async function download() {
    if (state.busy || !state.info) return;
    state.busy = true;
    els.download.disabled = true;
    showError("");
    els.progress.hidden = false;
    setProgress(0, "En cola…");
    try {
      const { job_id } = await api("/api/download", {
        url: state.info.url, type: state.type, quality: state.quality,
      });
      while (true) {
        await new Promise((r) => setTimeout(r, 900));
        const p = await api("/api/progress/" + job_id);
        if (p.status === "error") throw new Error(p.error);
        if (p.status === "done") {
          setProgress(100, "¡Listo! Descargando archivo…", fmtBytes(p.size));
          const a = document.createElement("a");
          a.href = "/api/file/" + job_id;
          a.download = p.filename || "";
          document.body.appendChild(a); a.click(); a.remove();
          break;
        }
        if (p.status === "downloading") {
          const det = [p.speed ? fmtBytes(p.speed) + "/s" : "", p.eta ? "faltan " + fmtTime(p.eta) : ""]
            .filter(Boolean).join(" · ");
          setProgress(p.progress, "Descargando " + (p.progress != null ? p.progress + "%" : "…"), det);
        } else if (p.status === "processing") {
          setProgress(null, state.type === "mp3" ? "Convirtiendo a MP3…" : "Uniendo video y audio…");
        } else {
          setProgress(null, p.status === "queued" ? "En cola…" : "Preparando…");
        }
      }
    } catch (e) {
      els.progress.hidden = true;
      showError(e.message);
    } finally {
      state.busy = false;
      els.download.disabled = false;
    }
  }

  form.addEventListener("submit", (e) => { e.preventDefault(); analyze(); });
  input.addEventListener("paste", () => setTimeout(analyze, 50));
  $("paste").addEventListener("click", async () => {
    try {
      input.value = (await navigator.clipboard.readText()).trim();
      analyze();
    } catch { input.focus(); }
  });
  document.querySelectorAll(".tab").forEach((t) =>
    t.addEventListener("click", () => !t.disabled && setType(t.dataset.type)));
  els.download.addEventListener("click", download);
})();

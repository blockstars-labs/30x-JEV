// Pálpito (prototipo del reto 30X: JEV). Sin build: lee /api/datos y demografia.json, y llama a
// /api/inscribir, /api/evento, /api/simular y /api/guardrail. La Tierra es globe.gl (vendor/).

const estado = { datos: null, demografia: null, gente: null, filtroRuta: "todas", busquedaDec: "", seleccion: null, politicaSimulada: null };
const RUTAS = {
  automatico: { nombre: "JEV decide solo", corto: "Automático", color: "var(--ruta-auto)" },
  llm: { nombre: "Lo revisa el LLM", corto: "LLM", color: "var(--ruta-llm)" },
  revision_humana: { nombre: "Lo confirma una persona", corto: "Persona", color: "var(--ruta-humana)" },
};
const CANALES = { formulario_luma: "Formulario de Luma", correo: "Correo", mensaje: "Mensaje" };
const ACCION_CORTA = { pasar_a_ventas: "Pasar a un asesor", nutrir_programa: "Contenido del programa", nutrir_general: "Contenido general", revision_humana: "Revisión" };
const TEMAS_ES = { ai: "IA", sales: "Ventas", ops: "Operaciones", gtm: "Go-to-market", leadership: "Liderazgo", marketing: "Marketing", fundraising: "Levantar capital", finance: "Finanzas", product: "Producto", pricing: "Precios", hiring: "Contratación", negotiation: "Negociación", retention: "Retención" };
const PAIS_EN = { Colombia: "Colombia", México: "Mexico", Perú: "Peru", Venezuela: "Venezuela", "Estados Unidos": "United States of America", España: "Spain", Argentina: "Argentina", Chile: "Chile", Ecuador: "Ecuador" };
const PAIS_ES = Object.fromEntries(Object.entries(PAIS_EN).map(([es, en]) => [en, es]));
const BOGOTA = { lat: 4.711, lng: -74.072 };
const QUIETO = matchMedia("(prefers-reduced-motion: reduce)").matches;
// En el teléfono la cámara se aleja para que la Tierra quepa entera y se vea más pequeña.
const MOVIL = matchMedia("(max-width: 720px)");
const alto = (a) => (MOVIL.matches ? a * 1.8 : a);

const $ = (sel, raiz = document) => raiz.querySelector(sel);
const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pct = (x, dec = 1) => (x == null ? "—" : (x * 100).toLocaleString("es-CO", { maximumFractionDigits: dec }) + " %");
const usd = (x, dec = 4) => "USD " + x.toLocaleString("es-CO", { minimumFractionDigits: dec, maximumFractionDigits: dec });
const cat = () => estado.datos.catalogo;
// Búsqueda por palabras: "medellin linkedin" encuentra lo que tenga ambas, en cualquier orden.
const coincide = (texto, q) => q.split(/\s+/).filter(Boolean).every((w) => texto.includes(w));
const normal = (t) => String(t ?? "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

function animar(el) {
  el.classList.remove("entra");
  void el.offsetWidth;
  el.classList.add("entra");
}

// ---------- Tooltip compartido ----------
const tooltip = $("#tooltip");
document.addEventListener("pointerover", (e) => {
  const t = e.target.closest("[data-tip]");
  if (!t) return;
  tooltip.innerHTML = t.dataset.tip;
  tooltip.hidden = false;
});
document.addEventListener("pointermove", (e) => {
  if (tooltip.hidden) return;
  tooltip.style.left = Math.min(e.clientX + 14, window.innerWidth - 300) + "px";
  tooltip.style.top = e.clientY + 14 + "px";
});
document.addEventListener("pointerout", (e) => {
  if (e.target.closest("[data-tip]")) tooltip.hidden = true;
});

// ---------- Escena: una sola Tierra para toda la experiencia ----------
const ESC = { g: null, paises: [], escena: "personas" };

function ciudadesDe(lista) {
  const c = {};
  lista.forEach((p) => {
    const x = (c[p.demo.ciudad] ||= { ciudad: p.demo.ciudad, pais: p.demo.pais, lat: 0, lng: 0, n: 0 });
    x.n += 1; x.lat += p.demo.lat; x.lng += p.demo.lon;
  });
  return Object.values(c).map((x) => ({ ...x, lat: x.lat / x.n, lng: x.lng / x.n })).sort((a, b) => b.n - a.n);
}

// Una "ciudad" por país, en el centro de su gente: para la vista general del globo.
function paisesDe(lista) {
  const c = {};
  lista.forEach((p) => {
    const x = (c[p.demo.pais] ||= { ciudad: p.demo.pais, lat: 0, lng: 0, n: 0 });
    x.n += 1; x.lat += p.demo.lat; x.lng += p.demo.lon;
  });
  return Object.values(c).map((x) => ({ ...x, lat: x.lat / x.n, lng: x.lng / x.n })).sort((a, b) => b.n - a.n);
}

function etiquetaCiudad(d) {
  const el = document.createElement("div");
  el.className = "geo-etq";
  el.innerHTML = `<i></i><span>${esc(d.ciudad)}</span><b>${d.n}</b>`;
  return el;
}

async function iniciarEscena() {
  if (typeof Globe === "undefined") { document.body.classList.add("sin-globo"); return; }
  const el = $("#escena-globo");
  const g = new Globe(el, { animateIn: !QUIETO })
    .backgroundColor("rgba(0,0,0,0)")
    .globeImageUrl("vendor/globo/earth-night.jpg")
    .bumpImageUrl("vendor/globo/earth-topology.png")
    .showAtmosphere(true).atmosphereColor("#cfe86a").atmosphereAltitude(0.17)
    .width(innerWidth).height(innerHeight)
    // Países: se encienden en lima cuando hay gente de ahí.
    .polygonCapColor((d) => d.__color || "rgba(0,0,0,0)")
    .polygonSideColor((d) => (d.__activo ? "rgba(233,255,123,0.35)" : "rgba(233,255,123,0.08)"))
    .polygonStrokeColor((d) => (d.__activo ? "#e9ff7b" : "rgba(255,255,255,0.12)"))
    .polygonAltitude((d) => d.__alt ?? 0.004)
    .polygonsTransitionDuration(700)
    .polygonLabel((d) => (d.__n ? `<b>${esc(PAIS_ES[d.properties.name] || d.properties.name)}</b><br>${d.__n} personas · clic para filtrar` : ""))
    .onPolygonClick((d) => {
      if (ESC.escena !== "personas") return;
      const es = PAIS_ES[d.properties.name];
      if (!es || !d.__n) return;
      if (ESTADO_P.filtros.pais === es) delete ESTADO_P.filtros.pais; else ESTADO_P.filtros.pais = es;
      actualizarPersonas();
    })
    // Ciudades: etiqueta HTML nítida, como en un mapa editorial.
    .htmlElement(etiquetaCiudad)
    .htmlAltitude(0.02)
    // Llegadas hacia 30X.
    .arcColor(() => ["rgba(233,255,123,0)", "rgba(233,255,123,0.85)"])
    .arcDashLength(0.45).arcDashGap(1.2).arcDashAnimateTime(2600).arcStroke(0.35).arcAltitudeAutoScale(0.35)
    // Pulsos.
    .ringColor(() => (t) => `rgba(233,255,123,${1 - t})`)
    .ringMaxRadius(3.2).ringPropagationSpeed(2.2).ringRepeatPeriod(1100);
  const c = g.controls();
  c.enableZoom = false;
  c.autoRotate = !QUIETO;
  c.autoRotateSpeed = 0.35;
  addEventListener("resize", () => g.width(innerWidth).height(innerHeight));
  ESC.g = g;
  try {
    const topo = await (await fetch("vendor/globo/paises-110m.json")).json();
    ESC.paises = topojson.feature(topo, topo.objects.countries).features.filter((f) => f.properties.name !== "Antarctica");
  } catch { ESC.paises = []; }
  ponerEscena(ESC.escena);
  if (ESC.escena === "personas") actualizarGloboPersonas(filtrar());
}

const POV = {
  ambiente: { lat: 10, lng: -78, altitude: 2.1 },
  personas: { lat: 6, lng: -76, altitude: 1.9 },
};

function ponerEscena(nombre, pov) {
  ESC.escena = nombre;
  document.body.dataset.escena = nombre;
  const g = ESC.g;
  if (!g) return;
  g.controls().autoRotate = !QUIETO && nombre === "ambiente";
  if (nombre === "personas") {
    g.arcsData([]);
  } else {
    g.polygonsData([]).htmlElementsData([]).arcsData([]).ringsData([]);
  }
  const v = pov || POV[nombre] || POV.ambiente;
  g.pointOfView({ ...v, altitude: alto(v.altitude) }, QUIETO ? 0 : 1600);
}

function enfocarCiudad(demo, altitud = 1.7) {
  if (!ESC.g || !demo) return;
  ESC.g.ringsData([{ lat: demo.lat, lng: demo.lon }]);
  ESC.g.pointOfView({ lat: demo.lat - 4, lng: demo.lon, altitude: alto(altitud) }, QUIETO ? 0 : 1400);
}

// ---------- Navegación ----------
function mostrarVista(nombre) {
  document.querySelectorAll("[data-vista]").forEach((x) => x.setAttribute("aria-selected", x.dataset.vista === nombre));
  document.querySelectorAll(".vista").forEach((v) => (v.hidden = v.id !== "vista-" + nombre));
  window.scrollTo({ top: 0 });
  if (nombre === "reclasificacion") { ponerEscena("personas"); actualizarGloboPersonas(filtrar()); }
  else ponerEscena("ambiente");
}
document.querySelectorAll("[data-vista]").forEach((b) => b.addEventListener("click", () => mostrarVista(b.dataset.vista)));
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-ir]");
  if (b) mostrarVista(b.dataset.ir);
});

// ---------- Piezas comunes ----------
function encabezado(etiqueta, titulo, texto = "", extra = "") {
  return `<div class="encabezado"><div><span class="etiqueta-mono">${etiqueta}</span><h1>${titulo}</h1>${texto ? `<p>${texto}</p>` : ""}</div>${extra}</div>`;
}

function stat(etiqueta, valor, nota = "", clase = "") {
  return `<div class="card stat ${clase}"><span class="stat-etiqueta">${etiqueta}</span><span class="stat-valor">${valor}</span><span class="stat-nota">${nota}</span></div>`;
}

function buscadorLocal(id, placeholder, valor) {
  return `<label class="buscar-local"><svg class="ico" viewBox="0 0 20 20" aria-hidden="true"><circle cx="9" cy="9" r="5.5"/><path d="M13.2 13.2L17 17"/></svg>
    <input id="${id}" type="search" placeholder="${placeholder}" value="${esc(valor)}" autocomplete="off" spellcheck="false" aria-label="${placeholder}"></label>`;
}

function badgeRuta(ruta) {
  const r = RUTAS[ruta] || { corto: ruta, color: "var(--muted-fg)" };
  return `<span class="badge"><span class="punto" style="background:${r.color}"></span>${esc(r.corto)}</span>`;
}

function barraRutas(rutas, total) {
  const orden = ["automatico", "llm", "revision_humana"].filter((r) => rutas[r]);
  const segmentos = orden
    .map((r) => `<div style="flex:${rutas[r]};background:${RUTAS[r].color}" data-tip="${esc(`<b>${RUTAS[r].nombre}</b><br>${rutas[r]} de ${total}`)}"></div>`)
    .join("");
  const leyenda = orden
    .map((r) => `<li><span class="punto" style="background:${RUTAS[r].color}"></span>${RUTAS[r].nombre}<b>${pct(rutas[r] / total, 0)}</b></li>`)
    .join("");
  return `<div class="rutas-barra" role="img" aria-label="Quién decide cada caso">${segmentos}</div><ul class="leyenda">${leyenda}</ul>`;
}

// La explicación llega como un párrafo; se parte en frases para leerla de un vistazo.
// La explicación llega como un párrafo: se parte en frases, primero el programa y la acción, y el
// detalle técnico (confianzas, afinidad) queda plegado.
const CLAVE_PORQUE = /^(Programa|Va a revisión|El perfil no parece|Duda|La intención|El rol no es|Perfil típico)/;
function explicacionHtml(texto, visibles = 3) {
  const partes = String(texto || "")
    .split(/\.\s+(?=[A-ZÁÉÍÓÚÑ¿(])/)
    .map((s) => s.trim().replace(/\.$/, ""))
    .filter(Boolean);
  const orden = [...partes.filter((p) => CLAVE_PORQUE.test(p)), ...partes.filter((p) => !CLAVE_PORQUE.test(p))];
  const li = (p) => `<li>${esc(p.replace(/^Programa: /, "").replace(/ \(1\.00\)/g, ""))}.</li>`;
  const resto = orden.slice(visibles);
  return `<ul class="porque">${orden.slice(0, visibles).map(li).join("")}</ul>${resto.length
    ? `<details class="mas-porque"><summary>Ver detalle (${resto.length})</summary><ul class="porque">${resto.map(li).join("")}</ul></details>` : ""}`;
}

function probabilidades(campo, juicio, max = 3) {
  const nombres = cat()[campo];
  const filas = Object.entries(juicio.probabilidades).sort((a, b) => b[1] - a[1]).slice(0, max);
  return `<div class="probs">${filas
    .map(([id, p]) => `<span class="${id === juicio.valor ? "elegida" : ""}">${esc(nombres[id] || id)}</span>
      <span class="pista"><span class="relleno" style="width:${(p * 100).toFixed(1)}%"></span></span>
      <span class="num">${pct(p, 0)}</span>`)
    .join("")}</div>`;
}

function probIntencion(probs) {
  const niveles = cat().intencion;
  const p = (i) => probs[i] ?? probs[String(i)] ?? 0;
  const mejor = niveles.reduce((m, _, i) => (p(i) > p(m) ? i : m), 0);
  return `<div class="probs">${niveles
    .map((n, i) => `<span class="${i === mejor ? "elegida" : ""}">${esc(n)}</span><span class="pista"><span class="relleno" style="width:${(p(i) * 100).toFixed(1)}%"></span></span><span class="num">${pct(p(i), 0)}</span>`)
    .join("")}</div>`;
}

function respuestasJev(rol, dolor, objetivo, intencion, valido) {
  return `<div class="jev">
    <div><span class="jev-q">Rol</span>${probabilidades("rol", rol)}</div>
    <div><span class="jev-q">Dolor</span>${probabilidades("dolor", dolor)}</div>
    <div><span class="jev-q">Objetivo</span>${probabilidades("objetivo", objetivo)}</div>
    <div><span class="jev-q">Intención de compra</span>${probIntencion(intencion)}</div>
    <div class="jev-noul"><span class="jev-q">¿Inscripción genuina?</span><b class="mono">${pct(valido, 0)}</b></div>
  </div>`;
}

function entradaHtml(inscripcion) {
  if (typeof inscripcion === "string") return `<div class="entrada">${esc(inscripcion)}</div>`;
  const etiquetas = { cargo: "Cargo", empresa: "Empresa", que_te_gustaria_lograr: "Quiere lograr", mayor_reto_hoy: "Mayor reto", comentario: "Comentario" };
  return `<dl class="entrada">${Object.entries(inscripcion)
    .filter(([, v]) => v)
    .map(([k, v]) => `<dt>${esc(etiquetas[k] || k)}</dt><dd>${esc(v)}</dd>`)
    .join("")}</dl>`;
}

function veredictoHtml(programa, accion, humana) {
  return `<div class="veredicto">
    <span class="eyebrow">${humana ? "Propuesta · la confirma una persona" : "Decisión"}</span>
    <h2>${esc(programa)}</h2>
    <p>${esc(accion)}</p>
  </div>`;
}

// Aviso honesto de qué son las cifras (texto del equipo, se muestra en Decisiones).
function avisoDatos() {
  const { metricas: m, modo } = estado.datos;
  if (modo === "mock") return "";
  return `<span class="badge" data-tip="JEV real sobre ${m ? m.perfiles : ""} inscripciones sintéticas. Hay que confirmarlo con una muestra real de 30X.">JEV real · perfiles sintéticos</span>`;
}

// ---------- Decisiones ----------
function detalleDecision(r) {
  const c = cat(), d = r.decision, j = r.respuestas_jev;
  const humana = d.ruta === "revision_humana";
  const acierto = d.accion === r.esperado.accion && d.programa === r.esperado.programa;
  const demo = estado.demografia?.[r.perfil_id];
  return `
    <div class="detalle-head"><span class="mono muted">${esc(r.perfil_id)} · ${esc(CANALES[r.estado_enviado.canal] || r.estado_enviado.canal)}${demo ? ` · ${esc(demo.ciudad)}` : ""}</span>${badgeRuta(d.ruta)}</div>
    ${veredictoHtml(c.programas[d.programa], c.acciones[d.accion_propuesta], humana)}
    <div class="seccion"><h4>Por qué</h4>${explicacionHtml(r.explicacion)}</div>
    <div class="seccion"><h4>Lo que escribió</h4>${entradaHtml(r.estado_enviado.inscripcion)}</div>
    <details class="plegable"><summary>Respuestas de JEV <span class="mono muted">${Math.round(r.latencia_ms)} ms</span></summary>
      ${respuestasJev(j.choices.rol, j.choices.dolor, j.choices.objetivo, j.scores.intencion.probabilidades, j.nouls.perfil_valido)}
    </details>
    <details class="plegable"><summary>¿Acertó? ${humana ? `<span class="badge">Lo decide una persona</span>` : `<span class="badge ${acierto ? "ok" : "mal"}">${acierto ? "Sí" : "No"}</span>`}</summary>
      <p class="correcta">Lo correcto: <b>${esc(c.programas[r.esperado.programa])}</b> · ${esc(c.acciones[r.esperado.accion])}</p>
    </details>`;
}

function textoDecision(r) {
  const demo = estado.demografia?.[r.perfil_id] || {};
  const insc = typeof r.estado_enviado.inscripcion === "string" ? r.estado_enviado.inscripcion : Object.values(r.estado_enviado.inscripcion).join(" ");
  return normal([r.perfil_id, cat().programas[r.decision.programa], ACCION_CORTA[r.decision.accion_propuesta], demo.ciudad, demo.pais, demo.origen, insc].join(" "));
}

function renderDecisiones() {
  const v = $("#vista-decisiones");
  const { decisiones } = estado.datos;
  const conteo = (ruta) => decisiones.filter((r) => r.decision.ruta === ruta).length;
  const opciones = [["todas", "Todas", decisiones.length], ...Object.entries(RUTAS).map(([k, x]) => [k, x.corto, conteo(k)])]
    .map(([k, t, n]) => `<button class="seg-item" data-filtro="${k}" aria-pressed="${estado.filtroRuta === k}">${t}<span class="seg-n">${n}</span></button>`)
    .join("");
  v.innerHTML = `
    ${encabezado("Decisiones", "Qué decidió con cada persona.<br><span class='tenue'>Y por qué.</span>", "", avisoDatos())}
    <div class="barra-herr">
      <div class="segmentado" role="group" aria-label="Filtrar por quién decide">${opciones}</div>
      ${buscadorLocal("buscar-dec", "Buscar por ID, programa, ciudad o lo que escribió", estado.busquedaDec)}
    </div>
    <div class="maestro-detalle">
      <div class="card lista" id="lista-dec"></div>
      <div class="card detalle entra" id="detalle"></div>
    </div>`;
  v.querySelectorAll("[data-filtro]").forEach((b) => b.addEventListener("click", () => { estado.filtroRuta = b.dataset.filtro; estado.seleccion = null; renderDecisiones(); }));
  $("#buscar-dec").addEventListener("input", (e) => { estado.busquedaDec = e.target.value; pintarListaDecisiones(); });
  pintarListaDecisiones();
}

function pintarListaDecisiones() {
  const { decisiones } = estado.datos;
  const q = normal(estado.busquedaDec).trim();
  const filtradas = decisiones.filter((r) => (estado.filtroRuta === "todas" || r.decision.ruta === estado.filtroRuta) && (!q || coincide(textoDecision(r), q)));
  const sel = filtradas.find((r) => r.perfil_id === estado.seleccion) || filtradas[0];
  const lista = $("#lista-dec");
  lista.innerHTML = filtradas.slice(0, 120)
    .map((r) => `<button class="fila ${sel && r.perfil_id === sel.perfil_id ? "activa" : ""}" data-id="${esc(r.perfil_id)}">
      <span class="fila-txt"><span class="fila-titulo">${esc(cat().programas[r.decision.programa])}</span>
      <span class="fila-sub"><span class="mono">${esc(r.perfil_id)}</span> · ${esc(ACCION_CORTA[r.decision.accion_propuesta])}</span></span>
      ${badgeRuta(r.decision.ruta)}</button>`)
    .join("") || `<p class="muted vacio-txt">Nada coincide con “${esc(estado.busquedaDec)}”.</p>`;
  $("#detalle").innerHTML = sel ? detalleDecision(sel) : "";
  lista.querySelectorAll(".fila").forEach((f) => f.addEventListener("click", () => elegirDecision(f.dataset.id)));
}

function elegirDecision(id) {
  estado.seleccion = id;
  document.querySelectorAll("#lista-dec .fila").forEach((x) => x.classList.toggle("activa", x.dataset.id === id));
  const det = $("#detalle");
  det.innerHTML = detalleDecision(estado.datos.decisiones.find((r) => r.perfil_id === id));
  animar(det);
  enfocarCiudad(estado.demografia?.[id], 2.2);
}

// ---------- Personas: demografía, origen y la Tierra ----------
const ESTADO_P = { filtros: {}, sel: null, busqueda: "" };
const FACETAS_SELECT = [["programa", "Programa sugerido"], ["edad", "Edad"], ["sector", "Sector"], ["tamano_empresa", "Tamaño de empresa"]];
const ETIQUETA_FACETA = { via: "Llegó por", origen: "Origen", pais: "País", programa: "Programa", edad: "Edad", sector: "Sector", tamano_empresa: "Empresa" };

function viaDe(origen) {
  if (origen.startsWith("Luma")) return "Luma";
  if (origen.startsWith("Campaña")) return "Campañas pagadas";
  return "Orgánico y referidos";
}

function gente() {
  if (estado.gente) return estado.gente;
  const demo = estado.demografia || {};
  const historiales = Object.fromEntries((estado.datos.historiales || []).map((h) => [h.perfil_id, h]));
  estado.gente = estado.datos.decisiones
    .filter((r) => demo[r.perfil_id])
    .map((r) => {
      const h = historiales[r.perfil_id];
      const d = demo[r.perfil_id];
      const insc = typeof r.estado_enviado.inscripcion === "string" ? r.estado_enviado.inscripcion : Object.values(r.estado_enviado.inscripcion).join(" ");
      return {
        ...r, demo: { ...d, via: viaDe(d.origen) }, historial: h?.historial || null,
        cambios: h ? h.historial.filter((e) => e.cambio_segmento).length : 0,
        texto: normal([r.perfil_id, d.ciudad, d.pais, d.origen, d.campana, d.sector, cat().programas[r.decision.programa], insc].join(" ")),
      };
    })
    .sort((a, b) => b.cambios - a.cambios || a.perfil_id.localeCompare(b.perfil_id));
  return estado.gente;
}

const valorDe = (p, k) => (k === "programa" ? cat().programas[p.decision.programa] : p.demo[k]);

function filtrar(excepto = null) {
  if (!estado.demografia) return [];
  const f = ESTADO_P.filtros, q = normal(ESTADO_P.busqueda).trim();
  return gente().filter((p) => (!q || coincide(p.texto, q)) && Object.entries(f).every(([k, v]) => k === excepto || valorDe(p, k) === v));
}

function contar(lista, k) {
  const c = {};
  lista.forEach((p) => { const v = valorDe(p, k); c[v] = (c[v] || 0) + 1; });
  return Object.entries(c).sort((a, b) => b[1] - a[1]);
}

function chipsFaceta(k, todos = "Todos") {
  const conteos = contar(filtrar(k), k);
  const activo = ESTADO_P.filtros[k];
  return `<div class="chips-faceta">
    <button class="chip-f" data-faceta="${k}" data-valor="" aria-pressed="${!activo}">${todos}</button>
    ${conteos.map(([v, n]) => `<button class="chip-f" data-faceta="${k}" data-valor="${esc(v)}" aria-pressed="${activo === v}">${esc(v)}<span>${n}</span></button>`).join("")}
  </div>`;
}

function selectFaceta(k, nombre) {
  const conteos = contar(filtrar(k), k);
  const activo = ESTADO_P.filtros[k] || "";
  return `<label class="sel-f">${nombre}<select data-faceta="${k}">
    <option value="">Todos</option>
    ${conteos.map(([v, n]) => `<option value="${esc(v)}" ${activo === v ? "selected" : ""}>${esc(v)} (${n})</option>`).join("")}
  </select></label>`;
}

function barrasFaceta(lista, k, max = 6) {
  const conteos = contar(lista, k).slice(0, max);
  const tope = conteos[0]?.[1] || 1;
  return `<ul class="barras">${conteos
    .map(([v, n]) => `<li><button data-faceta="${k}" data-valor="${esc(v)}" class="${ESTADO_P.filtros[k] === v ? "activa" : ""}">
      <span class="b-nombre">${esc(v)}</span>
      <span class="b-pista"><span style="width:${(n / tope) * 100}%"></span></span>
      <span class="b-n mono">${n}</span></button></li>`)
    .join("") || `<li class="muted pequeno">Sin datos.</li>`}</ul>`;
}

function lineaDeTiempo(historial) {
  const c = cat();
  return `<ol class="linea">${historial
    .map((e) => `<li class="${e.cambio_segmento ? "cambio" : ""}">
      <span class="t-fecha mono">${esc(e.fecha)}${e.llamo_jev ? "" : " · sin llamar a JEV"}</span>
      <span class="t-evento">${esc(e.evento)}</span>
      <span class="t-seg">${esc(c.programas[e.segmento.programa])} · ${esc(ACCION_CORTA[e.segmento.accion_propuesta || e.segmento.accion])}${e.segmento.ruta === "revision_humana" ? " (propuesta)" : ""}</span>
      ${e.cambios?.length ? `<span class="cambios">${e.cambios.map((x) => `<span>${esc(x)}</span>`).join("")}</span>` : ""}
    </li>`)
    .join("")}</ol>`;
}

function detalleGente(p) {
  const c = cat(), d = p.decision, demo = p.demo;
  const fila = (t, v) => `<div><dt>${t}</dt><dd>${v}</dd></div>`;
  return `
    <div class="detalle-head"><span class="mono muted">${esc(p.perfil_id)} · ${esc(demo.ciudad)}, ${esc(demo.pais)}</span>${badgeRuta(d.ruta)}</div>
    ${veredictoHtml(c.programas[d.programa], c.acciones[d.accion_propuesta], d.ruta === "revision_humana")}
    <dl class="ficha">
      ${fila("Llegó por", `${esc(demo.origen)}${demo.campana ? `<span class="muted"> · ${esc(demo.campana)}</span>` : ""}`)}
      ${fila("Canal", esc(CANALES[p.estado_enviado.canal] || p.estado_enviado.canal))}
      ${fila("Edad", esc(demo.edad))}
      ${fila("Sector", esc(demo.sector))}
      ${fila("Empresa", `${esc(demo.tamano_empresa)} personas`)}
      ${fila("Ubicación", `${esc(demo.ciudad)}, ${esc(demo.pais)}`)}
    </dl>
    <div class="seccion"><h4>Lo que escribió</h4>${entradaHtml(p.estado_enviado.inscripcion)}</div>
    ${p.historial ? `<div class="seccion"><h4>Lo que pasó después · ${p.cambios} ${p.cambios === 1 ? "cambio" : "cambios"} de segmento</h4>${lineaDeTiempo(p.historial)}</div>` : `<p class="muted pequeno seccion">Sin eventos después de inscribirse.</p>`}`;
}

function renderPersonas() {
  const v = $("#vista-reclasificacion");
  if (!estado.demografia) {
    v.innerHTML = encabezado("Personas", "Falta la demografía sintética", "Corre <code>python scripts/generar_demografia.py</code> y recarga.");
    return;
  }
  v.innerHTML = `
    <div class="personas-top">
      <div class="globo-hueco">
        <div class="globo-dato"><span class="etiqueta-mono">Personas</span><b class="mono" id="g-total">0</b><span id="g-sub"></span></div>
        <span class="badge aviso chip-demo" data-tip="30X no comparte datos demográficos: ubicación, edad, sector y origen son de ejemplo. El programa y la decisión sí son de Pálpito.">Demografía de ejemplo</span>
        <p class="globo-ayuda">Arrastra · clic en un país para filtrar</p>
      </div>
      <div class="card filtros-card" id="filtros-personas"></div>
    </div>
    <div id="personas-cuerpo"></div>`;
  v.addEventListener("click", (e) => {
    const b = e.target.closest("[data-faceta]");
    if (!b || b.tagName === "SELECT") return;
    const k = b.dataset.faceta, val = b.dataset.valor;
    if (k === "__todo") { ESTADO_P.filtros = {}; ESTADO_P.busqueda = ""; }
    else if (!val || ESTADO_P.filtros[k] === val) delete ESTADO_P.filtros[k];
    else ESTADO_P.filtros[k] = val;
    actualizarPersonas();
  });
  v.addEventListener("change", (e) => {
    const s = e.target.closest("select[data-faceta]");
    if (!s) return;
    if (s.value) ESTADO_P.filtros[s.dataset.faceta] = s.value;
    else delete ESTADO_P.filtros[s.dataset.faceta];
    actualizarPersonas();
  });
  v.addEventListener("input", (e) => {
    if (e.target.id !== "buscar-personas") return;
    ESTADO_P.busqueda = e.target.value;
    actualizarPersonas({ mantenerFoco: true });
  });
  actualizarPersonas();
}

function actualizarPersonas({ mantenerFoco = false } = {}) {
  const lista = filtrar();
  const f = ESTADO_P.filtros;
  const activos = Object.entries(f);
  const caja = $("#filtros-personas");
  if (!caja) return;
  const cursor = mantenerFoco ? $("#buscar-personas")?.selectionStart : null;
  caja.innerHTML = `
    <div class="filtros-head"><h3>Explorar</h3>${activos.length || ESTADO_P.busqueda ? `<button class="btn ghost chico" data-faceta="__todo" data-valor="">Limpiar</button>` : ""}</div>
    ${buscadorLocal("buscar-personas", "Buscar persona, ciudad, empresa, campaña…", ESTADO_P.busqueda)}
    ${activos.length ? `<div class="activos">${activos.map(([k, val]) => `<button class="pill-activa" data-faceta="${k}" data-valor="${esc(val)}">${ETIQUETA_FACETA[k]}: ${esc(val)} <span aria-hidden="true">×</span></button>`).join("")}</div>` : ""}
    <div class="grupo-f"><span class="grupo-t">Llegó por</span>${chipsFaceta("via", "Todos")}</div>
    <div class="grupo-f"><span class="grupo-t">País</span>${chipsFaceta("pais", "Todos")}</div>
    <div class="selects-f">${FACETAS_SELECT.map(([k, n]) => selectFaceta(k, n)).join("")}</div>`;
  if (mantenerFoco) { const i = $("#buscar-personas"); i.focus(); if (cursor != null) i.setSelectionRange(cursor, cursor); }

  const n = lista.length;
  const aVentas = lista.filter((p) => p.decision.accion_propuesta === "pasar_a_ventas").length;
  const solos = lista.filter((p) => p.decision.ruta !== "revision_humana").length;
  const paises = new Set(lista.map((p) => p.demo.pais)).size;
  $("#g-total").textContent = n;
  $("#g-sub").textContent = `${paises} ${paises === 1 ? "país" : "países"} · ${new Set(lista.map((p) => p.demo.ciudad)).size} ciudades`;

  if (!ESTADO_P.sel || !lista.find((p) => p.perfil_id === ESTADO_P.sel)) ESTADO_P.sel = lista[0]?.perfil_id || null;
  const sel = lista.find((p) => p.perfil_id === ESTADO_P.sel);
  const visibles = lista.slice(0, 80);
  const origen1 = contar(lista, "origen")[0];
  $("#personas-cuerpo").innerHTML = `
    <div class="stats">
      ${stat("Personas", n, activos.length || ESTADO_P.busqueda ? `de ${gente().length} en total` : "inscripciones de prueba")}
      ${stat("Listas para un asesor", n ? pct(aVentas / n, 0) : "—", `${aVentas} personas`)}
      ${stat("Sin intervención humana", n ? pct(solos / n, 0) : "—", "JEV o el LLM deciden")}
      ${stat("Origen principal", esc(origen1?.[0] || "—"), origen1 ? `${origen1[1]} personas` : "", "texto")}
    </div>
    <div class="grid-2">
      <div class="card"><div class="card-head"><h3>De dónde vienen</h3></div>${barrasFaceta(lista, "origen", 8)}</div>
      <div class="card"><div class="card-head"><h3>Programa sugerido</h3></div>${barrasFaceta(lista, "programa", 8)}</div>
    </div>
    <div class="maestro-detalle personas-lista">
      <div class="card lista">${visibles
        .map((p) => `<button class="fila ${p.perfil_id === ESTADO_P.sel ? "activa" : ""}" data-persona="${esc(p.perfil_id)}">
          <span class="fila-txt"><span class="fila-titulo">${esc(cat().programas[p.decision.programa])}</span>
          <span class="fila-sub"><span class="mono">${esc(p.perfil_id)}</span> · ${esc(p.demo.ciudad)} · ${esc(p.demo.origen)}</span></span>
          ${p.cambios ? `<span class="badge lima">${p.cambios} ${p.cambios === 1 ? "cambio" : "cambios"}</span>` : badgeRuta(p.decision.ruta)}</button>`)
        .join("") || `<p class="muted vacio-txt">Nadie cumple estos filtros.</p>`}
        ${n > visibles.length ? `<p class="muted pequeno vacio-txt">+${n - visibles.length} más</p>` : ""}</div>
      <div class="card detalle entra" id="detalle-persona">${sel ? detalleGente(sel) : ""}</div>
    </div>`;
  $("#personas-cuerpo").querySelectorAll(".fila").forEach((b) => b.addEventListener("click", () => elegirPersona(b.dataset.persona)));
  if (ESC.escena === "personas") actualizarGloboPersonas(lista);
}

function elegirPersona(id) {
  ESTADO_P.sel = id;
  document.querySelectorAll("#personas-cuerpo .fila").forEach((x) => x.classList.toggle("activa", x.dataset.persona === id));
  const p = gente().find((x) => x.perfil_id === id);
  const det = $("#detalle-persona");
  if (!det || !p) return;
  det.innerHTML = detalleGente(p);
  animar(det);
  enfocarCiudad(p.demo, 1.5);
}

function actualizarGloboPersonas(lista) {
  const g = ESC.g;
  if (!g || !estado.demografia) return;
  const porPais = {};
  lista.forEach((p) => { const en = PAIS_EN[p.demo.pais]; porPais[en] = (porPais[en] || 0) + 1; });
  const tope = Math.max(1, ...Object.values(porPais));
  const sel = ESTADO_P.filtros.pais ? PAIS_EN[ESTADO_P.filtros.pais] : null;
  ESC.paises.forEach((f) => {
    const nPais = porPais[f.properties.name] || 0;
    f.__n = nPais;
    f.__activo = nPais > 0;
    f.__alt = !nPais ? 0.004 : f.properties.name === sel ? 0.06 : 0.012 + 0.03 * (nPais / tope);
    f.__color = !nPais ? "rgba(0,0,0,0)" : `rgba(233,255,123,${f.properties.name === sel ? 0.85 : 0.18 + 0.5 * (nPais / tope)})`;
  });
  g.polygonsData([...ESC.paises]).htmlElementsData(sel ? ciudadesDe(lista).slice(0, 8) : paisesDe(lista)).ringsData([]);
  if (lista.length) {
    const lat = lista.reduce((s, p) => s + p.demo.lat, 0) / lista.length;
    const lng = lista.reduce((s, p) => s + p.demo.lon, 0) / lista.length;
    g.pointOfView({ lat: lat - 4, lng, altitude: alto(sel ? 1.45 : 2.35) }, QUIETO ? 0 : 1400);
  }
}

// ---------- Búsqueda global (⌘K) ----------
const SECCIONES = [
  { t: "Decisiones", s: "Qué decidió con cada persona y por qué", ir: "decisiones" },
  { t: "Personas", s: "Demografía, origen y el mapa", ir: "reclasificacion" },
  { t: "Reglas", s: "Umbrales y pesos de la política", ir: "politica" },
  { t: "Probar en vivo", s: "Clasifica una inscripción nueva", ir: "prueba" },
];
const BUS = { items: [], i: 0 };

function abrirBuscador() {
  $("#buscador").hidden = false;
  const q = $("#buscador-q");
  q.value = "";
  pintarBuscador("");
  requestAnimationFrame(() => q.focus());
}
function cerrarBuscador() { $("#buscador").hidden = true; }

function pintarBuscador(texto) {
  const q = normal(texto).trim();
  const secciones = SECCIONES.filter((x) => !q || coincide(normal(x.t + " " + x.s), q)).map((x) => ({ tipo: "seccion", ...x }));
  const personas = estado.demografia && q ? gente().filter((p) => coincide(p.texto, q)).slice(0, 7).map((p) => ({ tipo: "persona", p })) : [];
  BUS.items = [...personas, ...secciones];
  BUS.i = 0;
  const caja = $("#buscador-resultados");
  if (!BUS.items.length) { caja.innerHTML = `<p class="muted vacio-txt">Nada para “${esc(texto)}”.</p>`; return; }
  let html = "";
  if (personas.length) html += `<span class="bus-grupo">Personas</span>` + personas.map((it, i) => filaBuscador(it, i)).join("");
  if (secciones.length) html += `<span class="bus-grupo">Ir a</span>` + secciones.map((it, i) => filaBuscador(it, i + personas.length)).join("");
  caja.innerHTML = html;
  caja.querySelectorAll("[data-i]").forEach((b) => {
    b.addEventListener("click", () => elegirBuscador(Number(b.dataset.i)));
    b.addEventListener("pointermove", () => marcarBuscador(Number(b.dataset.i)));
  });
}

function filaBuscador(it, i) {
  if (it.tipo === "persona") {
    const p = it.p;
    return `<button class="bus-fila ${i === 0 ? "activa" : ""}" data-i="${i}" role="option"><span class="bus-ico mono">${esc(p.perfil_id.slice(-3))}</span>
      <span class="fila-txt"><span class="fila-titulo">${esc(cat().programas[p.decision.programa])}</span><span class="fila-sub">${esc(p.perfil_id)} · ${esc(p.demo.ciudad)}, ${esc(p.demo.pais)} · ${esc(p.demo.origen)}</span></span>${badgeRuta(p.decision.ruta)}</button>`;
  }
  return `<button class="bus-fila ${i === 0 ? "activa" : ""}" data-i="${i}" role="option"><span class="bus-ico">→</span><span class="fila-txt"><span class="fila-titulo">${esc(it.t)}</span><span class="fila-sub">${esc(it.s)}</span></span></button>`;
}

function marcarBuscador(i) {
  BUS.i = Math.max(0, Math.min(BUS.items.length - 1, i));
  document.querySelectorAll(".bus-fila").forEach((b) => b.classList.toggle("activa", Number(b.dataset.i) === BUS.i));
  document.querySelector(`.bus-fila[data-i="${BUS.i}"]`)?.scrollIntoView({ block: "nearest" });
}

function elegirBuscador(i) {
  const it = BUS.items[i];
  if (!it) return;
  cerrarBuscador();
  if (it.tipo === "seccion") { mostrarVista(it.ir); return; }
  ESTADO_P.filtros = {}; ESTADO_P.busqueda = ""; ESTADO_P.sel = it.p.perfil_id;
  mostrarVista("reclasificacion");
  actualizarPersonas();
  enfocarCiudad(it.p.demo, 1.4);
  setTimeout(() => $("#detalle-persona")?.scrollIntoView({ behavior: QUIETO ? "auto" : "smooth", block: "start" }), 250);
}

$("#abrir-buscador").addEventListener("click", abrirBuscador);
$("#buscador").addEventListener("click", (e) => { if (e.target.closest("[data-cerrar]")) cerrarBuscador(); });
$("#buscador-q").addEventListener("input", (e) => pintarBuscador(e.target.value));
document.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); $("#buscador").hidden ? abrirBuscador() : cerrarBuscador(); return; }
  if ($("#buscador").hidden) {
    if (e.key === "/" && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) { e.preventDefault(); abrirBuscador(); }
    return;
  }
  if (e.key === "Escape") cerrarBuscador();
  else if (e.key === "ArrowDown") { e.preventDefault(); marcarBuscador(BUS.i + 1); }
  else if (e.key === "ArrowUp") { e.preventDefault(); marcarBuscador(BUS.i - 1); }
  else if (e.key === "Enter") { e.preventDefault(); elegirBuscador(BUS.i); }
});

async function enviar(url, cuerpo) {
  const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cuerpo) });
  const datos = await r.json();
  if (!r.ok) throw new Error(datos.error || "Error del servidor");
  return datos;
}

// ---------- Probar en vivo: lote de perfiles del CRM (CSV de hasta 100 filas) ----------
// Mismo formato que el archivo de perfiles de 30X. El límite es a propósito: es una demo en vivo y así
// nadie sube la base completa por error. Para lotes grandes están los scripts de evaluación.
const LIMITE_LOTE = 100;
const COLUMNAS_PERFIL = ["ID", "Rol", "Dolor principal", "Objetivo principal", "Temas de interés", "Programa", "Programa sugerido"];
// Perfiles inventados con las mismas categorías que usa 30X (no son datos del CRM).
const EJEMPLO_PERFILES = [
  ["EJ-01", "Fundador, socio o CEO", "No tiene proceso comercial estructurado", "Construir una máquina de ventas", "sales, gtm", "Sales Machine", "Sales Machine"],
  ["EJ-02", "Líder comercial o de ventas", "Vive de referidos y prospecta a mano", "Vender más", "sales, ai", "AI Sales", "AI Sales"],
  ["EJ-03", "Sin dato de rol", "No declaró ningún dolor", "Formarse (sobre todo en IA)", "ai", "AI Sales", "Sin programa sugerido"],
  ["EJ-04", "Perfil técnico (ingeniería, datos, producto)", "No declaró ningún dolor", "Automatizar con IA", "ai, product", "AI for devs", "Hardcore AI"],
  ["EJ-05", "Fundador, socio o CEO", "Expansión internacional sin método", "Expandirse a otros países", "gtm, leadership", "30X Executive Program", "Inmersión Ejecutiva"],
  ["EJ-06", "Director, VP o C-level (no dueño)", "No declaró ningún dolor", "Automatizar con IA", "ai, leadership", "AI for Executives", "Sin programa sugerido"],
  ["EJ-07", "Gerente o jefe de área", "Procesos manuales y rezago tecnológico", "Automatizar con IA", "ai, ops", "AI Second Brain", "Hardcore AI"],
  ["EJ-08", "Fundador, socio o CEO", "El dueño es el cuello de botella y no delega", "Delegar y pasar a un rol estratégico", "leadership, ops", "30X Executive Program", "Inmersión Ejecutiva"],
  ["EJ-09", "Líder comercial o de ventas", "Ventas estancadas o cayendo", "Construir una máquina de ventas", "sales, negotiation", "Sales Machine", "Sales Machine"],
  ["EJ-10", "Sin dato de rol", "No declaró ningún dolor", "Automatizar con IA", "ai, sales", "AI Sales", "AI Sales"],
  ["EJ-11", "Fundador, socio o CEO", "Capital y flujo de caja para crecer", "Levantar capital", "fundraising, finance", "30X Executive Program", "Inmersión Ejecutiva"],
  ["EJ-12", "Gerente o jefe de área", "No declaró ningún dolor", "Vender más", "sales", "Sales Machine", "AI Sales"],
  ["EJ-13", "Otro rol", "No declaró ningún dolor", "Otro objetivo", "—", "", "Sin programa sugerido"],
  ["EJ-14", "Director, VP o C-level (no dueño)", "Falta de claridad estratégica para escalar", "Transformar el modelo de negocio", "leadership, finance", "30X Executive Program", "Inmersión Ejecutiva"],
  ["EJ-15", "Perfil técnico (ingeniería, datos, producto)", "Procesos manuales y rezago tecnológico", "Automatizar con IA", "ai", "AI for devs", "Hardcore AI"],
  ["EJ-16", "Fundador, socio o CEO", "No declaró ningún dolor", "Entrar a una red de pares", "leadership", "30X Executive Program", "Inmersión Ejecutiva"],
  ["EJ-17", "Sin dato de rol", "No declaró ningún dolor", "Vender más", "sales, marketing", "AI Sales", "AI Sales"],
  ["EJ-18", "Gerente o jefe de área", "Equipo: contratar, retener y vencer la resistencia al cambio", "Desarrollar liderazgo y equipo", "leadership, hiring", "", "Inmersión Ejecutiva"],
  ["EJ-19", "Líder comercial o de ventas", "No declaró ningún dolor", "Automatizar con IA", "sales, ai", "AI Sales", "AI Sales"],
  ["EJ-20", "Sin dato de rol", "No declaró ningún dolor", "Automatizar con IA", "ai", "AI Second Brain", "Sin programa sugerido"],
];
const LOTE = { filas: [], resultados: [], sel: 0 };

function partirCsv(texto) {
  const primera = texto.split(/\r?\n/, 1)[0];
  const sep = (primera.match(/;/g) || []).length > (primera.match(/,/g) || []).length ? ";" : ",";
  const filas = [];
  let fila = [], campo = "", comillas = false;
  for (let i = 0; i < texto.length; i++) {
    const c = texto[i];
    if (comillas) {
      if (c === '"' && texto[i + 1] === '"') { campo += '"'; i++; }
      else if (c === '"') comillas = false;
      else campo += c;
    } else if (c === '"') comillas = true;
    else if (c === sep) { fila.push(campo); campo = ""; }
    else if (c === "\n" || c === "\r") {
      if (c === "\r" && texto[i + 1] === "\n") i++;
      fila.push(campo); filas.push(fila); fila = []; campo = "";
    } else campo += c;
  }
  if (campo || fila.length) { fila.push(campo); filas.push(fila); }
  return filas.filter((f) => f.some((x) => x.trim()));
}

function filasDesdeCsv(texto) {
  const filas = partirCsv(texto.replace(/^﻿/, ""));
  if (!filas.length) throw new Error("El archivo está vacío.");
  const enc = filas[0].map((h) => h.trim());
  const clave = enc.map(normal);
  const faltan = ["rol", "dolor principal", "objetivo principal"].filter((c) => !clave.includes(c));
  if (faltan.length === 3) throw new Error("No encuentro las columnas Rol, Dolor principal y Objetivo principal. Descarga la plantilla para ver el formato.");
  return filas.slice(1).map((f) => Object.fromEntries(enc.map((h, i) => [h, (f[i] || "").trim()])));
}

function csvCelda(v) {
  const t = String(v ?? "");
  return /[",\n;]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t;
}

function descargar(nombre, texto) {
  const blob = new Blob(["﻿" + texto], { type: "text/csv;charset=utf-8" });
  const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(blob), download: nombre });
  a.click();
  URL.revokeObjectURL(a.href);
}

function errorLote(msg, accion = "") {
  const e = $("#lote-error");
  e.innerHTML = msg + accion;
  e.hidden = !msg;
}

async function procesarLote(filas) {
  errorLote("");
  if (filas.length > LIMITE_LOTE) {
    errorLote(`El archivo tiene ${filas.length} perfiles y el máximo es ${LIMITE_LOTE}. `, `<button type="button" class="btn ghost chico" id="lote-recortar">Usar solo los primeros ${LIMITE_LOTE}</button>`);
    $("#lote-recortar").addEventListener("click", () => procesarLote(filas.slice(0, LIMITE_LOTE)));
    return;
  }
  const t0 = performance.now();
  try {
    const r = await enviar("/api/perfiles", { filas });
    LOTE.filas = filas; LOTE.resultados = r.resultados; LOTE.sel = 0; LOTE.ms = performance.now() - t0;
    pintarLote();
    $("#lote-resultado").scrollIntoView({ behavior: QUIETO ? "auto" : "smooth", block: "start" });
  } catch (x) { errorLote(x.message); }
}

// ¿Pálpito coincide con lo que dice el CRM? Usa el mismo mapeo CRM → catálogo de politica.json.
function coincidencias(x) {
  const mapa = estado.datos.politica?.perfiles_por_programa?.programa_catalogo || {};
  const crm = x.comparar.programa_crm, sug = x.comparar.programa_sugerido_30x;
  return {
    crm: crm ? (mapa[crm] ? mapa[crm] === x.programa : null) : undefined,
    sugerido: sug ? normal(sug) === normal(x.programa_nombre) : undefined,
  };
}

function marca(v) {
  if (v === undefined) return `<span class="muted">—</span>`;
  if (v === null) return `<span class="muted">sin equivalente</span>`;
  return v ? `<span class="badge ok">Coincide</span>` : `<span class="badge">Distinto</span>`;
}

function detalleLote(x, i) {
  const c = cat(), e = x.entrada, k = coincidencias(x);
  const fila = (t, v) => `<div><dt>${t}</dt><dd>${v}</dd></div>`;
  return `
    <div class="detalle-head"><span class="mono muted">${esc(x.id || `Fila ${i + 1}`)}</span>${badgeRuta(x.ruta)}</div>
    ${veredictoHtml(x.programa_nombre, x.accion_texto, x.ruta === "revision_humana")}
    ${x.no_reconocidos.length ? `<p class="error">No reconocido: ${esc(x.no_reconocidos.join(", "))}</p>` : ""}
    <div class="seccion"><h4>Por qué</h4>${explicacionHtml(x.explicacion)}</div>
    <div class="seccion"><h4>Perfil</h4>
      <dl class="ficha">
        ${fila("Rol", esc(c.rol[e.rol] || e.rol))}
        ${fila("Dolor", esc(c.dolor[e.dolor] || e.dolor))}
        ${fila("Objetivo", esc(c.objetivo[e.objetivo] || e.objetivo))}
        ${fila("Temas", e.temas.length ? esc(e.temas.map((t) => TEMAS_ES[t] || t).join(", ")) : "—")}
        ${fila("Intención", `${esc(e.intencion)}${e.intencion_supuesta ? ` <span class="ilustrativo">supuesta</span>` : ""}`)}
      </dl>
    </div>
    <div class="seccion"><h4>Frente a 30X</h4>
      <dl class="ficha">
        ${fila("CRM", `${esc(x.comparar.programa_crm || "—")} ${marca(k.crm)}`)}
        ${fila("Sugerido por 30X", `${esc(x.comparar.programa_sugerido_30x || "—")} ${marca(k.sugerido)}`)}
      </dl>
    </div>`;
}

function pintarLote() {
  const r = LOTE.resultados;
  const rutas = {}, programas = {};
  r.forEach((x) => { rutas[x.ruta] = (rutas[x.ruta] || 0) + 1; programas[x.programa_nombre] = (programas[x.programa_nombre] || 0) + 1; });
  const k = r.map(coincidencias);
  const tasa = (campo) => {
    const v = k.map((x) => x[campo]).filter((x) => x === true || x === false);
    return v.length ? { pct: pct(v.filter(Boolean).length / v.length, 0), n: v.length } : null;
  };
  const sug = tasa("sugerido"), crm = tasa("crm");
  const asesor = r.filter((x) => x.accion_propuesta === "pasar_a_ventas").length;
  const top = Object.entries(programas).sort((a, b) => b[1] - a[1]);
  const caja = $("#lote-resultado");
  caja.innerHTML = `
    <div class="stats">
      ${stat("Perfiles", r.length, `en ${Math.max(1, Math.round(LOTE.ms))} ms`)}
      ${stat("Programa más sugerido", esc(top[0][0]), `${top[0][1]} perfiles`, "texto")}
      ${stat("Coincide con 30X", sug ? sug.pct : "—", sug ? `de ${sug.n} con programa sugerido` : "sin columna Programa sugerido")}
      ${stat("Coincide con el CRM", crm ? crm.pct : "—", crm ? `de ${crm.n} con programa en el CRM` : "sin columna Programa")}
    </div>
    <div class="card lote-rutas">
      <div class="card-head"><h3>Programa sugerido</h3>${asesor ? `<p>${asesor} listos para un asesor</p>` : ""}</div>
      <ul class="barras">${top.map(([p, n]) => `<li><button type="button" disabled><span class="b-nombre">${esc(p)}</span><span class="b-pista"><span style="width:${(n / top[0][1]) * 100}%"></span></span><span class="b-n mono">${n}</span></button></li>`).join("")}</ul>
    </div>
    <div class="maestro-detalle">
      <div class="card lista">
        <div class="lista-head"><span class="muted pequeno">${r.length} perfiles</span><button type="button" class="btn ghost chico" id="lote-descargar">Descargar resultados</button></div>
        ${r.map((x, i) => `<button class="fila ${i === LOTE.sel ? "activa" : ""}" data-i="${i}"><span class="fila-txt"><span class="fila-titulo">${esc(x.programa_nombre)}</span><span class="fila-sub"><span class="mono">${esc(x.id || "#" + (i + 1))}</span> · ${esc(cat().rol[x.entrada.rol] || x.entrada.rol)}</span></span>${k[i].sugerido === true ? `<span class="badge ok">= 30X</span>` : badgeRuta(x.ruta)}</button>`).join("")}
      </div>
      <div class="card detalle entra" id="lote-detalle">${detalleLote(r[LOTE.sel], LOTE.sel)}</div>
    </div>`;
  caja.querySelectorAll(".fila").forEach((f) => f.addEventListener("click", () => {
    LOTE.sel = Number(f.dataset.i);
    caja.querySelectorAll(".fila").forEach((y) => y.classList.toggle("activa", y === f));
    $("#lote-detalle").innerHTML = detalleLote(r[LOTE.sel], LOTE.sel);
    animar($("#lote-detalle"));
  }));
  $("#lote-descargar").addEventListener("click", () => {
    const enc = ["ID", "Rol", "Dolor principal", "Objetivo principal", "Temas de interés", "Programa Pálpito", "Siguiente paso", "Quién decide", "Coincide con programa sugerido 30X", "Explicación"];
    const lineas = r.map((x, i) => {
      const f = LOTE.filas[i], kk = coincidencias(x);
      const g = (n) => Object.entries(f).find(([h]) => normal(h) === normal(n))?.[1] || "";
      return [x.id || "", g("Rol"), g("Dolor principal"), g("Objetivo principal"), g("Temas de interés"), x.programa_nombre, x.accion_texto,
        RUTAS[x.ruta]?.nombre || x.ruta, kk.sugerido === undefined ? "" : kk.sugerido ? "sí" : "no", x.explicacion];
    });
    descargar("palpito-resultados.csv", [enc, ...lineas].map((l) => l.map(csvCelda).join(",")).join("\n"));
  });
}

function prepararLote() {
  const comoFilas = (datos) => datos.map((f) => Object.fromEntries(COLUMNAS_PERFIL.map((k, i) => [k, f[i]])));
  $("#lote-ejemplo").addEventListener("click", () => procesarLote(comoFilas(EJEMPLO_PERFILES)));
  $("#lote-plantilla").addEventListener("click", () => descargar("palpito-plantilla.csv", [COLUMNAS_PERFIL, ...EJEMPLO_PERFILES.slice(0, 3)].map((l) => l.map(csvCelda).join(",")).join("\n")));
  const leer = async (archivo) => {
    if (!archivo) return;
    if (!/\.csv$/i.test(archivo.name)) { errorLote("Sube un archivo .csv. Desde Excel: Archivo → Guardar como → CSV UTF-8."); return; }
    if (archivo.size > 1024 * 1024) { errorLote("El archivo pesa más de 1 MB: no parece un lote de 100 perfiles."); return; }
    try { procesarLote(filasDesdeCsv(await archivo.text())); }
    catch (x) { errorLote(x.message); }
  };
  $("#lote-archivo").addEventListener("change", (e) => { leer(e.target.files[0]); e.target.value = ""; });
  const zona = $("#lote-zona");
  ["dragenter", "dragover"].forEach((t) => zona.addEventListener(t, (e) => { e.preventDefault(); zona.classList.add("encima"); }));
  ["dragleave", "drop"].forEach((t) => zona.addEventListener(t, () => zona.classList.remove("encima")));
  zona.addEventListener("drop", (e) => { e.preventDefault(); leer(e.dataTransfer.files[0]); });
}

// ---------- Guardrail ----------
const NOMBRES_GUARDRAIL = {
  promesas: "¿Promete algo sin respaldo?",
  tono: "¿Tono adecuado?",
  coherencia: "¿Habla del programa sugerido?",
  instrucciones: "¿Trae instrucciones al sistema?",
};

function veredictoGuardrail(g) {
  const clase = g.estado === "aprobado" ? "ok" : g.estado === "bloqueado" ? "mal" : "aviso";
  const filas = Object.entries(g.probabilidades)
    .map(([k, p]) => `<span>${esc(NOMBRES_GUARDRAIL[k] || k)}</span><span class="pista"><span class="relleno" style="width:${(p * 100).toFixed(1)}%"></span></span><span class="num">sí ${pct(p, 0)}</span>`)
    .join("");
  return `<div class="guardia">
    <div class="guardia-head"><span class="badge ${clase}">${esc(g.estado_texto)}</span><span class="mono muted pequeno">Guardrail de JEV · ${Math.round(g.latencia_ms)} ms</span></div>
    ${g.razones.length ? `<ul class="razones">${g.razones.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>` : ""}
    <div class="probs">${filas}</div>
  </div>`;
}

function prepararGuardrail() {
  const form = $("#form-guardrail");
  $("#programa-guardrail").innerHTML = Object.entries(cat().programas).filter(([k]) => k !== "ninguno")
    .map(([k, v]) => `<option value="${k}" ${k === "sales_machine" ? "selected" : ""}>${esc(v)}</option>`).join("");
  form.querySelectorAll("[data-mensaje]").forEach((b) => b.addEventListener("click", () => { form.elements.mensaje.value = b.dataset.mensaje; }));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const err = $("#error-guardrail"), boton = form.querySelector("button[type=submit]"), caja = $("#resultado-guardrail");
    boton.disabled = true; err.hidden = true;
    try {
      const g = await enviar("/api/guardrail", { mensaje: form.elements.mensaje.value, programa: form.elements.programa.value });
      caja.classList.remove("muted");
      caja.innerHTML = veredictoGuardrail(g);
      animar(caja);
    } catch (x) { err.textContent = x.message; err.hidden = false; }
    boton.disabled = false;
  });
}

// ---------- Reglas (política) ----------
const CONTROLES = [
  ["umbrales", "perfil_valido_min", "Perfil genuino", "Debajo, lo revisa una persona.", 0.3, 0.99, 0.01],
  ["umbrales", "confianza_choice_min", "Certeza en rol, dolor y objetivo", "Si duda y cambia la decisión, pide ayuda.", 0.1, 0.9, 0.01],
  ["umbrales", "listo_ventas_revision", "Proponer un asesor", "Desde aquí propone pasar a ventas.", 0.3, 0.9, 0.01],
  ["umbrales", "listo_ventas_auto", "Asesor sin confirmar", "Desde aquí no necesita a una persona.", 0.5, 0.99, 0.01],
  ["umbrales", "confianza_rol_ventas", "Certeza del rol para ventas", "Debe saber si puede decidir la compra.", 0.3, 0.99, 0.01],
  ["pesos", "intencion", "Intención de compra", "", 0, 1, 0.05],
  ["pesos", "poder_decision", "Poder de decisión (rol)", "", 0, 1, 0.05],
  ["pesos", "claridad", "Claridad de la necesidad", "", 0, 1, 0.05],
  ["pesos", "compromiso", "Compromiso observado", "", 0, 1, 0.05],
];

function valorActual(grupo, clave) {
  const p = estado.datos.politica;
  return grupo === "umbrales" ? p.umbrales[clave] : p.afinidad.pesos[clave];
}

function delta(nuevo, viejo, subeEsBueno = true) {
  const d = (nuevo - viejo) * 100;
  if (Math.abs(d) < 0.05) return `<span class="delta">Igual que la política actual</span>`;
  const bueno = (d > 0) === subeEsBueno;
  return `<span class="delta ${bueno ? "bueno" : "malo"}">${d > 0 ? "▲ +" : "▼ "}${d.toLocaleString("es-CO", { maximumFractionDigits: 1 })} pts frente a la actual</span>`;
}

function seguridad(n) {
  return `<span class="${n === 0 ? "ok" : "mal"}">${n}</span>`;
}

function resultadosPolitica(r) {
  const a = r.actual, s = r.simulada;
  return `
    <div class="card-head"><h3>Efecto en ${s.perfiles} inscripciones</h3><p>Al instante, sin llamar a JEV</p></div>
    <div class="stats compactas">
      ${stat("JEV decide solo", pct(s.automatizacion, 1), delta(s.automatizacion, a.automatizacion))}
      ${stat("Precisión al actuar solo", pct(s.precision, 1), delta(s.precision, a.precision))}
      ${stat("Pases indebidos a ventas", seguridad(s.pases_a_ventas_indebidos), `Política actual: ${a.pases_a_ventas_indebidos}`)}
      ${stat("Perfiles trampa procesados solos", seguridad(s.invalidos_automaticos), `Política actual: ${a.invalidos_automaticos}`)}
    </div>
    <div class="seccion"><h4>Política actual</h4>${barraRutas(a.rutas, a.perfiles)}</div>
    <div class="seccion"><h4>Con estos valores</h4>${barraRutas(s.rutas, s.perfiles)}</div>`;
}

let temporizador = null;
async function simularPolitica() {
  const cuerpo = { umbrales: {}, pesos: {} };
  document.querySelectorAll("#vista-politica input[type=range]").forEach((i) => {
    cuerpo[i.dataset.grupo][i.name] = Number(i.value);
    $("#out-" + i.name).value = Number(i.value).toFixed(2);
  });
  try {
    const r = await enviar("/api/simular", cuerpo);
    estado.politicaSimulada = r.politica;
    $("#resultado-politica").innerHTML = resultadosPolitica(r);
  } catch (x) {
    $("#resultado-politica").innerHTML = `<p class="error">${esc(x.message)}</p>`;
  }
}

function controles(grupo) {
  return CONTROLES.filter((c) => c[0] === grupo)
    .map(([g, clave, etiqueta, ayuda, min, max, paso]) => `
      <div class="control">
        <div class="control-top"><label for="ctl-${clave}">${esc(etiqueta)}</label><output id="out-${clave}" class="mono">${Number(valorActual(g, clave)).toFixed(2)}</output></div>
        <input id="ctl-${clave}" type="range" name="${clave}" data-grupo="${g}" min="${min}" max="${max}" step="${paso}" value="${valorActual(g, clave)}">
        ${ayuda ? `<p class="ayuda">${esc(ayuda)}</p>` : ""}
      </div>`)
    .join("");
}

function renderPolitica() {
  const v = $("#vista-politica");
  v.innerHTML = `
    ${encabezado("Reglas", "Tú pones los límites.<br><span class='tenue'>Pálpito los respeta.</span>")}
    <div class="maestro-detalle politica">
      <div class="card">
        <div class="card-head"><h3>Umbrales</h3></div>
        ${controles("umbrales")}
        <details class="plegable"><summary>Pesos de afinidad</summary>${controles("pesos")}</details>
        <div class="acciones">
          <button type="button" class="btn ghost" id="restablecer">Volver a la política actual</button>
          <button type="button" class="btn ghost" id="descargar">Descargar configuración</button>
        </div>
      </div>
      <div class="card detalle" id="resultado-politica"><p class="muted">Calculando…</p></div>
    </div>`;
  v.querySelectorAll("input[type=range]").forEach((i) => i.addEventListener("input", () => {
    $("#out-" + i.name).value = Number(i.value).toFixed(2);
    clearTimeout(temporizador);
    temporizador = setTimeout(simularPolitica, 120);
  }));
  $("#restablecer").addEventListener("click", renderPolitica);
  $("#descargar").addEventListener("click", () => {
    const blob = new Blob([JSON.stringify(estado.politicaSimulada || estado.datos.politica, null, 2)], { type: "application/json" });
    const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(blob), download: "politica_propuesta.json" });
    a.click();
    URL.revokeObjectURL(a.href);
  });
  simularPolitica();
}

// ---------- Inicio ----------
async function iniciar() {
  try {
    estado.datos = await (await fetch("/api/datos")).json();
    estado.demografia = await fetch("demografia.json").then((r) => (r.ok ? r.json() : null)).catch(() => null);
  } catch {
    $("#vista-reclasificacion").innerHTML = encabezado("Sin conexión", "No se pudo conectar con el servidor", "Ejecuta <code>python -m app.servidor</code>.");
    return;
  }
  if (estado.demografia) gente();
  const { modo, llm } = estado.datos;
  const m = $("#modo");
  m.innerHTML = `<span class="punto" style="background:${modo === "mock" ? "var(--aviso)" : "var(--ok)"}"></span>${modo === "mock" ? "Simulado" : "JEV real"}`;
  m.title = `JEV ${modo === "mock" ? "simulado" : "real"} · LLM ${llm === "off" ? "apagado" : llm === "mock" ? "simulado" : "real"}`;
  iniciarEscena();
  renderDecisiones();
  renderPersonas();
  renderPolitica();
  prepararLote();
  prepararGuardrail();
}
iniciar();

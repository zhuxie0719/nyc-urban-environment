/* global L, d3 */

const ZIP_GEOJSON_PATH = "./data/nyc_zip_boundaries.geojson";
const ENV_DATA_PATH = "../output/final_data.environment.json";

const state = {
  map: null,
  zipLayer: null,
  lockedLayer: null,
  lockedZip: null,
  suppressNextMapClick: false,
  envRecords: [],
  envByZip: new Map(),
  threshold: 30,
  checks: {
    air: false,
    noise: false,
    green: false,
  },
};

init();

async function init() {
  wireControls();
  const [zipGeojson, envRecords] = await Promise.all([d3.json(ZIP_GEOJSON_PATH), d3.json(ENV_DATA_PATH)]);
  state.envRecords = envRecords || [];
  indexEnvironmentData(envRecords);
  renderInsights();
  joinEnvironmentToGeojson(zipGeojson);
  initMap(zipGeojson);
  drawRadarPlaceholder();
}

function wireControls() {
  const scoreRange = document.getElementById("scoreRange");
  const scoreLabel = document.getElementById("scoreLabel");
  const airCheck = document.getElementById("airCheck");
  const noiseCheck = document.getElementById("noiseCheck");
  const greenCheck = document.getElementById("greenCheck");

  scoreRange.addEventListener("input", () => {
    state.threshold = Number(scoreRange.value);
    scoreLabel.textContent = String(state.threshold);
    applyFilters();
  });

  airCheck.addEventListener("change", () => {
    state.checks.air = airCheck.checked;
    applyFilters();
  });
  noiseCheck.addEventListener("change", () => {
    state.checks.noise = noiseCheck.checked;
    applyFilters();
  });
  greenCheck.addEventListener("change", () => {
    state.checks.green = greenCheck.checked;
    applyFilters();
  });
}

function indexEnvironmentData(records) {
  for (const row of records) {
    state.envByZip.set(String(row.zip_code), row.environment);
  }
}

function joinEnvironmentToGeojson(geojson) {
  for (const feature of geojson.features) {
    const zip = getFeatureZip(feature.properties);
    const env = state.envByZip.get(zip);
    if (!env) {
      feature.properties.environment_score = 50;
      feature.properties.air_quality_score = 50;
      feature.properties.noise_score = 50;
      feature.properties.green_score = 50;
      feature.properties.has_data = 0;
      continue;
    }
    feature.properties.environment_score = env.environment_score;
    feature.properties.air_quality_score = env.air_quality_score;
    feature.properties.noise_score = env.noise_score;
    feature.properties.green_score = env.green_score;
    feature.properties.has_data = 1;
  }
}

function getFeatureZip(props) {
  const raw =
    props.ZIPCODE ||
    props.zip_code ||
    props.postalCode ||
    props.MODZCTA ||
    props.modzcta ||
    "";
  const m = String(raw).match(/\d{5}/);
  return m ? m[0] : "";
}

/** GeoJSON 中的邮局常用名 PO_NAME + 行政区 borough，近似对应片区（非官方邻里边界）。 */
function getPlaceLabelFromProps(props) {
  const po = String(props.PO_NAME || props.po_name || props.poName || "").trim();
  const boro = String(props.borough || props.BOROUGH || "").trim();
  if (po && boro) return `${po}（${boro}）`;
  if (po) return po;
  if (boro) return boro;
  return "";
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function initMap(geojson) {
  const map = L.map("map", {
    center: [40.72, -73.94],
    zoom: 10,
    zoomControl: true,
  });
  state.map = map;

  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(map);

  renderZipLayer(geojson);
  map.on("click", () => {
    if (state.suppressNextMapClick) return;
    clearLockedSelection();
  });
}

function renderZipLayer(geojson) {
  if (!state.map) return;
  if (state.zipLayer) {
    state.map.removeLayer(state.zipLayer);
  }

  state.zipLayer = L.geoJSON(geojson, {
    style: (feature) => {
      const score = Number(feature.properties.environment_score || 0);
      return {
        color: "rgba(255,255,255,0.9)",
        weight: 1,
        opacity: 1,
        lineCap: "round",
        lineJoin: "round",
        fillColor: getScoreColor(score),
        fillOpacity: 0.78,
      };
    },
    onEachFeature: (feature, layer) => {
      const zip = getFeatureZip(feature.properties);
      const placeLabel = getPlaceLabelFromProps(feature.properties);
      const score = Number(feature.properties.environment_score || 0);
      const hasData = Number(feature.properties.has_data) === 1;
      const placeHtml = placeLabel
        ? `<div class="tip-place">${escapeHtml(placeLabel)}</div>`
        : "";
      layer.bindTooltip(
        hasData
          ? `<div class="tip-inner"><strong>ZIP ${escapeHtml(zip)}</strong>${placeHtml}<div class="tip-score">环境综合分 ${escapeHtml(String(score))}</div></div>`
          : `<div class="tip-inner"><strong>ZIP ${escapeHtml(zip)}</strong>${placeHtml}<div class="tip-score tip-score--muted">暂无对齐数据</div></div>`,
        {
          sticky: true,
          direction: "top",
          opacity: 1,
          className: "env-tooltip",
        }
      );

      layer.on("mousemove", () => {
        if (!state.lockedLayer) drawRadarByFeature(feature);
      });
      layer.on("click", (e) => {
        state.suppressNextMapClick = true;
        window.setTimeout(() => {
          state.suppressNextMapClick = false;
        }, 0);
        if (e && e.originalEvent) L.DomEvent.stop(e.originalEvent);
        toggleLayerLock(layer);
      });
    },
  }).addTo(state.map);

  const bounds = state.zipLayer.getBounds();
  if (bounds.isValid()) {
    state.map.fitBounds(bounds, { padding: [20, 20] });
  }
  applyFilters();
}

function applyFilters() {
  if (!state.zipLayer) return;
  state.zipLayer.eachLayer((layer) => {
    const p = layer.feature.properties;
    if (passFilters(p)) {
      const score = Number(p.environment_score || 0);
      layer.setStyle({
        fillOpacity: 0.78,
        fillColor: getScoreColor(score),
        color: "rgba(255,255,255,0.88)",
        weight: 1,
        opacity: 1,
        lineCap: "round",
        lineJoin: "round",
      });
    } else {
      layer.setStyle({
        fillOpacity: 0.12,
        fillColor: "#d1d5db",
        color: "rgba(148,163,184,0.7)",
        weight: 0.5,
        opacity: 1,
        lineCap: "round",
        lineJoin: "round",
      });
    }
  });
  applyLockedStyle();
}

function passFilters(p) {
  if (Number(p.environment_score) < state.threshold) return false;
  if (state.checks.air && Number(p.air_quality_score) < 60) return false;
  if (state.checks.noise && Number(p.noise_score) < 60) return false;
  if (state.checks.green && Number(p.green_score) < 60) return false;
  return true;
}

function getScoreColor(score) {
  if (score >= 75) return "#16a34a";
  if (score >= 50) return "#84cc16";
  if (score >= 25) return "#f59e0b";
  return "#ef4444";
}

function toggleLayerLock(layer) {
  const zip = getFeatureZip(layer.feature.properties);
  if (state.lockedLayer === layer) {
    clearLockedSelection();
    return;
  }
  // 换选另一区块时，先清空锁定并统一重算样式，否则上一块仍保留高亮描边
  state.lockedLayer = null;
  state.lockedZip = null;
  applyFilters();
  state.lockedLayer = layer;
  state.lockedZip = zip;
  const placeLocked = getPlaceLabelFromProps(layer.feature.properties);
  drawRadarByFeature(layer.feature, { locked: true });
  document.getElementById("selectionHint").innerHTML =
    `<strong>操作提示：</strong>当前已固定 <strong>ZIP ${escapeHtml(zip)}</strong>${placeLocked ? ` <span class="hint-place">（${escapeHtml(placeLocked)}）</span>` : ""}。再次单击同一区块，或点击地图空白处，即可取消固定并恢复悬停预览。`;
  applyLockedStyle();
}

function clearLockedSelection() {
  if (!state.lockedLayer) return;
  state.lockedLayer = null;
  state.lockedZip = null;
  document.getElementById("selectionHint").innerHTML =
    "<strong>操作提示：</strong>在地图上移动鼠标可预览某一 ZIP 的雷达图；单击区块可「固定」该区域并加粗描边，再次单击同一区块或点击地图空白处即可取消。";
  applyFilters();
  document.getElementById("radarTitle").textContent = "ZIP 环境画像（悬停地图上的区域）";
  drawRadarPlaceholder();
}

function applyLockedStyle() {
  if (!state.lockedLayer) return;
  const p = state.lockedLayer.feature.properties;
  const score = Number(p.environment_score || 0);
  // 不用近黑色粗描边：与邻区共用边会双线叠加，看起来像一片脏黑边；改用浅色高亮并置顶绘制
  state.lockedLayer.setStyle({
    color: "#fef08a",
    weight: 2.5,
    opacity: 1,
    lineCap: "round",
    lineJoin: "round",
    fillColor: getScoreColor(score),
    fillOpacity: 0.92,
  });
  if (typeof state.lockedLayer.bringToFront === "function") {
    state.lockedLayer.bringToFront();
  }
}

function renderInsights() {
  const list = document.getElementById("insightList");
  if (!list) return;
  const rows = state.envRecords.map((r) => ({
    zip: String(r.zip_code),
    ...r.environment,
  }));
  if (!rows.length) {
    list.innerHTML = "<li>当前没有可展示的数据，请检查数据文件是否已正确生成并放在约定路径下。</li>";
    return;
  }

  const top = [...rows].sort((a, b) => b.environment_score - a.environment_score)[0];
  const bottom = [...rows].sort((a, b) => a.environment_score - b.environment_score)[0];
  const top3 = [...rows]
    .sort((a, b) => b.environment_score - a.environment_score)
    .slice(0, 3)
    .map((d) => `${d.zip}（${d.environment_score} 分）`)
    .join("、");
  const bottom3 = [...rows]
    .sort((a, b) => a.environment_score - b.environment_score)
    .slice(0, 3)
    .map((d) => `${d.zip}（${d.environment_score} 分）`)
    .join("、");

  const bestDim = maxMetric(top);
  const worstDim = minMetric(bottom);
  const avg = mean(rows.map((d) => d.environment_score)).toFixed(1);

  const kpiZipCount = document.getElementById("kpiZipCount");
  const kpiAvg = document.getElementById("kpiAvg");
  const kpiBest = document.getElementById("kpiBest");
  const kpiWorst = document.getElementById("kpiWorst");
  if (kpiZipCount) kpiZipCount.textContent = String(rows.length);
  if (kpiAvg) kpiAvg.textContent = avg;
  if (kpiBest) kpiBest.textContent = `${top.zip} · ${top.environment_score}`;
  if (kpiWorst) kpiWorst.textContent = `${bottom.zip} · ${bottom.environment_score}`;

  list.innerHTML = "";
  addInsight(
    `在本次载入的 ${rows.length} 个 ZIP 中，环境综合分的平均值约为 ${avg} 分——可作为你在地图上判断「整体偏绿还是偏黄/红」的参照。`
  );
  addInsight(`综合分相对更突出的区域包括：${top3}；相对更需要结合雷达图细看的区域包括：${bottom3}。`);
  addInsight(
    `ZIP ${top.zip} 在三项指标里相对最强的是「${bestDim}」；ZIP ${bottom.zip} 则更容易在「${worstDim}」上拖低整体感受——可在地图上分别点开感受差异。`
  );
  addInsight(
    "探索顺序建议：先把综合分滑块调到你能接受的底线，再逐个勾选空气、安静度、绿荫——看地图上哪些区块被「过滤」掉，就能直观看到是哪一个维度在限制你的选择。"
  );

  function addInsight(text) {
    const li = document.createElement("li");
    li.textContent = text;
    list.appendChild(li);
  }
}

function maxMetric(row) {
  const dims = [
    ["空气质量", row.air_quality_score],
    ["低噪音", row.noise_score],
    ["绿化", row.green_score],
  ];
  dims.sort((a, b) => b[1] - a[1]);
  return dims[0][0];
}

function minMetric(row) {
  const dims = [
    ["空气质量", row.air_quality_score],
    ["低噪音", row.noise_score],
    ["绿化", row.green_score],
  ];
  dims.sort((a, b) => a[1] - b[1]);
  return dims[0][0];
}

function mean(nums) {
  return nums.reduce((a, b) => a + b, 0) / nums.length;
}

function drawRadarPlaceholder() {
  drawRadar(
    {
      zip: "N/A",
      environment_score: 0,
      air_quality_score: 0,
      noise_score: 0,
      green_score: 0,
    },
    true
  );
}

function drawRadarByFeature(feature, opts) {
  const p = feature.properties;
  drawRadar(
    {
      zip: getFeatureZip(p),
      placeLabel: getPlaceLabelFromProps(p),
      locked: Boolean(opts && opts.locked),
      environment_score: +p.environment_score,
      air_quality_score: +p.air_quality_score,
      noise_score: +p.noise_score,
      green_score: +p.green_score,
    },
    false
  );
}

function drawRadar(row, isPlaceholder) {
  const svg = d3.select("#radar");
  svg.selectAll("*").remove();

  const w = 420;
  const h = 360;
  const cx = w / 2;
  const cy = h / 2;
  const radius = 118;
  const axes = ["air_quality_score", "noise_score", "green_score"];
  const labels = ["空气 Air", "安静 Noise", "绿荫 Green"];
  const angle = (Math.PI * 2) / axes.length;
  const r = d3.scaleLinear().domain([0, 100]).range([0, radius]);

  const defs = svg.append("defs");
  const grad = defs
    .append("linearGradient")
    .attr("id", "radarFillGrad")
    .attr("x1", "0%")
    .attr("y1", "0%")
    .attr("x2", "100%")
    .attr("y2", "100%");
  grad.append("stop").attr("offset", "0%").attr("stop-color", isPlaceholder ? "#94a3b8" : "#22c55e").attr("stop-opacity", 0.35);
  grad.append("stop").attr("offset", "100%").attr("stop-color", isPlaceholder ? "#64748b" : "#0284c7").attr("stop-opacity", 0.45);

  for (let i = 1; i <= 5; i++) {
    const rr = (radius * i) / 5;
    svg
      .append("circle")
      .attr("cx", cx)
      .attr("cy", cy)
      .attr("r", rr)
      .attr("fill", "none")
      .attr("stroke", "#e2e8f0")
      .attr("stroke-width", i === 5 ? 1.25 : 1);
  }

  axes.forEach((k, i) => {
    const a = -Math.PI / 2 + i * angle;
    const x = cx + Math.cos(a) * radius;
    const y = cy + Math.sin(a) * radius;
    svg
      .append("line")
      .attr("x1", cx)
      .attr("y1", cy)
      .attr("x2", x)
      .attr("y2", y)
      .attr("stroke", "#cbd5e1")
      .attr("stroke-width", 1);
    svg
      .append("text")
      .attr("x", cx + Math.cos(a) * (radius + 22))
      .attr("y", cy + Math.sin(a) * (radius + 22))
      .attr("dy", "0.35em")
      .attr("text-anchor", "middle")
      .attr("font-size", 12)
      .attr("font-weight", 600)
      .attr("fill", "#334155")
      .text(labels[i]);
  });

  const points = axes.map((k, i) => {
    const a = -Math.PI / 2 + i * angle;
    const rr = r(row[k] || 0);
    return [cx + Math.cos(a) * rr, cy + Math.sin(a) * rr];
  });

  svg
    .append("polygon")
    .attr("points", points.map((d) => d.join(",")).join(" "))
    .attr("fill", "url(#radarFillGrad)")
    .attr("stroke", isPlaceholder ? "#64748b" : "#15803d")
    .attr("stroke-width", 2)
    .attr("stroke-linejoin", "round");

  if (!isPlaceholder) {
    const place = row.placeLabel ? ` · ${row.placeLabel}` : "";
    document.getElementById("radarTitle").textContent = row.locked
      ? `ZIP 环境画像 · 已固定 ${row.zip}${place}`
      : `ZIP 环境画像 · ${row.zip}${place}`;
  } else {
    document.getElementById("radarTitle").textContent = "ZIP 环境画像（悬停地图上的区域）";
  }
  renderMetaCard(row, isPlaceholder);
}

function renderMetaCard(row, isPlaceholder) {
  const el = document.getElementById("meta");
  if (!el) return;
  if (isPlaceholder) {
    el.className = "meta-card is-placeholder";
    el.innerHTML = "将鼠标移到地图上的某一邮政编码区域，这里会显示该区的综合分与三项细分的文字摘要。";
    return;
  }
  el.className = "meta-card";
  const air = Math.round(Number(row.air_quality_score) || 0);
  const noise = Math.round(Number(row.noise_score) || 0);
  const green = Math.round(Number(row.green_score) || 0);
  const total = Math.round(Number(row.environment_score) || 0);
  const placeLine = row.placeLabel
    ? `<div class="meta-place">${escapeHtml(row.placeLabel)}</div><p class="meta-place-note">地名来自邮编边界数据中的邮局常用名与行政区，便于定位，不等同于官方邻里划分。</p>`
    : "";
  el.innerHTML = `
    <div class="meta-zip">ZIP ${escapeHtml(String(row.zip))} · 综合 ${total}</div>
    ${placeLine}
    <dl>
      <dt>空气</dt><dd>${air} / 100 — 相对呼吸环境</dd>
      <dt>安静</dt><dd>${noise} / 100 — 相对安静程度（基于相关诉求）</dd>
      <dt>绿荫</dt><dd>${green} / 100 — 相对树木覆盖</dd>
    </dl>
  `;
}

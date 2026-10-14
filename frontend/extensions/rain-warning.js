import { d as component, r as ref, Q as h, O as mounted, V as unmounted } from './index-Me4TUIQZ.js';

const API = '/rain-warning-api';
const STORAGE = 'rain_warning_jobs_v1';
let saved = [];
try { saved = JSON.parse(localStorage.getItem(STORAGE) || '[]').slice(0, 20); } catch (_) {}
const state = ref({ file: null, meta: null, error: '', checking: false, busy: false,
  job: null, result: null, history: saved, audience: 'overview' });
export const activeTool = ref(new URLSearchParams(location.hash.split('?')[1] || '').get('tool') === 'rainstorm' ? 'rainstorm' : 'segment');
let validationTicket = 0;
let pollTimer = null;
const audienceNames = { overview: '综合研判', public: '公众建议', traffic: '交通建议', water: '水利建议', emergency: '应急建议' };
const fmt = n => n == null ? '—' : Number(n).toLocaleString('zh-CN', { maximumFractionDigits: 2 });
const badge = level => ({ '低风险': 'low', '关注': 'watch', '较高风险': 'raised', '高风险': 'high' })[level] || 'low';
const el = (tag, props, children) => h(tag, props || {}, children);
const button = (text, click, props = {}) => el('button', { type: 'button', onClick: click, ...props }, text);

async function request(path, options = {}) {
  const response = await fetch(API + path, { cache: 'no-store', ...options });
  let data;
  try { data = await response.json(); } catch (_) { throw new Error('预警服务暂时不可用，请稍后重试。'); }
  if (!response.ok) throw new Error(data.error || '请求未完成，请重试。');
  return data;
}

function saveHistory(job) {
  const item = { id: job.id, filename: job.filename, basin: job.meta.basin,
    time: job.meta.end, status: job.status, created: job.created_at };
  state.value.history = [item, ...state.value.history.filter(x => x.id !== job.id)].slice(0, 20);
  localStorage.setItem(STORAGE, JSON.stringify(state.value.history));
}

function applyJob(job) {
  state.value.job = job;
  state.value.result = job.result;
  state.value.busy = !['complete', 'failed'].includes(job.status);
  state.value.meta = job.meta;
  saveHistory(job);
  state.value.error = job.status === 'failed' ? job.message : '';
}

async function poll(id) {
  clearTimeout(pollTimer);
  try {
    const job = await request('/jobs/' + id);
    if (state.value.job && state.value.job.id !== id) return;
    applyJob(job);
    if (state.value.busy) pollTimer = setTimeout(() => poll(id), 700);
  } catch (error) {
    state.value.error = error.message + ' 正在尝试重新连接。';
    pollTimer = setTimeout(() => poll(id), 2500);
  }
}

async function selectFile(file) {
  if (!file || state.value.busy) return;
  const ticket = ++validationTicket;
  state.value.file = file;
  state.value.meta = null;
  state.value.error = '';
  state.value.checking = true;
  if (!file.name.toLowerCase().endsWith('.csv') || file.size > 10 * 1024 * 1024) {
    state.value.error = '请上传不超过10 MB的.csv文件。';
    state.value.checking = false;
    return;
  }
  try {
    const data = await request('/validate', { method: 'POST', body: file,
      headers: { 'Content-Type': 'text/csv', 'X-File-Name': encodeURIComponent(file.name) } });
    if (ticket === validationTicket) state.value.meta = data.meta;
  } catch (error) {
    if (ticket === validationTicket) state.value.error = error.message;
  } finally {
    if (ticket === validationTicket) state.value.checking = false;
  }
}

async function startAnalysis() {
  if (!state.value.file || !state.value.meta || state.value.busy || state.value.checking) return;
  state.value.busy = true;
  state.value.error = '';
  state.value.result = null;
  state.value.job = null;
  state.value.audience = 'overview';
  try {
    const job = await request('/jobs', { method: 'POST', body: state.value.file,
      headers: { 'Content-Type': 'text/csv', 'X-File-Name': encodeURIComponent(state.value.file.name) } });
    applyJob(job);
    await poll(job.id);
  } catch (error) { state.value.error = error.message; state.value.busy = false; }
}

async function tryExample() {
  if (state.value.busy || state.value.checking) return;
  state.value.error = '';
  try {
    const response = await fetch('/rain-warning/example.csv', { cache: 'no-store' });
    if (!response.ok) throw new Error('示例暂时无法下载，请稍后重试。');
    await selectFile(new File([await response.blob()], '暴雨预警_示例.csv', { type: 'text/csv' }));
    if (state.value.meta && !state.value.error) await startAnalysis();
  } catch (error) { state.value.error = error.message; }
}

async function openHistory(id) {
  if (state.value.busy) return;
  activeTool.value = 'rainstorm';
  clearTimeout(pollTimer);
  state.value.error = '';
  state.value.file = null;
  state.value.job = null;
  try { const job = await request('/jobs/' + id); applyJob(job); if (state.value.busy) poll(id); }
  catch (error) { state.value.error = error.message; }
}

function downloadResult() {
  const result = state.value.result;
  if (!result || !result.advice) return;
  let text = `${result.meta.basin}暴雨风险分析\n数据截至：${result.meta.end}\n生成方式：${result.generation.label}\n\n`;
  for (const [key, label] of Object.entries(audienceNames)) text += label + '\n' + result.advice[key] + '\n\n';
  text += '不确定性说明\n' + result.advice.uncertainty;
  const url = URL.createObjectURL(new Blob(['\ufeff' + text], { type: 'text/plain;charset=utf-8' }));
  const link = document.createElement('a'); link.href = url; link.download = result.meta.basin + '_预警分析.txt'; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export const WarningUpload = component({
  name: 'RainWarningUpload',
  setup() {
    return () => {
      const s = state.value;
      return el('section', { class: 'rain-upload' }, [
        el('div', { class: 'rain-eyebrow' }, 'CSV · 自动识别流域'),
        el('h2', {}, '上传气象观测表'),
        el('p', { class: 'rain-muted' }, '上传一个河流的站点观测，自动识别并分析。'),
        el('div', { class: 'rain-example-actions' }, [
          el('a', { class: 'rain-example', href: '/rain-warning/example.csv', download: '暴雨预警_示例.csv' }, '↓ 下载示例 CSV'),
          button('使用示例试跑', tryExample, { class: 'rain-example-run', disabled: s.busy || s.checking }),
        ]),
        el('label', { class: 'rain-dropzone' + (s.busy ? ' disabled' : ''),
          onDragover: e => e.preventDefault(), onDrop: e => { e.preventDefault(); selectFile(e.dataTransfer.files[0]); } }, [
          el('input', { type: 'file', accept: '.csv', disabled: s.busy, 'aria-label': '上传暴雨预警CSV',
            onChange: e => selectFile(e.target.files[0]) }),
          el('span', { class: 'rain-upload-icon', 'aria-hidden': 'true' }, '⇧'),
          el('strong', {}, s.file ? s.file.name : '点击或拖拽上传 CSV'),
          el('span', { class: 'rain-muted' }, s.file ? fmt(s.file.size / 1024) + ' KB' : 'UTF-8 / GBK · 最大10 MB'),
        ]),
        s.checking ? el('p', { class: 'rain-checking', role: 'status' }, '正在检查格式与站点…') : null,
        s.error ? el('div', { class: 'rain-error', role: 'alert' }, s.error) : null,
        s.meta ? el('div', { class: 'rain-file-summary' }, [
          el('div', { class: 'rain-recognized' }, [el('span', {}, '已识别流域'), el('strong', {}, s.meta.basin)]),
          el('p', {}, `${s.meta.station_count}个站点 · ${fmt(s.meta.record_count)}条观测`),
          el('p', { class: 'rain-muted' }, s.meta.start + ' 至 ' + s.meta.end),
          el('small', {}, s.meta.inference),
          ...s.meta.warnings.map(x => el('p', { class: 'rain-warning-note' }, x)),
        ]) : null,
        button(s.busy ? '正在分析…' : '开始分析', startAnalysis,
          { class: 'rain-primary', disabled: !s.file || !s.meta || s.checking || s.busy }),
        s.busy && s.job ? el('div', { class: 'rain-progress', role: 'status', 'aria-live': 'polite' }, [
          el('div', { class: 'rain-progress-track' }, el('div', { style: { width: s.job.progress + '%' } })),
          el('p', {}, s.job.message),
        ]) : null,
        el('details', { class: 'rain-format' }, [el('summary', {}, '查看字段与数据要求'),
          el('p', {}, '站号 Station_Id_C；时间 datetime（或 Year/Mon/Day/Hour）；PRE_3h、PRS、VIS、WIN_S_MAX、WEP_Now。'),
          el('p', {}, '每站至少16个连续3小时时次，建议24个。可附 basin、reach、站名与温湿度等字段。'),
          el('p', {}, '一个文件对应一个流域，各站数据截至时间应一致。站号无法唯一判断时，在表中补充 basin 字段。')]),
      ]);
    };
  },
});

export const WarningResults = component({
  name: 'RainWarningResults',
  setup() {
    return () => {
      const s = state.value, result = s.result;
      if (!result) return el('section', { class: 'rain-center rain-empty' }, [
        el('span', { class: 'rain-empty-icon' }, '☂'),
        el('div', { class: 'rain-eyebrow' }, '暴雨预警'),
        el('h2', {}, s.busy ? '正在分析观测数据' : '从一份观测表开始'),
        el('p', {}, s.busy ? (s.job ? s.job.message : '正在提交分析任务…') : '在右侧上传 CSV，查看流域风险和分对象建议。'),
        el('div', { class: 'rain-empty-steps' }, '自动识别流域 → 计算风险 → 生成建议'),
      ]);
      const meta = result.meta, overall = result.overall;
      return el('section', { class: 'rain-center' }, [
        el('header', { class: 'rain-result-heading' }, [
          el('div', {}, [el('div', { class: 'rain-eyebrow' }, '观测驱动 · 流域风险分析'),
            el('h1', {}, meta.basin + '暴雨预警'), el('p', { class: 'rain-muted' }, '数据截至 ' + meta.end)]),
          result.advice ? button('导出结果', downloadResult, { class: 'rain-outline' }) : null,
        ]),
        el('div', { class: 'rain-overview' }, [
          el('div', {}, [el('span', { class: 'rain-muted' }, '当前最高风险等级'),
            el('strong', { class: 'rain-level ' + badge(overall.risk_level) }, overall.risk_level)]),
          el('div', {}, [el('span', { class: 'rain-muted' }, '最高风险指数'), el('strong', {}, fmt(overall.max_risk_index))]),
          el('div', {}, [el('span', { class: 'rain-muted' }, '观测站点'), el('strong', {}, meta.station_count + ' 个')]),
        ]),
        el('div', { class: 'rain-reach-grid' }, result.reaches.map(reach => el('article', { class: 'rain-reach-card', key: reach.reach }, [
          el('div', { class: 'rain-card-title' }, [el('h3', {}, reach.reach), el('span', { class: 'rain-pill ' + badge(reach.risk_level) }, reach.risk_level)]),
          el('strong', { class: 'rain-score' }, fmt(reach.max_risk_index)),
          el('p', { class: 'rain-muted' }, reach.station_count + '个站点 · 最大风险指数'),
          el('dl', {}, [el('dt', {}, '24h最大雨量'), el('dd', {}, fmt(reach.max_precip_24h) + ' mm'),
            el('dt', {}, '48h最大雨量'), el('dd', {}, fmt(reach.max_precip_48h) + ' mm'),
            el('dt', {}, '区域协同性'), el('dd', {}, fmt(reach.coherence_index))]),
        ]))),
        el('div', { class: 'rain-section-heading' }, [el('h2', {}, '重点站点'), el('span', { class: 'rain-muted' }, '按风险指数排序')]),
        el('div', { class: 'rain-table-wrap' }, el('table', { class: 'rain-table' }, [
          el('thead', {}, el('tr', {}, ['站点 / 河段', '风险', '24h雨量', '触发原因'].map(x => el('th', {}, x)))),
          el('tbody', {}, result.key_stations.map(station => el('tr', { key: station.station_id }, [
            el('td', {}, [el('strong', {}, station.station_name), el('small', {}, station.reach)]),
            el('td', {}, [el('span', { class: 'rain-pill ' + badge(station.risk_level) }, station.risk_level), el('small', {}, fmt(station.risk_index))]),
            el('td', {}, fmt(station.precip_24h) + ' mm'), el('td', {}, station.trigger_reasons.join('、')),
          ]))),
        ])),
        el('div', { class: 'rain-section-heading' }, [el('h2', {}, '预警建议'),
          el('span', { class: 'rain-method-label' }, result.generation ? result.generation.label : '正在生成建议…')]),
        result.advice ? el('div', { class: 'rain-advice' }, [
          el('nav', { class: 'rain-audience-tabs', 'aria-label': '预警建议类型' }, Object.entries(audienceNames).map(([key, label]) =>
            button(label, () => { state.value.audience = key; }, { class: s.audience === key ? 'active' : '', 'aria-pressed': s.audience === key }))),
          el('div', { class: 'rain-advice-body', 'aria-live': 'polite' }, result.advice[s.audience]),
          el('details', { class: 'rain-uncertainty' }, [el('summary', {}, '适用范围与不确定性'), el('p', {}, result.advice.uncertainty)]),
        ]) : el('p', { class: 'rain-muted' }, '风险计算已完成，正在生成分对象建议。'),
        el('footer', { class: 'rain-result-footer' }, `${meta.start} — ${meta.end} · ${fmt(meta.record_count)}条观测 · ${result.method.score_version}`),
      ]);
    };
  },
});

export const WarningHistory = component({
  name: 'RainWarningHistory',
  setup() {
    mounted(() => {
      const recent = state.value.history[0];
      if (recent && !state.value.job && (activeTool.value === 'rainstorm' || !['complete', 'failed'].includes(recent.status))) openHistory(recent.id);
    });
    return () => state.value.history.length ? el('section', { class: 'rain-history' }, [
      el('h3', {}, '暴雨预警记录'),
      ...state.value.history.map(job => el('button', {
        type: 'button', onClick: () => openHistory(job.id),
        class: 'rain-history-item' + (state.value.job && state.value.job.id === job.id ? ' selected' : ''),
        disabled: state.value.busy, title: job.filename,
      }, [el('span', {}, job.basin + ' · ' + (job.status === 'complete' ? '已完成' : job.status === 'failed' ? '未完成' : '分析中')),
        el('strong', {}, job.filename), el('small', {}, job.time)])),
    ]) : null;
  },
});

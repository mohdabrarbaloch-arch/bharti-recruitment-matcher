/* ==========================================================================
   Bharti frontend. No framework, no build step — one file, plain DOM.
   State lives in `state`; every render is a pure function of it.
   ========================================================================== */

'use strict';

const API = '/api';

const state = {
  token: localStorage.getItem('bharti_token') || null,
  user: null,
  jobs: [],
  activeJobId: null,
  ranked: [],
  minScore: 0,
  editingJobId: null,
};

/* ── tiny helpers ─────────────────────────────────────────────────────── */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = value;
    else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

let toastTimer = null;
function toast(message, isError = false) {
  const node = $('#toast');
  node.textContent = message;
  node.classList.toggle('is-error', isError);
  node.classList.add('is-visible');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.classList.remove('is-visible'), 3200);
}

/* ── api ──────────────────────────────────────────────────────────────── */

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.body && !(options.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json';
  }
  if (state.token) headers.Authorization = `Bearer ${state.token}`;

  const response = await fetch(API + path, { ...options, headers });

  if (response.status === 401 && state.token) {
    signOut();
    throw new Error('Session expired — please sign in again.');
  }

  if (response.status === 204) return null;

  let payload = null;
  const text = await response.text();
  if (text) {
    try { payload = JSON.parse(text); } catch { payload = { detail: text }; }
  }

  if (!response.ok) {
    let detail = payload?.detail;
    if (Array.isArray(detail)) {
      // FastAPI validation errors: turn them into one readable line.
      detail = detail.map((d) => `${(d.loc || []).slice(1).join('.')}: ${d.msg}`).join('; ');
    }
    throw new Error(detail || `Request failed (${response.status})`);
  }
  return payload;
}

/* ── auth ─────────────────────────────────────────────────────────────── */

function showAuthError(message) {
  const node = $('#auth-error');
  node.textContent = message;
  node.hidden = !message;
}

async function signIn(email, password) {
  const data = await api('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  });
  state.token = data.access_token;
  state.user = data.user;
  localStorage.setItem('bharti_token', state.token);
  await enterApp();
}

async function signUp(fullName, email, password) {
  const data = await api('/auth/register', {
    method: 'POST',
    body: JSON.stringify({ full_name: fullName, email, password }),
  });
  state.token = data.access_token;
  state.user = data.user;
  localStorage.setItem('bharti_token', state.token);
  await enterApp();
}

function signOut() {
  state.token = null;
  state.user = null;
  state.jobs = [];
  state.ranked = [];
  state.activeJobId = null;
  localStorage.removeItem('bharti_token');
  $('#app').classList.add('is-hidden');
  $('#auth-screen').classList.remove('is-hidden');
  closeAllModals();
}

async function enterApp() {
  $('#auth-screen').classList.add('is-hidden');
  $('#app').classList.remove('is-hidden');
  $('#user-chip').textContent = state.user ? state.user.full_name : '';
  await loadJobs();
}

/* ── jobs ─────────────────────────────────────────────────────────────── */

async function loadJobs() {
  state.jobs = await api('/jobs');
  renderJobList();

  if (state.jobs.length === 0) {
    state.activeJobId = null;
    renderPanel();
    return;
  }
  const stillExists = state.jobs.some((j) => j.id === state.activeJobId);
  if (!stillExists) state.activeJobId = state.jobs[0].id;
  await loadRanked();
}

function renderJobList() {
  const list = $('#job-list');
  list.innerHTML = '';
  $('#job-list-empty').classList.toggle('is-hidden', state.jobs.length > 0);

  for (const job of state.jobs) {
    const meta = [];
    if (job.company) meta.push(job.company);
    meta.push(job.remote_ok ? 'Remote' : (job.location || 'No location'));
    meta.push(`${job.candidate_count} candidate${job.candidate_count === 1 ? '' : 's'}`);

    list.append(
      el('button', {
        class: 'job-item' + (job.id === state.activeJobId ? ' is-active' : ''),
        onclick: () => selectJob(job.id),
      },
        el('span', { class: 'job-item-title', text: job.title }),
        el('span', { class: 'job-item-meta' }, ...meta.map((m) => el('span', { text: m }))),
      )
    );
  }
}

async function selectJob(jobId) {
  state.activeJobId = jobId;
  renderJobList();
  await loadRanked();
}

async function loadRanked() {
  if (!state.activeJobId) { renderPanel(); return; }
  try {
    state.ranked = await api(`/jobs/${state.activeJobId}/ranked`);
  } catch (error) {
    toast(error.message, true);
    state.ranked = [];
  }
  renderPanel();
}

/* ── panel ────────────────────────────────────────────────────────────── */

function activeJob() {
  return state.jobs.find((j) => j.id === state.activeJobId) || null;
}

function scoreClass(score) {
  if (score >= 70) return 's-good';
  if (score >= 45) return 's-mid';
  return 's-bad';
}

function barClass(score) {
  if (score >= 0.75) return 'b-good';
  if (score >= 0.45) return 'b-mid';
  return 'b-bad';
}

function renderPanel() {
  const job = activeJob();
  const empty = $('#panel-empty');
  const content = $('#panel-content');

  if (!job) {
    empty.classList.remove('is-hidden');
    content.classList.add('is-hidden');
    return;
  }
  empty.classList.add('is-hidden');
  content.classList.remove('is-hidden');

  $('#job-title').textContent = job.title;

  const metaBits = [];
  if (job.company) metaBits.push(job.company);
  metaBits.push(job.remote_ok ? 'Remote' : (job.location || 'Location not set'));
  metaBits.push(`${job.seniority} level`);
  metaBits.push(`${job.min_years}+ years`);
  if (!job.is_open) metaBits.push('CLOSED');
  $('#job-meta').textContent = metaBits.join(' · ');

  // requirements strip
  const strip = $('#job-requirements');
  strip.innerHTML = '';
  for (const skill of job.required_skills) {
    strip.append(el('span', { class: 'chip chip-req', text: skill.replace(/_/g, ' ') }));
  }
  for (const skill of job.nice_skills) {
    strip.append(el('span', { class: 'chip chip-nice', text: '+ ' + skill.replace(/_/g, ' ') }));
  }
  if (job.required_education) {
    strip.append(el('span', { class: 'chip', text: '🎓 ' + job.required_education }));
  }
  if (!job.required_skills.length && !job.nice_skills.length) {
    strip.append(el('span', { class: 'chip chip-warn', text: 'No skills set — scores will be driven by experience only' }));
  }

  renderStats();
  renderCandidates();
}

function renderStats() {
  const row = $('#stats-row');
  row.innerHTML = '';
  const ranked = state.ranked;

  const scores = ranked.map((r) => r.match.total);
  const avg = scores.length ? scores.reduce((a, b) => a + b, 0) / scores.length : 0;
  const strong = scores.filter((s) => s >= 70).length;
  const shortlisted = ranked.filter((r) => r.candidate.status === 'shortlisted').length;
  const lowConf = ranked.filter((r) => r.match.confidence === 'low').length;

  const stats = [
    { label: 'Candidates', value: ranked.length },
    { label: 'Average score', value: avg.toFixed(1) },
    { label: 'Strong (70+)', value: strong },
    { label: 'Shortlisted', value: shortlisted },
  ];
  if (lowConf) stats.push({ label: 'Low confidence', value: lowConf });

  for (const stat of stats) {
    row.append(
      el('div', { class: 'stat' },
        el('div', { class: 'stat-label', text: stat.label }),
        el('div', { class: 'stat-value', text: stat.value }),
      )
    );
  }
}

function renderCandidates() {
  const list = $('#candidate-list');
  list.innerHTML = '';

  const visible = state.ranked.filter((r) => r.match.total >= state.minScore);
  $('#candidate-empty').classList.toggle('is-hidden', state.ranked.length > 0);

  if (state.ranked.length > 0 && visible.length === 0) {
    list.append(el('p', { class: 'empty-note', text: `No candidates score ${state.minScore} or above. Lower the filter to see the rest.` }));
    return;
  }

  for (const row of visible) {
    const { candidate, match } = row;

    const tags = [];
    for (const hit of match.required_skills) {
      if (hit.kind === 'exact') tags.push(el('span', { class: 'chip chip-good', text: hit.label }));
      else if (hit.kind === 'related') tags.push(el('span', { class: 'chip chip-warn', text: `${hit.label} ~${hit.matched_via}` }));
      else tags.push(el('span', { class: 'chip chip-bad', text: `✕ ${hit.label}` }));
    }

    const subBits = [];
    if (candidate.email) subBits.push(candidate.email);
    subBits.push(`${candidate.years_experience.toFixed(1)} yrs`);
    subBits.push(candidate.seniority);
    if (candidate.location) subBits.push(candidate.location);

    list.append(
      el('div', { class: 'cand', onclick: () => openDetail(row) },
        el('div', { class: `cand-score ${scoreClass(match.total)}`, text: Math.round(match.total) }),
        el('div', { class: 'cand-main' },
          el('div', { class: 'cand-name' }, candidate.full_name),
          el('div', { class: 'cand-sub', text: subBits.join(' · ') }),
          el('div', { class: 'cand-verdict', text: match.verdict }),
          el('div', { class: 'cand-tags' }, ...tags),
        ),
        el('div', { class: 'cand-side' },
          el('span', { class: `status-pill status-${candidate.status}`, text: candidate.status }),
          el('span', {
            class: 'conf-badge' + (match.confidence === 'low' ? ' low' : ''),
            text: `${match.confidence} confidence`,
          }),
        ),
      )
    );
  }
}

/* ── detail modal ─────────────────────────────────────────────────────── */

function openDetail(row) {
  const { candidate, match } = row;

  $('#detail-name').textContent = candidate.full_name;
  const body = $('#detail-body');
  body.innerHTML = '';

  // headline
  const subBits = [];
  if (candidate.email) subBits.push(candidate.email);
  if (candidate.phone) subBits.push(candidate.phone);
  if (candidate.location) subBits.push(candidate.location);

  body.append(
    el('div', { class: 'detail-top' },
      el('div', { class: `detail-score ${scoreClass(match.total)}`, text: Math.round(match.total) }),
      el('div', { class: 'detail-headline' },
        el('h3', { text: candidate.full_name }),
        el('p', { text: subBits.join(' · ') || 'No contact details found' }),
        el('p', { class: 'detail-verdict', text: match.verdict }),
      ),
    )
  );

  // the arithmetic
  body.append(el('div', { class: 'section-label', text: 'How the score was built' }));
  const breakdown = el('div', { class: 'breakdown' });

  for (const component of match.components) {
    const pct = Math.round(component.score * 100);
    const dropped = !component.applied;

    breakdown.append(
      el('div', { class: 'bd-row' + (dropped ? ' is-dropped' : '') },
        el('div', { class: 'bd-name', text: component.name }),
        el('div', { class: 'bd-bar-wrap' },
          el('div', {
            class: 'bd-bar ' + (dropped ? 'b-off' : barClass(component.score)),
            style: `width:${dropped ? 0 : pct}%`,
          }),
        ),
        el('div', { class: 'bd-pts', text: dropped ? '—' : `+${component.contribution.toFixed(1)}` }),
        el('div', { class: 'bd-reason', text: component.reason }),
      )
    );
  }
  body.append(breakdown);

  // required skills
  if (match.required_skills.length) {
    body.append(el('div', { class: 'section-label', text: 'Required skills' }));
    const grid = el('div', { class: 'skill-grid' });
    for (const hit of match.required_skills) {
      if (hit.kind === 'exact') grid.append(el('span', { class: 'chip chip-good', text: `✓ ${hit.label}` }));
      else if (hit.kind === 'related') grid.append(el('span', { class: 'chip chip-warn', text: `${hit.label} — via ${hit.matched_via} (${Math.round(hit.credit * 100)}%)` }));
      else grid.append(el('span', { class: 'chip chip-bad', text: `✕ ${hit.label}` }));
    }
    body.append(grid);
  }

  // gaps
  if (match.gaps.length || match.partial.length) {
    body.append(el('div', { class: 'section-label', text: 'What to ask about' }));
    const gapList = el('div', { class: 'gap-list' });
    for (const gap of match.gaps) {
      gapList.append(el('div', { class: 'gap-item' }, el('span', { text: `Missing: ${gap.replace(/_/g, ' ')}` })));
    }
    for (const partial of match.partial) {
      const hit = match.required_skills.find((h) => h.skill === partial);
      gapList.append(
        el('div', { class: 'gap-item partial' },
          el('span', { text: `Partial: ${partial.replace(/_/g, ' ')}` }),
          el('span', { class: 'via', text: hit ? `— has ${hit.matched_via}` : '' }),
        )
      );
    }
    body.append(gapList);
  }

  // strengths
  if (match.strengths.length) {
    body.append(el('div', { class: 'section-label', text: 'Strengths' }));
    const grid = el('div', { class: 'skill-grid' });
    for (const strength of match.strengths) {
      grid.append(el('span', { class: 'chip chip-good', text: strength }));
    }
    body.append(grid);
  }

  // parse warnings — shown, not hidden
  if (candidate.parse_warnings.length) {
    body.append(el('div', { class: 'section-label', text: 'Parser notes' }));
    const gapList = el('div', { class: 'gap-list' });
    for (const warning of candidate.parse_warnings) {
      gapList.append(el('div', { class: 'gap-item partial' }, el('span', { text: warning })));
    }
    body.append(gapList);
  }

  // actions
  const actions = el('div', { class: 'detail-actions' });
  for (const status of ['shortlisted', 'rejected', 'hired', 'new']) {
    if (status === candidate.status) continue;
    actions.append(
      el('button', {
        class: 'btn btn-ghost btn-sm',
        text: `Mark ${status}`,
        onclick: () => setStatus(candidate.id, status),
      })
    );
  }
  body.append(actions);

  openModal('detail-modal');
}

async function setStatus(candidateId, status) {
  try {
    await api(`/jobs/${state.activeJobId}/candidates/${candidateId}`, {
      method: 'PATCH',
      body: JSON.stringify({ status }),
    });
    toast(`Marked ${status}`);
    closeAllModals();
    await loadJobs();
  } catch (error) {
    toast(error.message, true);
  }
}

/* ── modals ───────────────────────────────────────────────────────────── */

function openModal(id) {
  $('#modal-backdrop').classList.remove('is-hidden');
  $('#' + id).classList.remove('is-hidden');
  document.body.style.overflow = 'hidden';
}

function closeAllModals() {
  $('#modal-backdrop').classList.add('is-hidden');
  for (const modal of $$('.modal')) modal.classList.add('is-hidden');
  document.body.style.overflow = '';
}

/* ── job form ─────────────────────────────────────────────────────────── */

function openJobModal(job = null) {
  state.editingJobId = job ? job.id : null;
  $('#job-modal-title').textContent = job ? 'Edit role' : 'New role';
  $('#job-form-error').hidden = true;

  const form = $('#job-form');
  form.reset();

  if (job) {
    form.title.value = job.title;
    form.company.value = job.company || '';
    form.location.value = job.location || '';
    form.min_years.value = job.min_years;
    form.seniority.value = job.seniority;
    form.required_education.value = job.required_education || '';
    form.required_skills.value = (job.required_skills || []).join(', ');
    form.nice_skills.value = (job.nice_skills || []).join(', ');
    form.description.value = job.description || '';
    form.remote_ok.checked = job.remote_ok;
  }
  openModal('job-modal');
}

async function submitJob(event) {
  event.preventDefault();
  const form = event.target;
  const errorNode = $('#job-form-error');
  errorNode.hidden = true;

  const splitSkills = (value) =>
    value.split(',').map((s) => s.trim()).filter(Boolean);

  const payload = {
    title: form.title.value.trim(),
    company: form.company.value.trim(),
    location: form.location.value.trim() || null,
    remote_ok: form.remote_ok.checked,
    description: form.description.value.trim(),
    required_skills: splitSkills(form.required_skills.value),
    nice_skills: splitSkills(form.nice_skills.value),
    min_years: parseFloat(form.min_years.value) || 0,
    seniority: form.seniority.value,
    required_education: form.required_education.value.trim() || null,
  };

  try {
    if (state.editingJobId) {
      await api(`/jobs/${state.editingJobId}`, { method: 'PATCH', body: JSON.stringify(payload) });
      toast('Role updated — scores recomputed');
    } else {
      const created = await api('/jobs', { method: 'POST', body: JSON.stringify(payload) });
      state.activeJobId = created.id;
      toast('Role created');
    }
    closeAllModals();
    await loadJobs();
  } catch (error) {
    errorNode.textContent = error.message;
    errorNode.hidden = false;
  }
}

/* ── candidate form ───────────────────────────────────────────────────── */

function openCandidateModal() {
  $('#candidate-form-error').hidden = true;
  $('#candidate-form').reset();
  openModal('candidate-modal');
}

async function submitCandidate(event) {
  event.preventDefault();
  const form = event.target;
  const errorNode = $('#candidate-form-error');
  errorNode.hidden = true;

  const payload = {
    full_name: form.full_name.value.trim() || null,
    email: form.email.value.trim() || null,
    resume_text: form.resume_text.value,
  };

  const submitBtn = form.querySelector('button[type="submit"]');
  submitBtn.disabled = true;
  submitBtn.textContent = 'Parsing…';

  try {
    const created = await api(`/jobs/${state.activeJobId}/candidates`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    closeAllModals();
    toast(`${created.full_name} added — ${created.skills.length} skills found`);
    await loadJobs();
  } catch (error) {
    errorNode.textContent = error.message;
    errorNode.hidden = false;
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = 'Parse & score';
  }
}

/* ── wiring ───────────────────────────────────────────────────────────── */

function wireEvents() {
  // auth tabs
  for (const tab of $$('.auth-tab')) {
    tab.addEventListener('click', () => {
      for (const other of $$('.auth-tab')) other.classList.remove('is-active');
      tab.classList.add('is-active');
      const isLogin = tab.dataset.tab === 'login';
      $('#login-form').classList.toggle('is-hidden', !isLogin);
      $('#register-form').classList.toggle('is-hidden', isLogin);
      showAuthError('');
    });
  }

  $('#login-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    showAuthError('');
    const form = event.target;
    try {
      await signIn(form.email.value.trim(), form.password.value);
    } catch (error) {
      showAuthError(error.message);
    }
  });

  $('#register-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    showAuthError('');
    const form = event.target;
    try {
      await signUp(form.full_name.value.trim(), form.email.value.trim(), form.password.value);
    } catch (error) {
      showAuthError(error.message);
    }
  });

  $('#logout-btn').addEventListener('click', signOut);
  $('#new-job-btn').addEventListener('click', () => openJobModal());
  $('#edit-job-btn').addEventListener('click', () => {
    const job = activeJob();
    if (job) openJobModal(job);
  });
  $('#add-candidate-btn').addEventListener('click', openCandidateModal);

  $('#job-form').addEventListener('submit', submitJob);
  $('#candidate-form').addEventListener('submit', submitCandidate);

  $('#min-score').addEventListener('input', (event) => {
    state.minScore = Number(event.target.value);
    $('#min-score-out').textContent = state.minScore;
    renderCandidates();
  });

  $('#modal-backdrop').addEventListener('click', closeAllModals);
  for (const button of $$('[data-close]')) {
    button.addEventListener('click', closeAllModals);
  }
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeAllModals();
  });
}

/* ── boot ─────────────────────────────────────────────────────────────── */

async function boot() {
  wireEvents();

  if (!state.token) return;

  try {
    state.user = await api('/auth/me');
    await enterApp();
  } catch {
    signOut();
  }
}

boot();

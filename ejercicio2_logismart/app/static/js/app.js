/* LogiSmart — helpers compartidos del frontend */

async function api(ruta, opciones = {}) {
  if (opciones.body && typeof opciones.body !== 'string') {
    opciones.body = JSON.stringify(opciones.body);
    opciones.headers = { 'Content-Type': 'application/json', ...(opciones.headers || {}) };
  }
  const r = await fetch(ruta, opciones);
  const ct = r.headers.get('content-type') || '';
  const data = ct.includes('json') ? await r.json() : await r.text();
  if (!r.ok) {
    const msg = (data && data.error) ? data.error : `Error ${r.status}`;
    const err = new Error(msg);
    err.detalle = data && data.detalle;
    throw err;
  }
  return data;
}

function toast(mensaje, tipo = 'success', ms = 3500) {
  let cont = document.getElementById('toasts');
  if (!cont) {
    cont = document.createElement('div');
    cont.id = 'toasts';
    cont.className = 'toast-container position-fixed bottom-0 end-0 p-3';
    document.body.appendChild(cont);
  }
  const el = document.createElement('div');
  el.className = `toast align-items-center text-bg-${tipo} border-0`;
  el.innerHTML = `<div class="d-flex"><div class="toast-body">${mensaje}</div>
    <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button></div>`;
  cont.appendChild(el);
  const t = new bootstrap.Toast(el, { delay: ms });
  t.show();
  el.addEventListener('hidden.bs.toast', () => el.remove());
}

function fmtFecha(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return isNaN(d) ? String(iso).slice(0, 16) : d.toLocaleString('es-MX', { dateStyle: 'short', timeStyle: 'short' });
}

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function badgePrioridad(p) {
  const map = { critica: 'badge-coral', alta: 'badge-yellow', media: 'badge-sky', baja: 'badge-mint' };
  return `<span class="badge ${map[p] || ''}">${esc(p)}</span>`;
}

function badgeEstado(e) {
  const map = { nuevo: 'badge-sky', en_atencion: 'badge-yellow', cerrado: 'badge-mint' };
  return `<span class="badge ${map[e] || ''}">${esc(e || '—')}</span>`;
}

function badgeDecision(d) {
  const map = { acceso_estandar: 'badge-mint', inspeccion_especial: 'badge-yellow', retenido_horario: '', denegado: 'badge-coral' };
  const txt = { acceso_estandar: 'Acceso estándar', inspeccion_especial: 'Inspección especial', retenido_horario: 'Retenido (horario)', denegado: 'Denegado' };
  return `<span class="badge ${map[d] || ''}">${txt[d] || esc(d)}</span>`;
}

function badgeNivel(n) {
  const map = { critico: 'badge-coral', alto: 'badge-yellow', medio: 'badge-sky', bajo: 'badge-mint' };
  return `<span class="badge ${map[n] || ''}">${esc(n || '—')}</span>`;
}

/* Estado de conexiones en la barra superior */
async function pintarEstadoGlobal() {
  try {
    const d = await api('/api/estado');
    const db = document.getElementById('estadoDb');
    const lm = document.getElementById('estadoLlm');
    if (db) {
      db.className = 'estado-badge ' + (d.persistencia.conectado ? 'success' : 'danger');
      db.title = d.persistencia.conectado ? d.persistencia.uri : (d.persistencia.error || 'modo local');
      db.innerHTML = `<i class="bi bi-database"></i> ${d.persistencia.motor}`;
    }
    if (lm) {
      lm.className = 'estado-badge ' + (d.ollama.disponible ? 'success' : 'danger');
      lm.title = d.ollama.disponible ? 'Modelo: ' + d.ollama.modelo_actual : 'Ollama no responde';
      lm.innerHTML = `<i class="bi bi-cpu"></i> ${d.ollama.disponible ? d.ollama.modelo_actual : 'LLM off'}`;
    }
  } catch (e) { /* silencioso */ }
}

function spinnerBtn(btn, on, txt = 'Procesando…') {
  if (on) {
    btn.dataset.orig = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = `<span class="spinner-border spinner-border-sm me-1"></span>${txt}`;
  } else {
    btn.disabled = false;
    if (btn.dataset.orig) btn.innerHTML = btn.dataset.orig;
  }
}

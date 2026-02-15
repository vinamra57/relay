// Aria Health - Hospital Dashboard
let ws = null;
let cases = {};
let selectedCaseId = null;

// --- WebSocket Connection ---

function connectWS() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(`${proto}//${location.host}/api/hospital/ws/hospital`);

    ws.onopen = () => {
        const el = document.getElementById("wsStatus");
        el.textContent = "Live";
        el.className = "ws-status connected";
        el.innerHTML = '<span class="live-dot"></span> Live';
    };

    ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        handleEvent(msg);
    };

    ws.onclose = () => {
        const el = document.getElementById("wsStatus");
        el.textContent = "Disconnected";
        el.className = "ws-status disconnected";
        // Reconnect after 3 seconds
        setTimeout(connectWS, 3000);
    };

    ws.onerror = () => {
        const el = document.getElementById("wsStatus");
        el.textContent = "Error";
        el.className = "ws-status disconnected";
    };
}

function handleEvent(msg) {
    const caseId = msg.case_id;
    if (!caseId) return;

    // Update or create case in our local store
    if (!cases[caseId]) {
        cases[caseId] = { id: caseId, nemsis: {}, patient_name: null };
    }

    if (msg.type === "nemsis_update") {
        cases[caseId].nemsis = msg.nemsis || {};
        cases[caseId].patient_name = msg.patient_name || cases[caseId].patient_name;
    } else if (msg.type === "medical_db_result") {
        cases[caseId].medical_db_response = msg.result;
    } else if (msg.type === "gp_call_transcript") {
        cases[caseId].gp_response = msg.transcript;
        cases[caseId].gp_call_status = msg.call_status;
    }

    renderCaseList();
    if (selectedCaseId === caseId) {
        renderCaseDetail(caseId);
    }
}

// --- Data Loading ---

async function refreshCases() {
    try {
        const resp = await fetch("/api/hospital/active-cases");
        const data = await resp.json();
        cases = {};
        for (const c of data) {
            cases[c.id] = c;
        }
        renderCaseList();
        if (selectedCaseId && cases[selectedCaseId]) {
            renderCaseDetail(selectedCaseId);
        }
    } catch (e) {
        console.error("Failed to load cases:", e);
    }
}

// --- Rendering ---

function renderCaseList() {
    const body = document.getElementById("caseListBody");
    const ids = Object.keys(cases);
    document.getElementById("caseCount").textContent = ids.length;

    if (ids.length === 0) {
        body.innerHTML = '<div class="no-cases">No active cases</div>';
        return;
    }

    body.innerHTML = ids.map((id) => {
        const c = cases[id];
        const nemsis = c.nemsis || {};
        const patient = nemsis.patient || {};
        const situation = nemsis.situation || {};
        const name = c.patient_name ||
            [patient.patient_name_first, patient.patient_name_last].filter(Boolean).join(" ") ||
            "Unknown Patient";
        const age = patient.patient_age || "?";
        const gender = patient.patient_gender || "?";
        const complaint = situation.chief_complaint || "No complaint recorded";
        const impression = situation.primary_impression || "";
        const priority = getPriority(nemsis);
        const selected = id === selectedCaseId ? " selected" : "";

        return `<div class="case-card${selected}" onclick="selectCase('${id}')">
            <div class="card-header">
                <span class="card-name">${esc(name)}</span>
                <span class="priority-badge priority-${priority}">${priority}</span>
            </div>
            <div class="card-info">${esc(age)}y ${esc(gender)} - ${esc(complaint)}</div>
            <div class="card-id">${id.slice(0, 8)}...</div>
        </div>`;
    }).join("");
}

function selectCase(caseId) {
    selectedCaseId = caseId;
    renderCaseList();
    renderCaseDetail(caseId);
}

function renderCaseDetail(caseId) {
    const c = cases[caseId];
    if (!c) return;

    const area = document.getElementById("detailArea");
    const nemsis = c.nemsis || {};
    const patient = nemsis.patient || {};
    const vitals = nemsis.vitals || {};
    const situation = nemsis.situation || {};
    const procedures = nemsis.procedures || {};
    const medications = nemsis.medications || {};
    const history = nemsis.history || {};
    const disposition = nemsis.disposition || {};

    const name = c.patient_name ||
        [patient.patient_name_first, patient.patient_name_last].filter(Boolean).join(" ") ||
        "Unknown";

    area.className = "detail-area";
    area.innerHTML = `
        <div class="detail-panel">
            <div class="panel-header">Patient Info</div>
            <div class="panel-body">
                ${infoRow("Name", name)}
                ${infoRow("Age", patient.patient_age)}
                ${infoRow("Gender", patient.patient_gender)}
                ${infoRow("Address", [patient.patient_address, patient.patient_city, patient.patient_state].filter(Boolean).join(", "))}
                ${infoRow("Chief Complaint", situation.chief_complaint)}
                ${infoRow("Primary Impression", situation.primary_impression)}
                ${infoRow("Secondary Impression", situation.secondary_impression)}
                ${infoRow("Duration", situation.complaint_duration)}
                ${history.medical_history && history.medical_history.length > 0 ?
                    `<div style="margin-top:8px; font-size:12px; color:#5a6578;">MEDICAL HISTORY</div>
                     <div class="tag-list">${history.medical_history.map(h => `<span class="tag">${esc(h)}</span>`).join("")}</div>` : ""}
                ${history.allergies && history.allergies.length > 0 ?
                    `<div style="margin-top:8px; font-size:12px; color:#5a6578;">ALLERGIES</div>
                     <div class="tag-list">${history.allergies.map(a => `<span class="tag allergy">${esc(a)}</span>`).join("")}</div>` : ""}
            </div>
        </div>
        <div class="detail-panel">
            <div class="panel-header">Vitals</div>
            <div class="panel-body">
                <div class="vitals-grid">
                    ${vitalItem("BP", vitals.systolic_bp && vitals.diastolic_bp ? `${vitals.systolic_bp}/${vitals.diastolic_bp}` : null, isAbnormalBP(vitals))}
                    ${vitalItem("HR", vitals.heart_rate, vitals.heart_rate > 100 || vitals.heart_rate < 60)}
                    ${vitalItem("RR", vitals.respiratory_rate, vitals.respiratory_rate > 20 || vitals.respiratory_rate < 12)}
                    ${vitalItem("SpO2", vitals.spo2 != null ? vitals.spo2 + "%" : null, vitals.spo2 < 95)}
                    ${vitalItem("GCS", vitals.gcs_total, vitals.gcs_total < 15)}
                    ${vitalItem("Glucose", vitals.blood_glucose, false)}
                    ${vitalItem("Temp", vitals.temperature ? vitals.temperature + "F" : null, vitals.temperature > 100.4)}
                    ${vitalItem("Pain", vitals.pain_scale != null ? vitals.pain_scale + "/10" : null, vitals.pain_scale >= 7)}
                    ${vitalItem("LOC", vitals.level_of_consciousness, false)}
                </div>
            </div>
        </div>
        <div class="detail-panel">
            <div class="panel-header">Procedures & Medications</div>
            <div class="panel-body">
                <div style="margin-bottom:12px;">
                    <div style="font-size:12px; color:#c0392b; text-transform:uppercase; margin-bottom:6px;">Procedures</div>
                    ${(procedures.procedures || []).length > 0 ?
                        `<ul class="list-items">${procedures.procedures.map(p => `<li>${esc(p)}</li>`).join("")}</ul>` :
                        '<div style="color:#3a4052;">None recorded</div>'}
                </div>
                <div>
                    <div style="font-size:12px; color:#c0392b; text-transform:uppercase; margin-bottom:6px;">Medications</div>
                    ${(medications.medications || []).length > 0 ?
                        `<ul class="list-items">${medications.medications.map(m => `<li>${esc(m)}</li>`).join("")}</ul>` :
                        '<div style="color:#3a4052;">None administered</div>'}
                </div>
                ${disposition.destination_facility ? `
                <div style="margin-top:12px;">
                    <div style="font-size:12px; color:#f39c12; text-transform:uppercase; margin-bottom:6px;">Transport</div>
                    ${infoRow("Destination", disposition.destination_facility)}
                    ${infoRow("Mode", disposition.transport_mode)}
                </div>` : ""}
            </div>
        </div>
        <div class="detail-panel">
            <div class="panel-header">Downstream & Summary</div>
            <div class="panel-body">
                ${c.gp_response ? `
                <div class="downstream-section">
                    <h4>GP Response</h4>
                    ${esc(c.gp_response)}
                </div>` : '<div style="color:#3a4052; margin-bottom:8px;">GP response pending...</div>'}
                ${c.medical_db_response ? `
                <div class="downstream-section">
                    <h4>Medical Database</h4>
                    ${esc(c.medical_db_response)}
                </div>` : '<div style="color:#3a4052;">Medical records pending...</div>'}
                <div style="margin-top:12px;">
                    <button class="btn btn-secondary" style="width:100%;" onclick="loadSummary('${caseId}')">
                        Load Hospital Summary
                    </button>
                    <div id="summaryContent" style="margin-top:8px;"></div>
                </div>
            </div>
        </div>
    `;
}

async function loadSummary(caseId) {
    const el = document.getElementById("summaryContent");
    el.innerHTML = '<div style="color:#5a6578;">Loading summary...</div>';
    try {
        const resp = await fetch(`/api/hospital/summary/${caseId}`);
        if (!resp.ok) {
            el.innerHTML = '<div style="color:#c0392b;">Failed to load summary</div>';
            return;
        }
        const s = resp.json ? await resp.json() : {};
        el.innerHTML = `
            <div class="downstream-section">
                <h4>Hospital Preparation Summary</h4>
                <div>${infoRow("Priority", s.priority_level)}</div>
                <div>${infoRow("Demographics", s.patient_demographics)}</div>
                <div>${infoRow("Chief Complaint", s.chief_complaint)}</div>
                <div>${infoRow("Vitals", s.vitals_summary)}</div>
                <div>${infoRow("Impression", s.clinical_impression)}</div>
                <div>${infoRow("Procedures", s.procedures_performed)}</div>
                <div>${infoRow("Medications", s.medications_administered)}</div>
                <div>${infoRow("Preparations", s.recommended_preparations)}</div>
                <div>${infoRow("History", s.patient_history)}</div>
                <div>${infoRow("Special", s.special_considerations)}</div>
            </div>
        `;
    } catch (e) {
        el.innerHTML = '<div style="color:#c0392b;">Error loading summary</div>';
    }
}

// --- Helpers ---

function getPriority(nemsis) {
    const situation = nemsis.situation || {};
    const vitals = nemsis.vitals || {};
    const impression = (situation.primary_impression || "").toLowerCase();
    if (["stemi", "stroke", "cardiac arrest", "trauma"].some(k => impression.includes(k))) return "critical";
    if (vitals.spo2 && vitals.spo2 < 90) return "critical";
    if (vitals.heart_rate && vitals.heart_rate > 120) return "high";
    return "moderate";
}

function isAbnormalBP(vitals) {
    if (!vitals.systolic_bp) return false;
    return vitals.systolic_bp > 140 || vitals.systolic_bp < 90 || vitals.diastolic_bp > 90;
}

function vitalItem(label, value, abnormal) {
    const cls = value != null ? (abnormal ? "abnormal" : "normal") : "";
    return `<div class="vital-item">
        <div class="vital-label">${label}</div>
        <div class="vital-value ${cls}">${value != null ? value : "--"}</div>
    </div>`;
}

function infoRow(label, value) {
    return `<div class="info-row">
        <span class="info-label">${label}</span>
        <span class="info-value">${value ? esc(String(value)) : "--"}</span>
    </div>`;
}

function esc(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}

// --- Init ---
connectWS();
refreshCases();
// Auto-refresh every 30 seconds
setInterval(refreshCases, 30000);

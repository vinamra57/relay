const FEATURE_FLAGS = {
    evidenceDrawer: true,
    voiceQA: true,
};

const params = new URLSearchParams(window.location.search);
if (params.get("evidence") === "0") FEATURE_FLAGS.evidenceDrawer = false;
if (params.get("voice") === "0") FEATURE_FLAGS.voiceQA = false;

let ws = null;
let cases = {};
let selectedCaseId = null;
let mode = "inbound";

const charts = {};
let chartLoopStarted = false;
let liveStreamActive = false;

class LiveChart {
    constructor(canvasId, color, min, max, waveAmp = 0.8) {
        this.canvas = document.getElementById(canvasId);
        this.ctx = this.canvas.getContext("2d");
        this.color = color;
        this.min = min;
        this.max = max;
        this.waveAmp = waveAmp;
        this.data = Array(40).fill(null);
        this.current = null;
        this.target = null;
        this.phase = Math.random() * Math.PI * 2;
    }

    setTarget(value) {
        if (value == null) return;
        this.target = value;
        if (this.current == null) {
            this.current = value;
            this.data = Array(40).fill(value);
        }
    }

    _push(value) {
        this.data.push(value);
        if (this.data.length > 40) this.data.shift();
    }

    tick() {
        if (!liveStreamActive) return;
        if (this.target == null || this.current == null) return;
        const delta = (this.target - this.current) * 0.28;
        const noise = (Math.random() - 0.5) * (this.max - this.min) * 0.004;
        this.phase += 0.35;
        const wave = Math.sin(this.phase) * this.waveAmp;
        const next = Math.max(this.min, Math.min(this.max, this.current + delta + noise + wave));
        this.current = next;
        this._push(next);
    }

    draw() {
        const { ctx, canvas } = this;
        ctx.clearRect(0, 0, canvas.width, canvas.height);

        ctx.strokeStyle = "rgba(148, 163, 184, 0.2)";
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(0, canvas.height / 2);
        ctx.lineTo(canvas.width, canvas.height / 2);
        ctx.stroke();

        const points = this.data.filter((d) => d != null);
        if (points.length < 2) return;

        const maxVal = this.max;
        const minVal = this.min;
        const stepX = canvas.width / (this.data.length - 1);

        ctx.strokeStyle = this.color;
        ctx.lineWidth = 2;
        ctx.beginPath();
        this.data.forEach((val, idx) => {
            const y = val == null
                ? canvas.height / 2
                : canvas.height - ((val - minVal) / (maxVal - minVal)) * canvas.height;
            const x = idx * stepX;
            if (idx === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        });
        ctx.stroke();
    }
}

function initCharts() {
    charts.hr = new LiveChart("hrChart", "#0ea5e9", 40, 160, 1.6);
    charts.spo2 = new LiveChart("spo2Chart", "#16a34a", 80, 100, 0.4);
    charts.bp = new LiveChart("bpChart", "#64748b", 60, 200, 1.2);

    if (!chartLoopStarted) {
        chartLoopStarted = true;
        requestAnimationFrame(chartLoop);
        setInterval(() => {
            charts.hr.tick();
            charts.spo2.tick();
            charts.bp.tick();
        }, 250);
    }
}

function chartLoop() {
    Object.values(charts).forEach((chart) => chart.draw());
    requestAnimationFrame(chartLoop);
}

function setMode(nextMode) {
    mode = nextMode;
    document.body.classList.toggle("mode-arrived", mode === "arrived");
    document.body.classList.toggle("mode-inbound", mode === "inbound");
    const btn = document.getElementById("modeToggle");
    btn.textContent = mode === "arrived" ? "Arrived" : "Inbound";
    btn.className = mode === "arrived" ? "btn btn-secondary" : "btn btn-toggle";
}

// --- WebSocket ---

function connectWS() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(`${proto}//${location.host}/api/hospital/ws/hospital`);

    ws.onopen = () => {
        const el = document.getElementById("wsStatus");
        el.textContent = "Live";
        el.style.color = "#22c55e";
    };

    ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        handleEvent(msg);
    };

    ws.onclose = () => {
        const el = document.getElementById("wsStatus");
        el.textContent = "Disconnected";
        el.style.color = "#ef4444";
        setTimeout(connectWS, 3000);
    };

    ws.onerror = () => {
        const el = document.getElementById("wsStatus");
        el.textContent = "Error";
        el.style.color = "#ef4444";
    };
}

function handleEvent(msg) {
    const caseId = msg.case_id;
    if (!caseId) return;

    if (!cases[caseId]) {
        cases[caseId] = { id: caseId, nemsis: {}, insights: null };
    }

    if (!selectedCaseId) {
        selectedCaseId = caseId;
    }

    if (msg.type === "nemsis_update") {
        cases[caseId].nemsis = msg.nemsis || {};
        cases[caseId].patient_name = msg.patient_name || cases[caseId].patient_name;
        cases[caseId].last_update = new Date().toISOString();
    } else if (msg.type === "medical_db_complete") {
        cases[caseId].medical_db_response = msg.medical_db_response;
    } else if (msg.type === "gp_call_complete") {
        cases[caseId].gp_response = msg.gp_response;
    } else if (msg.type === "gp_data_received") {
        cases[caseId].gp_response = msg.gp_response;
    } else if (msg.type === "clinical_insights") {
        cases[caseId].insights = msg.insights;
    } else if (msg.type === "arrival_status") {
        cases[caseId].arrival_status = msg.status;
        if (selectedCaseId === caseId && msg.status === "arrived") {
            setMode("arrived");
        }
    }

    renderCaseList();
    if (selectedCaseId === caseId) {
        if (msg.type === "medical_db_complete" || msg.type === "gp_call_complete" || msg.type === "gp_data_received") {
            loadCaseBundle(caseId).then(renderSelectedCase);
        } else {
            renderSelectedCase();
        }
    }
}

// --- Data Loading ---

async function refreshCases() {
    try {
        const resp = await fetch("/api/hospital/active-cases");
        const data = await resp.json();
        cases = {};
        for (const c of data) {
            cases[c.id] = {
                ...c,
                nemsis: c.nemsis || {},
                insights: null,
            };
        }
        renderCaseList();
        if (!selectedCaseId && Object.keys(cases).length > 0) {
            selectedCaseId = Object.keys(cases)[0];
        }
        if (selectedCaseId && cases[selectedCaseId]) {
            loadCaseBundle(selectedCaseId).then(renderSelectedCase);
        }
    } catch (e) {
        console.error("Failed to load cases:", e);
    }
}

async function loadCaseBundle(caseId) {
    try {
        const [caseResp, inboundResp, arrivedResp, insightsResp] = await Promise.all([
            fetch(`/api/cases/${caseId}`),
            fetch(`/api/hospital/summary/${caseId}`),
            fetch(`/api/hospital/case-summary/${caseId}?urgency=critical`),
            fetch(`/api/hospital/clinical-insights/${caseId}`),
        ]);

        if (caseResp.ok) {
            const caseData = await caseResp.json();
            cases[caseId] = {
                ...cases[caseId],
                ...caseData,
                nemsis: caseData.nemsis_data || caseData.nemsis,
                last_update: caseData.updated_at || cases[caseId]?.last_update,
            };
        }
        if (inboundResp.ok) {
            cases[caseId].inbound_summary = await inboundResp.json();
        }
        if (arrivedResp.ok) {
            cases[caseId].arrived_summary = await arrivedResp.json();
        }
        if (insightsResp.ok) {
            cases[caseId].insights = await insightsResp.json();
        }
    } catch (e) {
        console.error("Failed to load case bundle:", e);
    }
}

// --- Rendering ---

function renderCaseList() {
    const body = document.getElementById("caseListBody");
    const ids = Object.keys(cases);
    document.getElementById("caseCount").textContent = ids.length ? "1" : "0";

    if (ids.length === 0) {
        body.innerHTML = '<div class="empty-state">No active cases</div>';
        return;
    }

    const activeId = selectedCaseId && cases[selectedCaseId] ? selectedCaseId : ids[0];
    if (!selectedCaseId) selectedCaseId = activeId;
    const renderIds = [activeId];

    body.innerHTML = renderIds.map((id) => {
        const c = cases[id];
        const nemsis = c.nemsis || {};
        const patient = nemsis.patient || {};
        const situation = nemsis.situation || {};
        const name = c.patient_name || [patient.patient_name_first, patient.patient_name_last].filter(Boolean).join(" ") || "Unknown Patient";
        const age = patient.patient_age || "?";
        const gender = patient.patient_gender || "?";
        const complaint = situation.chief_complaint || "No complaint";
        const priority = getPriority(nemsis);
        const selected = id === selectedCaseId ? " selected" : "";
        const alertLabel = getAlertLabel(c);

        return `<div class="case-card${selected}" onclick="selectCase('${id}')">
            <div class="case-title">
                <span>${esc(name)}</span>
                <span class="priority ${priority}">${priority}</span>
            </div>
            <div class="case-meta">${esc(age)}y ${esc(gender)} · ${esc(complaint)}</div>
            ${alertLabel ? `<div class="case-alert">${esc(alertLabel)}</div>` : ""}
            <div class="case-id">${id.slice(0, 8)}...</div>
        </div>`;
    }).join("");
}

function selectCase(caseId) {
    selectedCaseId = caseId;
    renderCaseList();
    renderSelectedCase();
    loadCaseBundle(caseId).then(() => {
        if (selectedCaseId === caseId) {
            renderSelectedCase();
        }
    });
}

window.selectCase = selectCase;

function renderSelectedCase() {
    if (!selectedCaseId) return;
    const c = cases[selectedCaseId];
    if (!c) return;

    const nemsis = c.nemsis || {};
    const patient = nemsis.patient || {};
    const vitals = nemsis.vitals || {};
    const situation = nemsis.situation || {};
    const history = nemsis.history || {};
    const procedures = nemsis.procedures || {};
    const medications = nemsis.medications || {};

    updateStatusPanel(patient, situation, c, nemsis);
    updateSummaries(c.inbound_summary, c.arrived_summary, c.nemsis, c.insights);
    updateAlertBanner(nemsis, c.insights);
    updateVitals(vitals);
    updateOverview(situation, history);
    updateInterventions(procedures, medications);
    updateAdmin(c);
    updateInsights(c.insights);
    updateHistoryWarnings(c.insights);
    updateDocuments(c.insights);
    updateEvidence(c.insights);
    updateEpcp(nemsis);
    updateStreamFeed(c);
}

function updateStreamStatus(active, hasVitals = false) {
    const dot = document.getElementById("streamDot");
    const text = document.getElementById("streamStatus");
    if (active) {
        dot.style.background = "#22c55e";
        text.textContent = "Streaming live";
        liveStreamActive = true;
    } else if (hasVitals) {
        dot.style.background = "#f59e0b";
        text.textContent = "Demo playback";
        liveStreamActive = true;
    } else {
        dot.style.background = "#6b7280";
        text.textContent = "Waiting for stream";
        liveStreamActive = false;
    }
}

function updateStatusPanel(patient, situation, c, nemsis) {
    const name = c.patient_name || [patient.patient_name_first, patient.patient_name_last].filter(Boolean).join(" ") || "--";
    const demo = [patient.patient_age, patient.patient_gender].filter(Boolean).join(" / ") || "--";
    document.getElementById("patientName").textContent = name;
    document.getElementById("patientDemo").textContent = demo;
    document.getElementById("patientEta").textContent = situation.complaint_duration ? `ETA ${situation.complaint_duration}` : "ETA --";
    document.getElementById("lastUpdate").textContent = c.last_update ? formatTime(c.last_update) : "--";
    const hasVitals = Boolean(nemsis?.vitals && (nemsis.vitals.heart_rate || nemsis.vitals.spo2 || nemsis.vitals.systolic_bp));
    updateStreamStatus(isRecent(c.last_update), hasVitals);

    const badge = document.getElementById("triageBadge");
    const priority = getPriority(c.nemsis || {});
    badge.textContent = priority;
    badge.style.background = priority === "critical" ? "rgba(239, 68, 68, 0.2)" : "rgba(34, 197, 94, 0.2)";
    badge.style.color = priority === "critical" ? "#ef4444" : "#22c55e";

    const handoff = document.getElementById("handoffBadge");
    if (c.core_info_complete) {
        handoff.textContent = "Core info complete";
        handoff.style.color = "#22c55e";
    } else {
        handoff.textContent = "Streaming";
        handoff.style.color = "#94a3b8";
    }
}

function updateEpcp(nemsis) {
    if (!nemsis) return;
    const patient = nemsis.patient || {};
    const vitals = nemsis.vitals || {};
    const situation = nemsis.situation || {};
    const history = nemsis.history || {};
    const times = nemsis.times || {};
    const disposition = nemsis.disposition || {};

    const name = [patient.patient_name_first, patient.patient_name_last].filter(Boolean).join(" ") || "--";
    const demo = [patient.patient_age ? `${patient.patient_age}y` : null, patient.patient_gender].filter(Boolean).join(" / ") || "--";
    const addressParts = [patient.patient_address, patient.patient_city, patient.patient_state, patient.patient_zip].filter(Boolean);

    setText("epcrName", name);
    setText("epcrDemo", demo);
    setText("epcrDob", patient.patient_date_of_birth || "--");
    setText("epcrRace", patient.patient_race || "--");
    setText("epcrPhone", patient.patient_phone || "--");
    setText("epcrAddress", addressParts.length ? addressParts.join(", ") : "--");
    setText("epcrGp", patient.gp_name || "--");
    setText("epcrGpPractice", patient.gp_practice_name || "--");
    setText("epcrGpPhone", patient.gp_phone || "--");

    setText("epcrChief", situation.chief_complaint || "--");
    setText("epcrImpression", situation.primary_impression || "--");
    setText("epcrSecondary", situation.secondary_impression || "--");
    setText("epcrInjury", situation.injury_cause || "--");
    setText("epcrInitialAcuity", situation.initial_acuity || "--");
    setText("epcrOnset", situation.onset_date_time || "--");
    setText("epcrDuration", situation.complaint_duration || "--");

    setText("epcrBP", vitals.systolic_bp && vitals.diastolic_bp ? `${vitals.systolic_bp}/${vitals.diastolic_bp}` : "--");
    setText("epcrHR", vitals.heart_rate != null ? `${vitals.heart_rate} bpm` : "--");
    setText("epcrRR", vitals.respiratory_rate != null ? `${vitals.respiratory_rate} /min` : "--");
    setText("epcrSpO2", vitals.spo2 != null ? `${vitals.spo2}%` : "--");
    setText("epcrGlucose", vitals.blood_glucose != null ? `${vitals.blood_glucose}` : "--");
    setText("epcrTemp", vitals.temperature != null ? `${vitals.temperature}` : "--");
    setText("epcrPain", vitals.pain_scale != null ? `${vitals.pain_scale}/10` : "--");
    setText("epcrGcs", buildGcsText(vitals));
    setText("epcrLOC", vitals.level_of_consciousness || "--");

    setList("epcrHistory", history.medical_history);
    setList("epcrAllergies", history.allergies);
    setList("epcrCurrentMeds", history.current_medications);
    setText("epcrLastIntake", history.last_oral_intake || "--");
    setText("epcrSubstance", history.alcohol_drug_use || "--");

    setList("epcrProcedures", nemsis.procedures?.procedures);
    setList("epcrMedications", nemsis.medications?.medications);

    setText("epcrUnitNotified", times.unit_notified || "--");
    setText("epcrEnRoute", times.unit_en_route || "--");
    setText("epcrArrivedScene", times.unit_arrived_scene || "--");
    setText("epcrArrivedPatient", times.arrived_at_patient || "--");
    setText("epcrLeftScene", times.unit_left_scene || "--");
    setText("epcrArrivedDestination", times.arrived_destination || "--");
    setText("epcrTransfer", times.transfer_of_care || "--");

    setText("epcrDestination", disposition.destination_facility || "--");
    setText("epcrDestinationType", disposition.destination_type || "--");
    setText("epcrTransportMode", disposition.transport_mode || "--");
    setText("epcrDisposition", disposition.transport_disposition || "--");
    setText("epcrDispositionAcuity", disposition.patient_acuity || situation.initial_acuity || "--");
    setList("epcrTeams", disposition.hospital_team_activation);
}

function buildGcsText(vitals) {
    if (!vitals) return "--";
    const parts = [];
    if (vitals.gcs_eye != null) parts.push(`E${vitals.gcs_eye}`);
    if (vitals.gcs_verbal != null) parts.push(`V${vitals.gcs_verbal}`);
    if (vitals.gcs_motor != null) parts.push(`M${vitals.gcs_motor}`);
    if (vitals.gcs_total != null) parts.push(`Total ${vitals.gcs_total}`);
    return parts.length ? parts.join(" ") : "--";
}

function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value || "--";
}

function setList(id, items) {
    const el = document.getElementById(id);
    if (!el) return;
    const values = (items || []).filter(Boolean);
    el.innerHTML = values.length ? values.map((v) => `<li>${esc(v)}</li>`).join("") : "<li>--</li>";
}

function updateSummaries(inbound, arrived, nemsis, insights) {
    const fallbackInbound = buildInboundFromNemsis(nemsis);
    const activeInbound = isSummaryEmpty(inbound, [
        "chief_complaint",
        "clinical_impression",
        "vitals_summary",
        "recommended_preparations",
    ]) ? fallbackInbound : (inbound || fallbackInbound);

    const patient = nemsis?.patient || {};
    const situation = nemsis?.situation || {};
    const history = nemsis?.history || {};
    const name = [patient.patient_name_first, patient.patient_name_last].filter(Boolean).join(" ") || "Unknown patient";
    const demo = [patient.patient_age ? `${patient.patient_age}y` : null, patient.patient_gender].filter(Boolean).join(" ");
    const eta = situation.complaint_duration ? `ETA ${situation.complaint_duration}` : "";
    const inboundSubtitle = [name, demo, eta].filter(Boolean).join(" • ") || "--";

    setPriorityPill("inboundPriority", activeInbound.priority_level || getPriority(nemsis));
    const inboundHeadline = (activeInbound.chief_complaint && activeInbound.chief_complaint !== "--")
        ? activeInbound.chief_complaint
        : activeInbound.clinical_impression || "--";
    const inboundKicker = document.getElementById("inboundKicker");
    if (inboundKicker) {
        inboundKicker.textContent = (activeInbound.chief_complaint && activeInbound.chief_complaint !== "--")
            ? "Chief complaint"
            : "Primary impression";
    }
    document.getElementById("inboundHeadline").textContent = inboundHeadline;
    document.getElementById("inboundSubtitle").textContent = inboundSubtitle;
    document.getElementById("inboundVitals").textContent = activeInbound.vitals_summary || "--";
    document.getElementById("inboundImpression").textContent = activeInbound.clinical_impression || "--";
    document.getElementById("inboundHistory").textContent = buildHistoryLine(activeInbound, history);
    document.getElementById("inboundInterventions").textContent = buildInterventionLine(activeInbound);
    updatePrepChecklist(activeInbound.recommended_preparations);
    setSummaryList("inboundSummaryList", buildInboundSummaryList(activeInbound, nemsis), "Summary pending");

    const fallbackArrived = buildArrivedFromNemsis(nemsis);
    const arrivedSummary = buildArrivedFromSummary(arrived, nemsis);
    const activeArrived = isSummaryEmpty(arrivedSummary, [
        "headline",
        "clinical_narrative",
    ]) ? fallbackArrived : (arrivedSummary || fallbackArrived);
    const arrivedHistoryParts = [];
    if (history?.allergies?.length) arrivedHistoryParts.push(`Allergies: ${history.allergies.join(", ")}`);
    if (history?.medical_history?.length) arrivedHistoryParts.push(`PMH: ${history.medical_history.join(", ")}`);
    if (!arrivedHistoryParts.length) arrivedHistoryParts.push("History pending");
    const arrivedSubtitle = arrivedHistoryParts.join(" • ") || "--";

    setPriorityPill("arrivedPriority", activeArrived.urgency || getPriority(nemsis));
    document.getElementById("arrivedHeadline").textContent = activeArrived.headline || "--";
    document.getElementById("arrivedSubtitle").textContent = arrivedSubtitle;
    setSummaryList("arrivedFindingsList", activeArrived.key_findings, "No key findings recorded");
    setSummaryList("arrivedActionsList", activeArrived.actions_taken, "No interventions recorded");
    setSummaryList("arrivedRisksList", buildRisksList(insights), "No contraindications flagged");
    setSummaryList("arrivedDxList", buildDiagnosisList(insights, nemsis), "Diagnosis pending");
    document.getElementById("arrivedNarrative").textContent = activeArrived.clinical_narrative || "--";
    setSummaryList("arrivedSummaryList", buildArrivedSummaryList(activeArrived, nemsis, insights), "Summary pending");
}

function isSummaryEmpty(summary, keys) {
    if (!summary) return true;
    return keys.every((k) => {
        const val = summary[k];
        if (Array.isArray(val)) return val.length === 0;
        return !val || val === "--";
    });
}

function buildInboundFromNemsis(nemsis) {
    const situation = nemsis?.situation || {};
    const vitals = nemsis?.vitals || {};
    const history = nemsis?.history || {};
    const procedures = nemsis?.procedures?.procedures || [];
    const medications = nemsis?.medications?.medications || [];
    const impression = situation.primary_impression || "Pending";
    const vitalsParts = [];
    if (vitals.systolic_bp && vitals.diastolic_bp) vitalsParts.push(`BP ${vitals.systolic_bp}/${vitals.diastolic_bp}`);
    if (vitals.heart_rate) vitalsParts.push(`HR ${vitals.heart_rate}`);
    if (vitals.spo2) vitalsParts.push(`SpO2 ${vitals.spo2}%`);
    if (vitals.respiratory_rate) vitalsParts.push(`RR ${vitals.respiratory_rate}`);
    const prep = impression.toLowerCase().includes("stemi")
        ? "Activate cath lab"
        : impression.toLowerCase().includes("stroke")
            ? "Prep CT + neuro team"
            : impression.toLowerCase().includes("trauma")
                ? "Prep trauma bay"
                : "Awaiting impression";
    return {
        priority_level: getPriority(nemsis),
        chief_complaint: situation.chief_complaint || "--",
        vitals_summary: vitalsParts.join(" · ") || "--",
        clinical_impression: impression || "--",
        recommended_preparations: prep,
        patient_history: history?.medical_history?.length ? `PMH: ${history.medical_history.join(", ")}` : "",
        special_considerations: history?.allergies?.length ? `Allergies: ${history.allergies.join(", ")}` : "",
        procedures_performed: procedures.length ? procedures.join(", ") : "",
        medications_administered: medications.length ? medications.join(", ") : "",
    };
}

function buildArrivedFromNemsis(nemsis) {
    const patient = nemsis?.patient || {};
    const situation = nemsis?.situation || {};
    const vitals = nemsis?.vitals || {};
    const procedures = nemsis?.procedures?.procedures || [];
    const medications = nemsis?.medications?.medications || [];
    const name = [patient.patient_name_first, patient.patient_name_last].filter(Boolean).join(" ") || "Unknown patient";
    const demo = `${patient.patient_age || "--"}y ${patient.patient_gender || "--"}`;
    const complaint = situation.chief_complaint || "unspecified complaint";
    const findings = [];
    if (vitals.systolic_bp && vitals.diastolic_bp) findings.push(`BP ${vitals.systolic_bp}/${vitals.diastolic_bp}`);
    if (vitals.heart_rate) findings.push(`HR ${vitals.heart_rate}`);
    if (vitals.spo2) findings.push(`SpO2 ${vitals.spo2}%`);
    if (situation.primary_impression) findings.push(situation.primary_impression);
    return {
        headline: situation.primary_impression || complaint,
        clinical_narrative: `Arrived with ${complaint}. ${situation.primary_impression || "Impression pending."}`,
        actions_taken: [...procedures, ...medications],
        key_findings: findings.length ? findings : ["No key findings recorded"],
        urgency: getPriority(nemsis),
    };
}

function buildArrivedFromSummary(summary, nemsis) {
    if (!summary) return null;
    return {
        headline: summary.one_liner || summary.clinical_narrative || "--",
        clinical_narrative: summary.clinical_narrative || "--",
        actions_taken: summary.actions_taken || [],
        key_findings: summary.key_findings || [],
        urgency: summary.urgency || getPriority(nemsis),
    };
}

function setPriorityPill(id, level) {
    const el = document.getElementById(id);
    if (!el) return;
    const normalized = (level || "moderate").toLowerCase();
    el.textContent = normalized;
    el.classList.remove("critical", "high", "moderate");
    if (normalized === "critical") el.classList.add("critical");
    else if (normalized === "high") el.classList.add("high");
    else el.classList.add("moderate");
}

function setSummaryList(id, items, emptyLabel) {
    const el = document.getElementById(id);
    if (!el) return;
    const filtered = (items || []).filter(Boolean);
    el.innerHTML = filtered.length
        ? filtered.map((item) => `<li>${esc(item)}</li>`).join("")
        : `<li>${esc(emptyLabel)}</li>`;
}

function buildHistoryLine(activeInbound, history) {
    const parts = [];
    if (history?.medical_history?.length) {
        parts.push(`PMH: ${history.medical_history.join(", ")}`);
    }
    if (history?.allergies?.length) {
        parts.push(`Allergies: ${history.allergies.join(", ")}`);
    }
    if (!parts.length && activeInbound.patient_history) {
        parts.push(shorten(activeInbound.patient_history, 120));
    }
    if (!parts.length && activeInbound.special_considerations) {
        parts.push(shorten(activeInbound.special_considerations, 120));
    }
    return parts.filter(Boolean).join(" · ") || "--";
}

function buildInterventionLine(activeInbound) {
    const parts = [];
    if (activeInbound.procedures_performed) parts.push(activeInbound.procedures_performed);
    if (activeInbound.medications_administered) parts.push(activeInbound.medications_administered);
    return parts.filter(Boolean).join(" · ") || "--";
}

function shorten(text, max = 120) {
    if (!text) return "";
    if (text.length <= max) return text;
    return `${text.slice(0, max - 1)}…`;
}

function buildRisksList(insights) {
    if (!insights || !insights.contraindications) return [];
    return insights.contraindications.map((item) => {
        if (item.reason) return `${item.label} — ${item.reason}`;
        return item.label;
    });
}

function buildDiagnosisList(insights, nemsis) {
    if (insights && insights.likely_diagnoses && insights.likely_diagnoses.length) {
        const symptomWords = [
            "pain", "complaint", "radiating", "shortness", "breath", "sob", "nausea", "vomit",
            "dizziness", "weakness", "slurred", "speech", "headache", "injury", "trauma",
            "mvc", "accident", "fall", "bleeding", "laceration",
        ];
        const filtered = insights.likely_diagnoses.filter((item) => {
            const label = (item.label || "").toLowerCase();
            if (!label) return false;
            if (symptomWords.some((w) => label.includes(w))) return false;
            return true;
        });
        if (!filtered.length) {
            const situation = nemsis?.situation || {};
            return [situation.primary_impression, situation.secondary_impression, situation.chief_complaint]
                .filter(Boolean);
        }
        const list = filtered
            .sort((a, b) => (b.confidence || 0) - (a.confidence || 0))
            .map((item) => {
                const pct = item.confidence ? ` (${Math.round(item.confidence * 100)}%)` : "";
                return `${item.label}${pct}`;
            });
        return list;
    }
    const situation = nemsis?.situation || {};
    const fallback = [situation.primary_impression, situation.secondary_impression, situation.chief_complaint]
        .filter(Boolean);
    return fallback;
}

function buildInboundSummaryList(activeInbound, nemsis) {
    const patient = nemsis?.patient || {};
    const situation = nemsis?.situation || {};
    const name = [patient.patient_name_first, patient.patient_name_last].filter(Boolean).join(" ") || "Unknown patient";
    const demo = [patient.patient_age ? `${patient.patient_age}y` : null, patient.patient_gender].filter(Boolean).join(" ");
    const items = [];
    items.push(`Patient: ${[name, demo].filter(Boolean).join(", ") || "pending"}`);
    items.push(`Chief complaint: ${activeInbound.chief_complaint || situation.chief_complaint || "pending"}`);
    items.push(`Impression: ${activeInbound.clinical_impression || "pending"}`);
    items.push(`Vitals: ${activeInbound.vitals_summary || "pending"}`);
    const historyLine = buildHistoryLine(activeInbound, nemsis?.history || {});
    items.push(`History: ${historyLine !== "--" ? historyLine : "pending"}`);
    const prep = activeInbound.recommended_preparations || "prep pending";
    items.push(`Prep: ${prep}`);
    return items;
}

function buildArrivedSummaryList(activeArrived, nemsis, insights) {
    const patient = nemsis?.patient || {};
    const name = [patient.patient_name_first, patient.patient_name_last].filter(Boolean).join(" ") || "Unknown patient";
    const demo = [patient.patient_age ? `${patient.patient_age}y` : null, patient.patient_gender].filter(Boolean).join(" ");
    const items = [];
    items.push(`Patient: ${[name, demo].filter(Boolean).join(", ") || "pending"}`);
    items.push(`Primary issue: ${activeArrived.headline || "pending"}`);
    const findings = (activeArrived.key_findings || []).slice(0, 3).join(" · ") || "pending";
    items.push(`Key findings: ${findings}`);
    const actions = (activeArrived.actions_taken || []).slice(0, 3).join(" · ") || "none recorded";
    items.push(`Interventions: ${actions}`);
    const risks = buildRisksList(insights);
    items.push(`Risks: ${risks.length ? risks.slice(0, 2).join("; ") : "none flagged"}`);
    return items;
}

function updatePrepList(prepText) {
    const list = document.getElementById("inboundPrepList");
    if (!list) return;
    if (!prepText) {
        list.innerHTML = "<li>Awaiting impression</li>";
        return;
    }
    const items = prepText.split(/,|;/).map((s) => s.trim()).filter(Boolean);
    list.innerHTML = items.length ? items.map((item) => `<li>${esc(item)}</li>`).join("") : "<li>Prep pending</li>";
}

function updatePrepChecklist(prepText) {
    const list = document.getElementById("prepChecklist");
    if (!prepText) {
        list.innerHTML = '<div class="prep-item">Awaiting impression</div>';
        return;
    }
    const items = prepText.split(/,|;/).map((s) => s.trim()).filter(Boolean);
    list.innerHTML = items.length
        ? items.map((item) => `<div class="prep-item">${esc(item)}</div>`).join("")
        : '<div class="prep-item">Prep pending</div>';
}

function updateAlertBanner(nemsis, insights) {
    const alertTitle = document.getElementById("alertTitle");
    const alertSub = document.getElementById("alertSub");
    const banner = document.getElementById("alertBanner");

    const alert = deriveAlert(nemsis, insights);

    if (alert) {
        banner.classList.remove("safe");
        banner.classList.toggle("critical", alert.severity === "critical");
        alertTitle.textContent = alert.label;
        alertSub.textContent = alert.action || "Prepare team";
    } else {
        banner.classList.add("safe");
        banner.classList.remove("critical");
        alertTitle.textContent = "No critical alerts";
        alertSub.textContent = "Awaiting clinical triggers";
    }
}

function deriveAlert(nemsis, insights) {
    if (insights && insights.prep_alerts && insights.prep_alerts.length) {
        return insights.prep_alerts[0];
    }
    const impression = (nemsis.situation?.primary_impression || "").toLowerCase();
    if (impression.includes("stroke")) {
        return { label: "Stroke Alert", action: "Prep CT + neuro team", severity: "critical" };
    }
    if (impression.includes("stemi")) {
        return { label: "STEMI Alert", action: "Prep cath lab", severity: "critical" };
    }
    if (impression.includes("trauma")) {
        return { label: "Trauma Activation", action: "Prep trauma bay", severity: "high" };
    }
    return null;
}

function getAlertLabel(c) {
    if (!c) return "";
    const nemsis = c.nemsis || {};
    const alert = deriveAlert(nemsis, c.insights);
    return alert ? alert.label : "";
}

function updateVitals(vitals) {
    if (!vitals) return;
    const hr = parseFloat(vitals.heart_rate);
    const spo2 = parseFloat(vitals.spo2);
    const sys = parseFloat(vitals.systolic_bp);
    if (!Number.isNaN(hr)) charts.hr.setTarget(hr);
    if (!Number.isNaN(spo2)) charts.spo2.setTarget(spo2);
    if (!Number.isNaN(sys)) charts.bp.setTarget(sys);

    document.getElementById("vitalHR").textContent = `HR ${vitals.heart_rate || "--"}`;
    document.getElementById("vitalSpO2").textContent = `SpO2 ${vitals.spo2 != null ? vitals.spo2 + "%" : "--"}`;
    document.getElementById("vitalBP").textContent = `BP ${vitals.systolic_bp || "--"}/${vitals.diastolic_bp || "--"}`;
    document.getElementById("vitalGCS").textContent = `GCS ${vitals.gcs_total || "--"}`;
}

function updateOverview(situation, history) {
    setText("overviewComplaint", situation.chief_complaint || "--");
    setText("overviewImpression", situation.primary_impression || "--");
    setText("overviewHistory", (history.medical_history || []).join(", ") || "--");
    setText("overviewAllergies", (history.allergies || []).join(", ") || "--");
}

function updateInterventions(procedures, medications) {
    const procedureList = document.getElementById("proceduresList");
    const medList = document.getElementById("medicationsList");
    const timeline = document.getElementById("timelineList");

    const procItems = procedures?.procedures || [];
    const medItems = medications?.medications || [];

    procedureList.innerHTML = procItems.length ? procItems.map((p) => `<li>${esc(p)}</li>`).join("") : "<li>None recorded</li>";
    medList.innerHTML = medItems.length ? medItems.map((m) => `<li>${esc(m)}</li>`).join("") : "<li>None recorded</li>";

    const timelineItems = [];
    procItems.forEach((item) => timelineItems.push({ label: item, time: "T-6m" }));
    medItems.forEach((item) => timelineItems.push({ label: item, time: "T-4m" }));

    timeline.innerHTML = timelineItems.length
        ? timelineItems.map((t) => `<div class="timeline-item"><span>${esc(t.label)}</span><span>${t.time}</span></div>`).join("")
        : "<div class=\"timeline-item\"><span>Awaiting interventions</span><span>--</span></div>";
}

function updateStreamFeed(c) {
    const feed = document.getElementById("streamFeed");
    if (!feed) return;

    const transcript = c.full_transcript || "";
    let items = [];
    if (transcript) {
        const segments = transcript
            .split(/(?<=[.!?])\s+|\n+/)
            .map((s) => s.trim())
            .filter(Boolean);
        items = segments.slice(-8);
    }

    if (!items.length) {
        const proc = c.nemsis?.procedures?.procedures || [];
        const meds = c.nemsis?.medications?.medications || [];
        items = [
            ...proc.map((p) => `Procedure: ${p}`),
            ...meds.map((m) => `Medication: ${m}`),
        ].slice(0, 6);
    }

    if (!items.length) {
        feed.innerHTML = '<div class="stream-item">Awaiting stream...</div>';
        return;
    }

    feed.innerHTML = items.map((item) => `<div class="stream-item">${esc(item)}</div>`).join("");
}

function updateAdmin(c) {
    const tasks = document.getElementById("adminTasks");
    const transcript = document.getElementById("rawTranscript");
    const gp = document.getElementById("gpTransmission");
    const med = document.getElementById("medicalRecords");

    const gaps = [];
    const nemsis = c.nemsis || {};
    const patient = nemsis.patient || {};
    if (!patient.patient_name_first && !patient.patient_name_last) gaps.push("Confirm patient identity");
    if (!patient.patient_address) gaps.push("Confirm address/contact");
    if (!nemsis.history?.allergies?.length) gaps.push("Confirm allergies");
    if (!nemsis.history?.medical_history?.length) gaps.push("Confirm past history");

    tasks.innerHTML = gaps.length ? gaps.map((g) => `<li>${esc(g)}</li>`).join("") : "<li>No admin tasks pending</li>";
    transcript.textContent = c.full_transcript ? c.full_transcript.slice(-420) : "--";
    gp.textContent = c.gp_response || "--";
    med.textContent = c.medical_db_response || "--";
}

function updateInsights(insights) {
    const warningList = document.getElementById("warningList");
    const diagnosisList = document.getElementById("diagnosisList");

    if (!insights) {
        warningList.innerHTML = '<div class="warning-item">No safety flags yet</div>';
        diagnosisList.innerHTML = "";
        return;
    }

    const warnings = insights.contraindications || [];
    warningList.innerHTML = warnings.length
        ? warnings.map((w) => {
            const detail = w.reason ? ` · ${esc(w.reason)}` : "";
            return `<div class="warning-item critical">${esc(w.label)}${detail}</div>`;
        }).join("")
        : '<div class="warning-item">No safety flags yet</div>';

    const diagnoses = insights.likely_diagnoses || [];
    diagnosisList.innerHTML = diagnoses.length
        ? diagnoses.map((d) => `<span class="chip">${esc(d.label)} ${Math.round((d.confidence || 0) * 100)}%</span>`).join("")
        : '<span class="chip">Awaiting impression</span>';
}

function updateHistoryWarnings(insights) {
    const list = document.getElementById("historyWarningList");
    if (!list) return;
    if (!insights || !insights.history_warnings || insights.history_warnings.length === 0) {
        list.innerHTML = "<div class=\"warning-item\">No history warnings yet</div>";
        return;
    }
    list.innerHTML = insights.history_warnings.map((w) => `<div class="warning-item">${esc(w)}</div>`).join("");
}

function updateDocuments(insights) {
    const grid = document.getElementById("documentGrid");
    if (!insights || !insights.attachments || !insights.attachments.length) {
        grid.innerHTML = "<div class=\"doc-card\">No documents available yet</div>";
        return;
    }
    grid.innerHTML = insights.attachments.map((doc) => `
        <div class="doc-card">
            <div><strong>${esc(doc.name)}</strong></div>
            <div>${esc(doc.file_type)} · ${esc(doc.source)}</div>
            <div>${esc(formatTime(doc.timestamp))}</div>
            <a href="${doc.url}" target="_blank">View</a>
        </div>
    `).join("");
}

function updateEvidence(insights) {
    const list = document.getElementById("evidenceList");
    if (!insights || !insights.evidence) {
        list.innerHTML = "<div class=\"evidence-item\">No evidence items yet</div>";
        return;
    }
    list.innerHTML = insights.evidence.map((item, idx) => `
        <div class="evidence-item" onclick="openEvidence(${idx})">
            <div><strong>${esc(item.source_label || item.source_type)}</strong></div>
            <div class="case-meta">${esc(item.summary)}</div>
        </div>
    `).join("");
}

function openEvidence(index) {
    if (!FEATURE_FLAGS.evidenceDrawer) return;
    const c = cases[selectedCaseId];
    if (!c || !c.insights) return;
    const item = c.insights.evidence?.[index];
    if (!item) return;

    const drawer = document.getElementById("evidenceDrawer");
    const body = document.getElementById("drawerBody");
    const subtitle = document.getElementById("drawerSubtitle");

    subtitle.textContent = item.source_label || item.source_type || "Evidence";
    body.innerHTML = `
        <div class="doc-card">
            <div><strong>${esc(item.source_label || item.source_type)}</strong></div>
            <div>${esc(item.summary)}</div>
            <div class="case-meta">${esc(formatTime(item.timestamp))}</div>
        </div>
    `;
    drawer.classList.add("open");
    drawer.setAttribute("aria-hidden", "false");
}

// --- Ask Relay ---

function setupAskPanel() {
    const panel = document.getElementById("askPanel");
    if (!FEATURE_FLAGS.voiceQA) {
        panel.style.display = "none";
        return;
    }

    const toggle = document.getElementById("askToggle");
    toggle.addEventListener("click", () => {
        panel.classList.toggle("collapsed");
        toggle.textContent = panel.classList.contains("collapsed") ? "Show" : "Hide";
    });

    const sendBtn = document.getElementById("askSend");
    sendBtn.addEventListener("click", askTextQuestion);

    const micBtn = document.getElementById("askMic");
    micBtn.addEventListener("mousedown", startVoiceCapture);
    micBtn.addEventListener("mouseup", stopVoiceCapture);
    micBtn.addEventListener("mouseleave", stopVoiceCapture);
}

async function askTextQuestion() {
    const input = document.getElementById("askText");
    const question = input.value.trim();
    if (!selectedCaseId) {
        setAskResponse("Select a case to ask.");
        return;
    }
    if (!question) return;

    setAskStatus("Thinking...");
    try {
        const resp = await fetch("/api/hospital/ask", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ case_id: selectedCaseId, question }),
        });
        if (!resp.ok) {
            setAskResponse(fallbackAskAnswer(question));
            setAskStatus("Voice ready");
            return;
        }
        const data = await resp.json();
        setAskResponse(data.answer || fallbackAskAnswer(question));
        setAskStatus("Voice ready");
    } catch (e) {
        setAskResponse(fallbackAskAnswer(question));
        setAskStatus("Voice ready");
    }
}

let voiceWs = null;
let voiceStream = null;
let voiceContext = null;
let voiceProcessor = null;
let voiceActive = false;

async function startVoiceCapture() {
    if (!selectedCaseId || voiceActive) return;
    voiceActive = true;
    setAskStatus("Listening...");

    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    voiceWs = new WebSocket(`${proto}//${location.host}/api/hospital/ws/ask/${selectedCaseId}`);

    voiceWs.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        if (msg.type === "question_partial") {
            setAskResponse(msg.text);
        }
        if (msg.type === "answer") {
            setAskResponse(msg.answer?.answer || "No answer");
            setAskStatus("Voice ready");
        }
    };

    voiceWs.onclose = () => {
        if (voiceActive) {
            setAskStatus("Voice ready");
            setAskResponse("Voice session ended.");
        }
    };

    voiceWs.onopen = async () => {
        try {
            voiceStream = await navigator.mediaDevices.getUserMedia({
                audio: { sampleRate: 16000, channelCount: 1, echoCancellation: true, noiseSuppression: true },
            });
            voiceContext = new AudioContext({ sampleRate: 16000 });
            const source = voiceContext.createMediaStreamSource(voiceStream);
            voiceProcessor = voiceContext.createScriptProcessor(4096, 1, 1);
            voiceProcessor.onaudioprocess = (e) => {
                if (voiceWs && voiceWs.readyState === WebSocket.OPEN) {
                    const float32 = e.inputBuffer.getChannelData(0);
                    const int16 = float32ToInt16(float32);
                    const base64 = arrayBufferToBase64(int16.buffer);
                    voiceWs.send(JSON.stringify({ type: "audio_chunk", data: base64 }));
                }
            };
            source.connect(voiceProcessor);
            voiceProcessor.connect(voiceContext.destination);
        } catch (e) {
            setAskStatus("Mic error");
        }
    };
}

function stopVoiceCapture() {
    if (!voiceActive) return;
    voiceActive = false;

    if (voiceWs && voiceWs.readyState === WebSocket.OPEN) {
        setAskStatus("Processing...");
        voiceWs.send(JSON.stringify({ type: "end" }));
    }

    if (voiceProcessor) {
        voiceProcessor.disconnect();
        voiceProcessor = null;
    }
    if (voiceContext) {
        voiceContext.close();
        voiceContext = null;
    }
    if (voiceStream) {
        voiceStream.getTracks().forEach((t) => t.stop());
        voiceStream = null;
    }
}

function setAskStatus(text) {
    const status = document.getElementById("askStatus");
    if (status) status.textContent = text;
}

function setAskResponse(text) {
    const resp = document.getElementById("askResponse");
    if (resp) resp.textContent = text;
}

function fallbackAskAnswer(question) {
    const c = cases[selectedCaseId] || {};
    const nemsis = c.nemsis || {};
    const vitals = nemsis.vitals || {};
    const meds = nemsis.medications?.medications || [];
    const lower = question.toLowerCase();
    if (lower.includes("blood") || lower.includes("lab")) {
        return "Latest labs: Troponin 0.16 ng/mL, WBC 11.2, Glucose 145 mg/dL (demo).";
    }
    if (lower.includes("med")) {
        return `Meds given: ${meds.join(", ") || "none recorded"}`;
    }
    if (lower.includes("vital")) {
        const parts = [];
        if (vitals.heart_rate) parts.push(`HR ${vitals.heart_rate}`);
        if (vitals.spo2) parts.push(`SpO2 ${vitals.spo2}%`);
        if (vitals.systolic_bp && vitals.diastolic_bp) parts.push(`BP ${vitals.systolic_bp}/${vitals.diastolic_bp}`);
        return `Latest vitals: ${parts.join(", ") || "pending"}`;
    }
    return "Answer pending. Try asking about vitals, meds, or labs.";
}

// --- Helpers ---

function float32ToInt16(float32Array) {
    const int16 = new Int16Array(float32Array.length);
    for (let i = 0; i < float32Array.length; i++) {
        const s = Math.max(-1, Math.min(1, float32Array[i]));
        int16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    return int16;
}

function arrayBufferToBase64(buffer) {
    const bytes = new Uint8Array(buffer);
    let binary = "";
    for (let i = 0; i < bytes.byteLength; i++) {
        binary += String.fromCharCode(bytes[i]);
    }
    return btoa(binary);
}

function esc(text) {
    const div = document.createElement("div");
    div.textContent = text || "";
    return div.innerHTML;
}

function formatTime(iso) {
    if (!iso) return "--";
    const d = new Date(iso);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function isRecent(iso, seconds = 8) {
    if (!iso) return false;
    const d = new Date(iso).getTime();
    if (Number.isNaN(d)) return false;
    return Date.now() - d < seconds * 1000;
}

function getPriority(nemsis) {
    const situation = nemsis.situation || {};
    const vitals = nemsis.vitals || {};
    const impression = (situation.primary_impression || "").toLowerCase();
    if (["stemi", "stroke", "cardiac arrest", "trauma"].some((k) => impression.includes(k))) return "critical";
    if (vitals.spo2 && vitals.spo2 < 90) return "critical";
    if (vitals.heart_rate && vitals.heart_rate > 120) return "high";
    return "moderate";
}

function wireTabs() {
    const buttons = document.querySelectorAll(".tab-btn");
    buttons.forEach((btn) => {
        btn.addEventListener("click", () => {
            const tab = btn.dataset.tab;
            activateTab(tab);
        });
    });
}

function activateTab(tab) {
    if (!tab) return;
    const buttons = document.querySelectorAll(".tab-btn");
    buttons.forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((panel) => panel.classList.remove("active"));
    const btn = Array.from(buttons).find((b) => b.dataset.tab === tab);
    if (btn) btn.classList.add("active");
    const panel = document.getElementById(`tab-${tab}`);
    if (panel) panel.classList.add("active");
}

function wireDeepLinks() {
    document.querySelectorAll(".deep-link").forEach((el) => {
        el.addEventListener("click", () => {
            const tab = el.dataset.tab;
            const scrollId = el.dataset.scroll;
            if (tab) activateTab(tab);
            if (scrollId) {
                const target = document.getElementById(scrollId);
                if (target) {
                    target.scrollIntoView({ behavior: "smooth", block: "start" });
                }
            }
        });
    });
}

function wireDrawer() {
    const close = document.getElementById("closeDrawer");
    if (!FEATURE_FLAGS.evidenceDrawer) {
        document.getElementById("evidenceDrawer").style.display = "none";
        const tabButton = document.querySelector(".tab-btn[data-tab='evidence']");
        const tabPanel = document.getElementById("tab-evidence");
        if (tabButton) tabButton.style.display = "none";
        if (tabPanel) tabPanel.style.display = "none";
        return;
    }
    close.addEventListener("click", () => {
        const drawer = document.getElementById("evidenceDrawer");
        drawer.classList.remove("open");
        drawer.setAttribute("aria-hidden", "true");
    });
}

// --- Init ---

document.addEventListener("DOMContentLoaded", () => {
    initCharts();
    connectWS();
    refreshCases();
    wireTabs();
    wireDeepLinks();
    wireDrawer();
    setupAskPanel();
    setMode("inbound");

    const toggle = document.getElementById("modeToggle");
    toggle.addEventListener("click", () => {
        setMode(mode === "inbound" ? "arrived" : "inbound");
    });

    setInterval(refreshCases, 30000);
});

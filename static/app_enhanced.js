// Relay - Enhanced Paramedic UI with Multi-Source Patient History
let currentCaseId = null;
let ws = null;
let mediaStream = null;
let audioContext = null;
let processorNode = null;
let segmentCount = 0;
let sceneTimerInterval = null;
let sceneStartTime = null;
let coreInfoComplete = false;
let voiceGateActive = false;
let lastVoiceAt = 0;

const VOICE_RMS_THRESHOLD = 0.012;
const VOICE_HOLD_MS = 700;

// Store fetched medical history
let fetchedMedicalHistory = null;

// Data source status tracking
const dataSources = {
    FHIR: { status: 'waiting', name: 'FHIR R4 / Synthea' },
    GP: { status: 'waiting', name: 'GP Practice Call' },
    GPData: { status: 'waiting', name: 'GP Records' }
};

// --- Case Management ---

async function newCase() {
    try {
        const resp = await fetch("/api/cases", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
        const data = await resp.json();
        currentCaseId = data.id;

        document.getElementById("caseIdDisplay").textContent = `Case: ${currentCaseId.slice(0, 8)}...`;
        document.getElementById("btnStartStream").disabled = false;
        document.getElementById("btnNewCase").disabled = true;

        setStatus("active", "Ready");
        clearUI();
        resetDataSources();
        
        // Start scene timer
        startSceneTimer();
    } catch (e) {
        console.error("Failed to create case:", e);
        setStatus("error", "Error");
    }
}

// --- Scene Timer ---

function startSceneTimer() {
    sceneStartTime = Date.now();
    updateTimer();
    sceneTimerInterval = setInterval(updateTimer, 1000);
}

function updateTimer() {
    if (!sceneStartTime) return;
    const elapsed = Math.floor((Date.now() - sceneStartTime) / 1000);
    const mins = String(Math.floor(elapsed / 60)).padStart(2, '0');
    const secs = String(elapsed % 60).padStart(2, '0');
    document.getElementById("timerValue").textContent = `${mins}:${secs}`;
}

function stopSceneTimer() {
    if (sceneTimerInterval) {
        clearInterval(sceneTimerInterval);
        sceneTimerInterval = null;
    }
}

// --- Audio Streaming ---

async function startStream() {
    if (!currentCaseId) return;

    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(`${proto}//${location.host}/ws/stream/${currentCaseId}`);

    ws.onopen = () => {
        console.log("WebSocket connected");
        startMicrophone();
    };

    ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        handleServerMessage(msg);
    };

    ws.onclose = () => {
        console.log("WebSocket closed");
        stopMicrophone();
    };

    ws.onerror = (e) => {
        console.error("WebSocket error:", e);
        setStatus("error", "WS Error");
    };

    document.getElementById("btnStartStream").disabled = true;
    document.getElementById("btnStopStream").disabled = false;
    document.getElementById("recordingIndicator").style.display = "flex";
    setStatus("active", "Recording");
}

function stopStream() {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "end_call" }));
        ws.close();
    }
    stopMicrophone();
    stopSceneTimer();

    document.getElementById("btnStartStream").disabled = true;
    document.getElementById("btnStopStream").disabled = true;
    document.getElementById("btnNewCase").disabled = false;
    document.getElementById("recordingIndicator").style.display = "none";
    setStatus("complete", "Completed");
}

async function startMicrophone() {
    try {
        mediaStream = await navigator.mediaDevices.getUserMedia({
            audio: {
                sampleRate: 16000,
                channelCount: 1,
                echoCancellation: true,
                noiseSuppression: true,
            },
        });

        audioContext = new AudioContext({ sampleRate: 16000 });
        const source = audioContext.createMediaStreamSource(mediaStream);

        processorNode = audioContext.createScriptProcessor(4096, 1, 1);
        processorNode.onaudioprocess = (e) => {
            if (ws && ws.readyState === WebSocket.OPEN) {
                const float32 = e.inputBuffer.getChannelData(0);
                let sum = 0;
                for (let i = 0; i < float32.length; i++) {
                    sum += float32[i] * float32[i];
                }
                const rms = Math.sqrt(sum / float32.length);
                const now = performance.now();
                if (rms > VOICE_RMS_THRESHOLD) {
                    voiceGateActive = true;
                    lastVoiceAt = now;
                }
                if (voiceGateActive && now - lastVoiceAt > VOICE_HOLD_MS) {
                    voiceGateActive = false;
                }
                if (!voiceGateActive) {
                    return;
                }
                const int16 = float32ToInt16(float32);
                const base64 = arrayBufferToBase64(int16.buffer);
                ws.send(JSON.stringify({ type: "audio_chunk", data: base64 }));
            }
        };

        source.connect(processorNode);
        processorNode.connect(audioContext.destination);
    } catch (e) {
        console.error("Microphone access failed:", e);
        setStatus("error", "Mic Error");
    }
}

function stopMicrophone() {
    if (processorNode) { processorNode.disconnect(); processorNode = null; }
    if (audioContext) { audioContext.close(); audioContext = null; }
    if (mediaStream) { mediaStream.getTracks().forEach((t) => t.stop()); mediaStream = null; }
}

// --- Audio Helpers ---

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

// --- Server Message Handling ---

function handleServerMessage(msg) {
    switch (msg.type) {
        case "transcript_partial":
            updatePartialTranscript(msg.text);
            break;
        case "transcript_committed":
            addCommittedSegment(msg.text);
            break;
        case "nemsis_update":
            updateNEMSIS(msg.nemsis);
            break;
        case "core_info_complete":
            onCoreInfoComplete();
            break;
        case "medical_db_complete":
            handleMedicalDbComplete(msg.medical_db_response);
            break;
        case "gp_call_triggered":
            handleGpTriggered(msg.message);
            break;
        case "gp_call_complete":
            handleGpComplete(msg.gp_response);
            break;
        case "gp_data_status":
            handleGpDataStatus(msg.status, msg.message);
            break;
        case "gp_data_received":
            handleGpDataReceived(msg.gp_document_summary || msg.gp_response, msg.gp_response);
            break;
        case "error":
            console.error("Server error:", msg.message);
            setStatus("error", "Error");
            break;
    }
}

// --- Transcript UI ---

function updatePartialTranscript(text) {
    let partial = document.getElementById("partialText");
    if (!partial) {
        partial = document.createElement("div");
        partial.id = "partialText";
        partial.className = "transcript-partial";
        document.getElementById("transcriptArea").appendChild(partial);
    }
    partial.textContent = text;
    scrollTranscript();
}

function addCommittedSegment(text) {
    const partial = document.getElementById("partialText");
    if (partial) partial.remove();

    segmentCount++;
    const area = document.getElementById("transcriptArea");

    // Remove placeholder if first segment
    if (segmentCount === 1) {
        area.innerHTML = "";
    }

    const seg = document.createElement("div");
    seg.className = "transcript-segment";
    const time = new Date().toLocaleTimeString();
    seg.innerHTML = `<span class="time">${time}</span>${escapeHtml(text)}`;
    area.appendChild(seg);

    document.getElementById("segmentCount").textContent = `${segmentCount} segments`;
    scrollTranscript();
}

function scrollTranscript() {
    const area = document.getElementById("transcriptArea");
    area.scrollTop = area.scrollHeight;
}

// --- NEMSIS Updates ---

function updateNEMSIS(nemsis) {
    const p = nemsis.patient || {};
    const v = nemsis.vitals || {};
    const s = nemsis.situation || {};
    const proc = nemsis.procedures || {};
    const med = nemsis.medications || {};

    setField("nFirstName", p.patient_name_first);
    setField("nLastName", p.patient_name_last);
    setField("nAge", p.patient_age);
    setField("nGender", p.patient_gender);
    setField("nAddress", p.patient_address);
    setField("nCity", p.patient_city);
    setField("nState", p.patient_state);

    // Vitals with warning/critical highlighting
    if (v.systolic_bp || v.diastolic_bp) {
        setVital("nBP", `${v.systolic_bp || "--"}/${v.diastolic_bp || "--"}`, 
            v.systolic_bp > 180 || v.systolic_bp < 90 ? 'critical' : v.systolic_bp > 140 ? 'warning' : null);
    }
    setVital("nHR", v.heart_rate, 
        v.heart_rate > 120 || v.heart_rate < 50 ? 'warning' : null);
    setVital("nRR", v.respiratory_rate,
        v.respiratory_rate > 24 || v.respiratory_rate < 10 ? 'warning' : null);
    setVital("nSpO2", v.spo2,
        v.spo2 < 92 ? 'critical' : v.spo2 < 95 ? 'warning' : null);
    setVital("nGlucose", v.blood_glucose,
        v.blood_glucose > 300 || v.blood_glucose < 70 ? 'warning' : null);
    setVital("nGCS", v.gcs_total,
        v.gcs_total < 13 ? 'warning' : null);

    // Situation
    setField("nChief", s.chief_complaint);
    setField("nPrimary", s.primary_impression);
    setField("nSecondary", s.secondary_impression);

    // Procedures
    const procList = document.getElementById("nProcedures");
    if (proc.procedures && proc.procedures.length > 0) {
        procList.innerHTML = proc.procedures.map((p) => `<li>${escapeHtml(p)}</li>`).join("");
    }

    // Medications
    const medList = document.getElementById("nMedications");
    if (med.medications && med.medications.length > 0) {
        medList.innerHTML = med.medications.map((m) => `<li>${escapeHtml(m)}</li>`).join("");
    }

    // Update core info dots
    updateCoreDots(p);

    // If GP info is detected in NEMSIS, mark GP call as in progress
    if ((p.gp_name || p.gp_phone || p.gp_practice_name) && dataSources.GP?.status === 'waiting') {
        setSourceStatus('GP', 'querying');
        updateSourceResult('GP', 'GP contact detected');
    }

    if (p.gp_name || p.gp_phone || p.gp_practice_name) {
        setStatusPill("gpExtractedBadge", "success");
    }
}

function setField(id, value) {
    const el = document.getElementById(id);
    if (!el) return;
    if (value != null && value !== "") {
        el.textContent = value;
        el.classList.add('filled');
    }
}

function setVital(id, value, severity) {
    const el = document.getElementById(id);
    if (!el) return;
    if (value != null && value !== "") {
        el.textContent = value;
        el.className = 'vital-value filled';
        if (severity) el.classList.add(severity);
    }
}

function updateCoreDots(patient) {
    const dots = {
        dotName: !!(patient.patient_name_first || patient.patient_name_last),
        dotAddress: !!patient.patient_address,
        dotAge: !!patient.patient_age,
        dotGender: !!patient.patient_gender,
    };
    for (const [id, complete] of Object.entries(dots)) {
        const dot = document.getElementById(id);
        if (dot) {
            dot.className = complete ? "core-dot filled" : "core-dot";
        }
    }
}

// --- Core Info Complete - Trigger Multi-Source Lookup ---

function onCoreInfoComplete() {
    if (coreInfoComplete) return;
    coreInfoComplete = true;

    // Show core complete badge
    document.getElementById("coreCompleteIndicator").style.display = "block";
    setStatus("active", "Core Info Complete");

    // Show and activate sources panel
    document.getElementById("sourcesMessage").style.display = "none";
    document.getElementById("sourcesGrid").style.display = "flex";
    document.getElementById("patientHistory").style.display = "block";
    document.getElementById("sourcesStatus").textContent = "Querying Synthea FHIR...";
    document.getElementById("sourcesStatus").classList.add("active");
    // Start querying sources (backend will notify when done)
    startSourceLookup();
}

function startSourceLookup() {
    setSourceStatus('FHIR', 'querying');
    document.getElementById("sourcesStatus").textContent = "Querying FHIR...";
}

function setSourceStatus(sourceId, status) {
    const item = document.getElementById(`source${sourceId}`);
    const statusDot = item?.querySelector('.source-status');
    const statusMap = {
        contacting: 'querying',
        pending: 'querying',
        waiting: 'waiting',
        received: 'success',
        success: 'success',
        querying: 'querying',
        failed: 'failed',
    };
    const normalized = statusMap[status] || status;
    
    if (item && statusDot) {
        // Update item class
        item.className = `source-item ${normalized}`;
        // Update status dot
        statusDot.className = `source-status ${normalized}`;
        
        dataSources[sourceId].status = status;
    }
}

function updateSourceResult(sourceId, payload) {
    const resultEl = document.getElementById(`result${sourceId}`);
    if (!resultEl) return;

    if (typeof payload === 'string') {
        resultEl.textContent = payload;
        return;
    }

    if (sourceId === 'FHIR' && payload) {
        const condCount = payload.conditions?.length || 0;
        const medCount = payload.medications?.length || 0;
        const allergyCount = payload.allergies?.length || 0;
        resultEl.textContent = `${condCount} conditions, ${medCount} meds, ${allergyCount} allergies`;
        return;
    }

    resultEl.textContent = 'Data found';
}

// --- Show Aggregated Patient History ---

function showAggregatedHistory(history) {
    // Count successful sources
    const successCount = Object.values(dataSources).filter(s => s.status === 'success').length;
    document.getElementById("sourceCount").textContent = successCount;

    const data = history || {
        allergies: [],
        medications: [],
        conditions: [],
        immunizations: [],
        procedures: [],
    };

    const allergies = data.allergies || [];
    const medications = data.medications || [];
    const conditions = data.conditions || [];
    const immunizations = data.immunizations || [];
    const procedures = data.procedures || [];

    if (
        !allergies.length
        && !medications.length
        && !conditions.length
        && !immunizations.length
        && !procedures.length
    ) {
        showNoRecordsMessage();
        return;
    }

    // Allergies section - hide entirely if no allergies
    const allergiesSection = document.getElementById("allergiesSection");
    const allergiesEl = document.getElementById("historyAllergies");
    if (allergies.length > 0) {
        allergiesSection.style.display = 'block';
        allergiesEl.innerHTML = allergies.map(a => 
            `<span class="history-item allergy">${escapeHtml(a)}</span>`
        ).join('');
    } else {
        allergiesSection.style.display = 'none';
    }

    // Medications section - hide if empty
    const medsSection = document.getElementById("medicationsSection");
    const medsEl = document.getElementById("historyMedications");
    if (medications.length > 0) {
        medsSection.style.display = 'block';
        medsEl.innerHTML = medications.map(m => 
            `<span class="history-item medication">${escapeHtml(m)}</span>`
        ).join('');
    } else {
        medsSection.style.display = 'none';
    }

    // Conditions section - hide if empty
    const conditionsSection = document.getElementById("conditionsSection");
    const conditionsEl = document.getElementById("historyConditions");
    if (conditions.length > 0) {
        conditionsSection.style.display = 'block';
        conditionsEl.innerHTML = conditions.map(c => 
            `<span class="history-item condition">${escapeHtml(c)}</span>`
        ).join('');
    } else {
        conditionsSection.style.display = 'none';
    }

    // Immunizations section - hide if empty
    const immuneSection = document.getElementById("immunizationsSection");
    const immuneEl = document.getElementById("historyImmunizations");
    if (immunizations.length > 0) {
        immuneSection.style.display = 'block';
        immuneEl.innerHTML = immunizations.map(i => 
            `<span class="history-item">${escapeHtml(i)}</span>`
        ).join('');
    } else {
        immuneSection.style.display = 'none';
    }

    // Procedures section - hide if empty
    const procSection = document.getElementById("proceduresSection");
    const procEl = document.getElementById("historyProcedures");
    if (procedures.length > 0) {
        procSection.style.display = 'block';
        // Limit to most recent 10 procedures
        const recentProcs = procedures.slice(0, 10);
        procEl.innerHTML = recentProcs.map(p => 
            `<span class="history-item">${escapeHtml(p)}</span>`
        ).join('');
        if (procedures.length > 10) {
            procEl.innerHTML += `<span class="history-item muted">...and ${procedures.length - 10} more</span>`;
        }
    } else {
        procSection.style.display = 'none';
    }
}

function showNoRecordsMessage() {
    document.getElementById("sourceCount").textContent = "0";
    // Hide all data sections since patient not found
    document.getElementById("allergiesSection").style.display = 'none';
    document.getElementById("medicationsSection").style.display = 'none';
    document.getElementById("conditionsSection").style.display = 'none';
    document.getElementById("immunizationsSection").style.display = 'none';
    document.getElementById("proceduresSection").style.display = 'none';
    // Show not found message
    document.getElementById("patientHistory").innerHTML = `
        <div class="history-header">
            <h3>📁 Patient Medical History</h3>
            <span class="history-sources">Patient not found in FHIR database</span>
        </div>
        <div class="history-section">
            <p class="no-data">No matching patient records found in connected health systems.</p>
        </div>
    `;
}

function showClinicalAlerts(history) {
    const alertsSection = document.getElementById("clinicalAlerts");
    const alertsContent = document.getElementById("alertsContent");
    
    const alerts = [];
    
    // Only generate alerts from REAL allergy data
    const allergies = history?.allergies || [];
    for (const allergy of allergies) {
        const allergyLower = allergy.toLowerCase();
        if (allergyLower.includes('penicillin') || allergyLower.includes('amoxicillin')) {
            alerts.push({
                type: 'danger',
                title: '⚠️ PENICILLIN ALLERGY',
                desc: `Patient allergic to: ${allergy}. Avoid beta-lactam antibiotics.`
            });
        } else if (allergyLower.includes('sulfa') || allergyLower.includes('sulfonamide')) {
            alerts.push({
                type: 'danger',
                title: '⚠️ SULFA ALLERGY',
                desc: `Patient allergic to: ${allergy}. Avoid sulfonamide drugs.`
            });
        } else if (allergyLower.includes('latex')) {
            alerts.push({
                type: 'danger',
                title: '⚠️ LATEX ALLERGY',
                desc: `${allergy} - Use latex-free gloves and equipment.`
            });
        } else if (allergy && !allergyLower.includes('no known')) {
            alerts.push({
                type: 'warning',
                title: '💊 Allergy Alert',
                desc: `Patient allergic to: ${allergy}`
            });
        }
    }
    
    // Only generate alerts from REAL condition data
    const conditions = history?.conditions || [];
    for (const condition of conditions) {
        const condLower = condition.toLowerCase();
        if (condLower.includes('diabetes')) {
            alerts.push({
                type: 'warning',
                title: '🩺 Diabetes',
                desc: `${condition} - Monitor blood glucose, consider insulin requirements.`
            });
        } else if (condLower.includes('kidney') || condLower.includes('renal')) {
            alerts.push({
                type: 'warning',
                title: '🩺 Renal Condition',
                desc: `${condition} - Adjust renal-cleared medications. Monitor fluid status.`
            });
        } else if (condLower.includes('cardiac arrest') || condLower.includes('heart failure')) {
            alerts.push({
                type: 'danger',
                title: '❤️ Cardiac History',
                desc: `${condition} - Cardiac monitoring recommended.`
            });
        } else if (condLower.includes('hypertension')) {
            alerts.push({
                type: 'warning',
                title: '❤️ Hypertension',
                desc: `${condition} - Monitor blood pressure.`
            });
        } else if (condLower.includes('overdose')) {
            alerts.push({
                type: 'danger',
                title: '⚠️ Overdose History',
                desc: `${condition} - Consider substance use history.`
            });
        }
    }
    
    // Only show alerts section if there are actual alerts
    if (alerts.length > 0) {
        alertsSection.style.display = "block";
        alertsContent.innerHTML = alerts.map(a => `
            <div class="alert-item ${a.type === 'danger' ? '' : 'warning'}">
                <div class="alert-title">${a.title}</div>
                <div class="alert-desc">${escapeHtml(a.desc)}</div>
            </div>
        `).join('');
    } else {
        // Hide alerts section entirely if no alerts
        alertsSection.style.display = "none";
    }
}

function showHospitalBanner() {
    const banner = document.getElementById("hospitalBanner");
    banner.style.display = "block";
    document.getElementById("bannerTime").textContent = new Date().toLocaleTimeString();
}

function handleMedicalDbComplete(reportText) {
    setSourceStatus('FHIR', 'success');
    updateSourceResult('FHIR', 'History loaded');
    document.getElementById("sourcesStatus").textContent = "Medical history received";
    document.getElementById("patientHistory").style.display = "block";
    const parsed = parseMedicalDbReport(reportText || "");
    fetchedMedicalHistory = parsed;
    showAggregatedHistory(parsed);
    showClinicalAlerts(parsed);
    showHospitalBanner();
}

function handleGpTriggered(message) {
    setSourceStatus('GP', 'querying');
    updateSourceResult('GP', 'Calling GP...');
    document.getElementById("gpCallSection").style.display = "block";
    document.getElementById("gpCallStatus").textContent = "Calling...";
    document.getElementById("gpCallStatus").className = "gp-call-status calling";
    document.getElementById("gpCallTranscript").textContent = message || "Initiating GP voice call...";
    setStatusPill("gpCallBadge", "active");
}

function handleGpComplete(gpResponse) {
    setSourceStatus('GP', 'success');
    updateSourceResult('GP', 'Call complete');
    document.getElementById("gpCallSection").style.display = "block";
    document.getElementById("gpCallStatus").textContent = "Complete";
    document.getElementById("gpCallStatus").className = "gp-call-status complete";
    if (gpResponse) {
        document.getElementById("gpCallTranscript").textContent = gpResponse;
    }
    const responseLower = (gpResponse || "").toLowerCase();
    if (responseLower.includes("skipped") || responseLower.includes("disabled")) {
        setStatusPill("gpCallBadge", "warning", "GP call disabled");
    } else {
        setStatusPill("gpCallBadge", "success");
    }
}

function handleGpDataStatus(status, message) {
    const statusText = message || "Waiting for GP records...";
    setSourceStatus('GPData', status || 'waiting');
    updateSourceResult('GPData', statusText);
    document.getElementById("gpDataSection").style.display = "block";
    const statusEl = document.getElementById("gpDataStatus");
    statusEl.textContent = statusText;
    statusEl.className = `gp-call-status ${status === 'received' ? 'complete' : 'calling'}`;
    const sourcesStatus = document.getElementById("sourcesStatus");
    sourcesStatus.textContent = statusText;
    sourcesStatus.classList.add("active");
}

function handleGpDataReceived(summaryText, fullText) {
    setSourceStatus('GPData', 'success');
    updateSourceResult('GPData', 'Records received');
    document.getElementById("gpDataSection").style.display = "block";
    const statusEl = document.getElementById("gpDataStatus");
    statusEl.textContent = "Records received";
    statusEl.className = "gp-call-status complete";
    const displayText = summaryText || fullText || "GP records received.";
    document.getElementById("gpDataTranscript").textContent = displayText;
    const sourcesStatus = document.getElementById("sourcesStatus");
    sourcesStatus.textContent = "GP records received";
    sourcesStatus.classList.add("active");
}

function parseMedicalDbReport(text) {
    const lines = text.split("\n");
    const sections = {
        conditions: [],
        allergies: [],
        medications: [],
        immunizations: [],
        procedures: [],
    };
    let current = "";
    for (const line of lines) {
        const trimmed = line.trim();
        if (trimmed.includes("CONDITIONS / MEDICAL HISTORY")) current = "conditions";
        else if (trimmed.includes("ALLERGIES")) current = "allergies";
        else if (trimmed.includes("CURRENT MEDICATIONS")) current = "medications";
        else if (trimmed.includes("IMMUNIZATION HISTORY")) current = "immunizations";
        else if (trimmed.includes("PAST PROCEDURES")) current = "procedures";
        else if (trimmed.startsWith("*") || trimmed.startsWith("-") || trimmed.startsWith("!!")) {
            const value = trimmed.replace(/^(\*|-|!!)\s*/, "");
            if (current && value) sections[current].push(value);
        }
    }
    return sections;
}

// --- UI State ---

function setStatus(type, text) {
    const badge = document.getElementById("statusBadge");
    badge.textContent = text;
    badge.className = `status-badge status-${type}`;
}

function setStatusPill(id, state, label) {
    const el = document.getElementById(id);
    if (!el) return;
    el.className = `status-pill ${state || ""}`.trim();
    if (label) el.textContent = label;
}

function resetDataSources() {
    for (const key of Object.keys(dataSources)) {
        dataSources[key].status = 'waiting';
        setSourceStatus(key, 'waiting');
        const resultEl = document.getElementById(`result${key}`);
        if (resultEl) resultEl.textContent = '';
    }
}

function clearUI() {
    // Reset transcript
    document.getElementById("transcriptArea").innerHTML = `
        <div class="empty-state">
            <div class="empty-icon">🎤</div>
            <p>Waiting for voice input...</p>
            <p class="empty-hint">Click "Start Recording" to begin</p>
        </div>`;
    segmentCount = 0;
    document.getElementById("segmentCount").textContent = "0 segments";

    // Reset NEMSIS fields
    document.querySelectorAll(".nemsis-field .value").forEach((el) => {
        el.textContent = "--";
        el.className = "value";
    });
    document.querySelectorAll(".vital-value").forEach((el) => {
        el.textContent = "--";
        el.className = "vital-value";
    });
    document.getElementById("nBP").textContent = "--/--";
    document.getElementById("nProcedures").innerHTML = '<li class="empty">None recorded</li>';
    document.getElementById("nMedications").innerHTML = '<li class="empty">None recorded</li>';

    // Reset core info
    document.querySelectorAll(".core-dot").forEach((d) => (d.className = "core-dot"));
    document.getElementById("coreCompleteIndicator").style.display = "none";
    coreInfoComplete = false;
    fetchedMedicalHistory = null;

    // Reset sources panel
    document.getElementById("sourcesMessage").style.display = "block";
    document.getElementById("sourcesGrid").style.display = "none";
    document.getElementById("patientHistory").style.display = "none";
    document.getElementById("clinicalAlerts").style.display = "none";
    document.getElementById("gpCallSection").style.display = "none";
    document.getElementById("gpDataSection").style.display = "none";
    const gpDataTranscript = document.getElementById("gpDataTranscript");
    if (gpDataTranscript) gpDataTranscript.textContent = "";
    const gpDataStatus = document.getElementById("gpDataStatus");
    if (gpDataStatus) {
        gpDataStatus.textContent = "Waiting for records...";
        gpDataStatus.className = "gp-call-status";
    }
    document.getElementById("hospitalBanner").style.display = "none";
    document.getElementById("sourcesStatus").textContent = "Waiting for Core ID";
    document.getElementById("sourcesStatus").classList.remove("active");
    setStatusPill("gpExtractedBadge", "");
    setStatusPill("gpCallBadge", "");

    // Reset timer
    document.getElementById("timerValue").textContent = "00:00";
    sceneStartTime = null;
}

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}

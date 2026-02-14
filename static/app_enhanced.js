// Aria Health - Enhanced Paramedic UI with Multi-Source Patient History
let currentCaseId = null;
let ws = null;
let mediaStream = null;
let audioContext = null;
let processorNode = null;
let segmentCount = 0;
let sceneTimerInterval = null;
let sceneStartTime = null;
let coreInfoComplete = false;

// Data source status tracking
const dataSources = {
    HIE: { status: 'waiting', name: 'Regional HIE Network' },
    Particle: { status: 'waiting', name: 'Particle Health API' },
    FHIR: { status: 'waiting', name: 'FHIR R4 / Synthea' },
    EHR: { status: 'waiting', name: 'EHR Systems Query' },
    PDMP: { status: 'waiting', name: 'PDMP Registry' },
    Pharmacy: { status: 'waiting', name: 'Pharmacy Networks' },
    IIS: { status: 'waiting', name: 'Immunization Registry' },
    GP: { status: 'waiting', name: 'Primary Care Provider' }
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
        case "downstream_complete":
            showDownstream(msg.gp_response, msg.medical_db_response);
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
    document.getElementById("sourcesStatus").textContent = "Querying Sources...";
    document.getElementById("sourcesStatus").classList.add("active");

    // Start querying all sources with staggered timing for visual effect
    startMultiSourceLookup();
}

async function startMultiSourceLookup() {
    // Define query order and timing (simulates real-world latency differences)
    const querySequence = [
        { id: 'FHIR', delay: 200, duration: 1500 },
        { id: 'HIE', delay: 400, duration: 2500 },
        { id: 'Particle', delay: 600, duration: 3000 },
        { id: 'EHR', delay: 800, duration: 2800 },
        { id: 'PDMP', delay: 1000, duration: 2000 },
        { id: 'Pharmacy', delay: 1200, duration: 3500 },
        { id: 'IIS', delay: 1400, duration: 1800 },
        { id: 'GP', delay: 1600, duration: 4000 }
    ];

    // Start all queries
    for (const source of querySequence) {
        setTimeout(() => {
            setSourceStatus(source.id, 'querying');
        }, source.delay);

        setTimeout(() => {
            // Simulate success/failure (FHIR always succeeds since we have it)
            const success = source.id === 'FHIR' ? true : Math.random() > 0.3;
            setSourceStatus(source.id, success ? 'success' : 'failed');
            
            if (success) {
                updateSourceResult(source.id);
            }
        }, source.delay + source.duration);
    }

    // After all sources complete, show aggregated results
    setTimeout(() => {
        document.getElementById("sourcesStatus").textContent = "Lookup Complete";
        showAggregatedHistory();
        showClinicalAlerts();
        showHospitalBanner();
    }, 5500);
}

function setSourceStatus(sourceId, status) {
    const item = document.getElementById(`source${sourceId}`);
    const statusDot = item?.querySelector('.source-status');
    
    if (item && statusDot) {
        // Update item class
        item.className = `source-item ${status}`;
        // Update status dot
        statusDot.className = `source-status ${status}`;
        
        dataSources[sourceId].status = status;
    }
}

function updateSourceResult(sourceId) {
    const resultEl = document.getElementById(`result${sourceId}`);
    if (!resultEl) return;

    const results = {
        FHIR: '4 conditions, 6 meds',
        HIE: '3 encounters found',
        Particle: '2 providers linked',
        EHR: 'Records retrieved',
        PDMP: 'Rx history found',
        Pharmacy: '5 prescriptions',
        IIS: '8 immunizations',
        GP: 'History received'
    };

    resultEl.textContent = results[sourceId] || 'Data found';
}

// --- Show Aggregated Patient History ---

function showAggregatedHistory() {
    // Count successful sources
    const successCount = Object.values(dataSources).filter(s => s.status === 'success').length;
    document.getElementById("sourceCount").textContent = successCount;

    // Demo patient history data (would come from real API)
    const history = {
        allergies: ['Penicillin (SEVERE)', 'Sulfonamides', 'Iodine contrast'],
        medications: ['Metformin 500mg', 'Lisinopril 10mg', 'Atorvastatin 20mg', 'Aspirin 81mg'],
        conditions: ['Diabetes Mellitus Type 2', 'Essential Hypertension', 'Hyperlipidemia', 'Chronic Kidney Disease Stage 2'],
        immunizations: ['Influenza (2025-09)', 'COVID-19 (2024-10)', 'Td (2023-06)'],
        procedures: ['Colonoscopy (2024-03)', 'Echocardiogram (2024-01)']
    };

    // Populate allergies
    const allergiesEl = document.getElementById("historyAllergies");
    allergiesEl.innerHTML = history.allergies.map(a => 
        `<span class="history-item allergy">${escapeHtml(a)}</span>`
    ).join('');

    // Populate medications
    const medsEl = document.getElementById("historyMedications");
    medsEl.innerHTML = history.medications.map(m => 
        `<span class="history-item medication">${escapeHtml(m)}</span>`
    ).join('');

    // Populate conditions
    const conditionsEl = document.getElementById("historyConditions");
    conditionsEl.innerHTML = history.conditions.map(c => 
        `<span class="history-item condition">${escapeHtml(c)}</span>`
    ).join('');

    // Populate immunizations
    const immuneEl = document.getElementById("historyImmunizations");
    immuneEl.innerHTML = history.immunizations.map(i => 
        `<span class="history-item">${escapeHtml(i)}</span>`
    ).join('');

    // Populate procedures
    const procEl = document.getElementById("historyProcedures");
    procEl.innerHTML = history.procedures.map(p => 
        `<span class="history-item">${escapeHtml(p)}</span>`
    ).join('');
}

function showClinicalAlerts() {
    const alertsSection = document.getElementById("clinicalAlerts");
    const alertsContent = document.getElementById("alertsContent");
    
    alertsSection.style.display = "block";
    alertsContent.innerHTML = `
        <div class="alert-item">
            <div class="alert-title">⚠️ PENICILLIN ALLERGY</div>
            <div class="alert-desc">Patient has severe penicillin allergy. Avoid beta-lactam antibiotics.</div>
        </div>
        <div class="alert-item warning">
            <div class="alert-title">💊 Drug Interaction Check</div>
            <div class="alert-desc">Metformin + contrast: Hold metformin if CT with contrast needed.</div>
        </div>
        <div class="alert-item warning">
            <div class="alert-title">🩺 Chronic Conditions</div>
            <div class="alert-desc">CKD Stage 2: Adjust renal-cleared medications. Monitor fluid status.</div>
        </div>
    `;
}

function showHospitalBanner() {
    const banner = document.getElementById("hospitalBanner");
    banner.style.display = "block";
    document.getElementById("bannerTime").textContent = new Date().toLocaleTimeString();
}

function showDownstream(gp, medDb) {
    // This is called by the server when downstream lookups complete
    // In the enhanced UI, this triggers the patient history display
    console.log("Downstream complete:", gp, medDb);
}

// --- UI State ---

function setStatus(type, text) {
    const badge = document.getElementById("statusBadge");
    badge.textContent = text;
    badge.className = `status-badge status-${type}`;
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

    // Reset sources panel
    document.getElementById("sourcesMessage").style.display = "block";
    document.getElementById("sourcesGrid").style.display = "none";
    document.getElementById("patientHistory").style.display = "none";
    document.getElementById("clinicalAlerts").style.display = "none";
    document.getElementById("hospitalBanner").style.display = "none";
    document.getElementById("sourcesStatus").textContent = "Waiting for Core ID";
    document.getElementById("sourcesStatus").classList.remove("active");

    // Reset timer
    document.getElementById("timerValue").textContent = "00:00";
    sceneStartTime = null;
}

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}

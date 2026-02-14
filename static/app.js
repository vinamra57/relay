// Aria Health - Paramedic UI
let currentCaseId = null;
let ws = null;
let mediaStream = null;
let audioContext = null;
let processorNode = null;
let segmentCount = 0;

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
    } catch (e) {
        console.error("Failed to create case:", e);
        setStatus("error", "Error");
    }
}

// --- Audio Streaming ---

async function startStream() {
    if (!currentCaseId) return;

    // Connect WebSocket
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
    setStatus("active", "Streaming");
}

function stopStream() {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "end_call" }));
        ws.close();
    }
    stopMicrophone();

    document.getElementById("btnStartStream").disabled = true;
    document.getElementById("btnStopStream").disabled = true;
    document.getElementById("btnNewCase").disabled = false;
    document.getElementById("recordingIndicator").style.display = "none";
    setStatus("idle", "Completed");
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

        // Use ScriptProcessorNode for PCM capture
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
    if (processorNode) {
        processorNode.disconnect();
        processorNode = null;
    }
    if (audioContext) {
        audioContext.close();
        audioContext = null;
    }
    if (mediaStream) {
        mediaStream.getTracks().forEach((t) => t.stop());
        mediaStream = null;
    }
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

// --- UI Updates ---

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
    // Remove partial
    const partial = document.getElementById("partialText");
    if (partial) partial.remove();

    segmentCount++;
    const area = document.getElementById("transcriptArea");

    // Remove placeholder if it's the first segment
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

    // Vitals
    if (v.systolic_bp || v.diastolic_bp) {
        setField("nBP", `${v.systolic_bp || "--"}/${v.diastolic_bp || "--"}`);
    }
    setField("nHR", v.heart_rate);
    setField("nRR", v.respiratory_rate);
    setField("nSpO2", v.spo2 != null ? `${v.spo2}%` : null);
    setField("nGlucose", v.blood_glucose);
    setField("nGCS", v.gcs_total);

    // Situation
    setField("nChief", s.chief_complaint);
    setField("nPrimary", s.primary_impression);
    setField("nSecondary", s.secondary_impression);
    setField("nInjury", s.injury_cause);

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
        el.className = "value filled";
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
            dot.className = complete ? "core-dot complete" : "core-dot";
        }
    }
}

function onCoreInfoComplete() {
    setStatus("active", "Core Info Complete");
}

function showDownstream(gp, medDb) {
    document.getElementById("downstreamSection").style.display = "block";
    document.getElementById("gpResponse").textContent = gp || "No response";
    document.getElementById("medDbResponse").textContent = medDb || "No response";
}

function setStatus(type, text) {
    const badge = document.getElementById("statusBadge");
    badge.textContent = text;
    badge.className = `status-badge status-${type}`;
}

function clearUI() {
    document.getElementById("transcriptArea").innerHTML =
        '<div style="color: #3a4052; text-align: center; padding-top: 40px;">Click "Start Recording" to begin live transcription.</div>';
    segmentCount = 0;
    document.getElementById("segmentCount").textContent = "0 segments";

    // Reset NEMSIS fields
    document.querySelectorAll("#nemsisArea .value").forEach((el) => {
        el.textContent = "--";
        el.className = "value empty";
    });
    document.getElementById("nBP").textContent = "--/--";
    document.getElementById("nProcedures").innerHTML = '<li style="color: #3a4052;">None recorded</li>';
    document.getElementById("nMedications").innerHTML = '<li style="color: #3a4052;">None recorded</li>';
    document.getElementById("downstreamSection").style.display = "none";

    // Reset core dots
    document.querySelectorAll(".core-dot").forEach((d) => (d.className = "core-dot"));
}

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}

from pydantic import BaseModel


class NEMSISPatientInfo(BaseModel):
    """NEMSIS ePatient fields (v3.5)"""
    patient_name_last: str | None = None        # ePatient.02
    patient_name_first: str | None = None       # ePatient.03
    patient_address: str | None = None          # ePatient.05
    patient_city: str | None = None             # ePatient.06
    patient_state: str | None = None            # ePatient.08
    patient_zip: str | None = None              # ePatient.09
    patient_age: str | None = None              # ePatient.15
    patient_gender: str | None = None           # ePatient.13
    patient_race: str | None = None             # ePatient.14
    patient_phone: str | None = None            # ePatient.18
    patient_date_of_birth: str | None = None    # ePatient.17


class NEMSISVitals(BaseModel):
    """NEMSIS eVitals fields (v3.5)"""
    systolic_bp: int | None = None              # eVitals.06
    diastolic_bp: int | None = None             # eVitals.07
    heart_rate: int | None = None               # eVitals.10
    respiratory_rate: int | None = None         # eVitals.14
    spo2: int | None = None                     # eVitals.12
    blood_glucose: float | None = None          # eVitals.18
    gcs_total: int | None = None                # eVitals.23
    gcs_eye: int | None = None                  # eVitals.19
    gcs_verbal: int | None = None               # eVitals.20
    gcs_motor: int | None = None                # eVitals.21
    temperature: float | None = None            # eVitals.24
    pain_scale: int | None = None               # eVitals.27
    level_of_consciousness: str | None = None   # eVitals.26
    stroke_scale_score: int | None = None       # eVitals.29
    stroke_scale_type: str | None = None        # eVitals.30


class NEMSISSituation(BaseModel):
    """NEMSIS eSituation fields (v3.5)"""
    chief_complaint: str | None = None          # eSituation.04
    primary_impression: str | None = None       # eSituation.11
    secondary_impression: str | None = None     # eSituation.12
    injury_cause: str | None = None             # eSituation.02
    onset_date_time: str | None = None          # eSituation.01
    possible_injury: bool | None = None         # eSituation.07
    complaint_duration: str | None = None       # eSituation.05
    initial_acuity: str | None = None           # eSituation.13


class NEMSISProcedures(BaseModel):
    """NEMSIS eProcedures fields (v3.5)"""
    procedures: list[str] = []                  # eProcedures.03


class NEMSISMedications(BaseModel):
    """NEMSIS eMedications fields (v3.5)"""
    medications: list[str] = []                 # eMedications.03


class NEMSISTimes(BaseModel):
    """NEMSIS eTimes fields (v3.5) - Response time tracking."""
    unit_notified: str | None = None            # eTimes.03
    unit_en_route: str | None = None            # eTimes.05
    unit_arrived_scene: str | None = None       # eTimes.06
    arrived_at_patient: str | None = None       # eTimes.07
    transfer_of_care: str | None = None         # eTimes.08
    unit_left_scene: str | None = None          # eTimes.09
    arrived_destination: str | None = None      # eTimes.11
    unit_back_in_service: str | None = None     # eTimes.13


class NEMSISDisposition(BaseModel):
    """NEMSIS eDisposition fields (v3.5) - Patient outcome and transport."""
    destination_facility: str | None = None     # eDisposition.01
    destination_type: str | None = None         # eDisposition.02 (e.g. Hospital, Clinic)
    transport_mode: str | None = None           # eDisposition.16 (e.g. ground, air)
    transport_disposition: str | None = None    # eDisposition.12 (e.g. transported, refused)
    patient_acuity: str | None = None           # eDisposition.19 (critical, emergent, etc.)
    hospital_team_activation: list[str] = []    # eDisposition.24 (teams alerted)


class NEMSISHistory(BaseModel):
    """NEMSIS eHistory fields (v3.5) - Patient medical history."""
    medical_history: list[str] = []             # eHistory.08
    current_medications: list[str] = []         # eHistory.12
    allergies: list[str] = []                   # eHistory.06
    last_oral_intake: str | None = None         # eHistory.18
    alcohol_drug_use: str | None = None         # eHistory.17


class NEMSISRecord(BaseModel):
    """Full NEMSIS ePCR record (v3.5 compliant)"""
    patient: NEMSISPatientInfo = NEMSISPatientInfo()
    vitals: NEMSISVitals = NEMSISVitals()
    situation: NEMSISSituation = NEMSISSituation()
    procedures: NEMSISProcedures = NEMSISProcedures()
    medications: NEMSISMedications = NEMSISMedications()
    times: NEMSISTimes = NEMSISTimes()
    disposition: NEMSISDisposition = NEMSISDisposition()
    history: NEMSISHistory = NEMSISHistory()

from pydantic import BaseModel


class NEMSISPatientInfo(BaseModel):
    """NEMSIS ePatient fields"""
    patient_name_last: str | None = None        # ePatient.02
    patient_name_first: str | None = None       # ePatient.03
    patient_address: str | None = None          # ePatient.05
    patient_city: str | None = None             # ePatient.06
    patient_state: str | None = None            # ePatient.08
    patient_zip: str | None = None              # ePatient.09
    patient_age: str | None = None              # ePatient.15
    patient_gender: str | None = None           # ePatient.13
    patient_race: str | None = None             # ePatient.14


class NEMSISVitals(BaseModel):
    """NEMSIS eVitals fields"""
    systolic_bp: int | None = None              # eVitals.06
    diastolic_bp: int | None = None             # eVitals.07
    heart_rate: int | None = None               # eVitals.10
    respiratory_rate: int | None = None         # eVitals.14
    spo2: int | None = None                     # eVitals.12
    blood_glucose: float | None = None          # eVitals.18
    gcs_total: int | None = None                # eVitals.23


class NEMSISSituation(BaseModel):
    """NEMSIS eSituation fields"""
    chief_complaint: str | None = None          # eSituation.04
    primary_impression: str | None = None       # eSituation.11
    secondary_impression: str | None = None     # eSituation.12
    injury_cause: str | None = None             # eSituation.02


class NEMSISProcedures(BaseModel):
    """NEMSIS eProcedures fields"""
    procedures: list[str] = []                  # eProcedures.03


class NEMSISMedications(BaseModel):
    """NEMSIS eMedications fields"""
    medications: list[str] = []                 # eMedications.03


class NEMSISRecord(BaseModel):
    """Full NEMSIS ePCR record"""
    patient: NEMSISPatientInfo = NEMSISPatientInfo()
    vitals: NEMSISVitals = NEMSISVitals()
    situation: NEMSISSituation = NEMSISSituation()
    procedures: NEMSISProcedures = NEMSISProcedures()
    medications: NEMSISMedications = NEMSISMedications()

from pydantic import BaseModel


class MedicationInfo(BaseModel):
    drug_name: str
    dosage: str | None = None
    frequency: str | None = None
    start_date: str | None = None


class PatientContext(BaseModel):
    patient_id: str
    name: str
    age: int
    gender: str
    chronic_diseases: list[str] = []
    allergies: list[str] = []
    current_medications: list[MedicationInfo] = []
    risk_level: str = "green"
    care_team_id: str | None = None

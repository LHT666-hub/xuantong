from enum import Enum


class EventType(str, Enum):
    PATIENT_MESSAGE_RECEIVED = "patient.message.received"
    BLOOD_PRESSURE_RECORDED = "blood_pressure.recorded"
    BLOOD_GLUCOSE_RECORDED = "blood_glucose.recorded"
    REPORT_UPLOADED = "report.uploaded"
    FOLLOWUP_DUE = "followup.due"
    MEDICATION_MISSED = "medication.missed"
    RISK_DETECTED = "risk.detected"
    TASK_OVERDUE = "task.overdue"
    TASK_COMPLETED = "task.completed"
    WECOM_MESSAGE_RECEIVED = "wecom.message.received"
    CALL_COMPLETED = "call.completed"


class Channel(str, Enum):
    CHANGXI = "changxi"
    DOCTOR_WORKBENCH = "doctor_workbench"
    ADMIN_CONSOLE = "admin_console"
    WECOM = "wecom"
    VOICE = "voice"
    SYSTEM = "system"

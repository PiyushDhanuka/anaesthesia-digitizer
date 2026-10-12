from database import save_reading

# Mock data from your OCR
sample_vitals = {
    "hr": 75,
    "spo2": 98,
    "etco2": 35
}

save_reading("surgery-room-1", sample_vitals)
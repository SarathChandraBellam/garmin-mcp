"""Synthetic Garmin Personal API payloads. No real user data."""

ACTIVITY = {
    "activityId": 1001,
    "activityName": "Morning Run",
    "activityType": {"typeKey": "running"},
    "startTimeLocal": "2026-01-15 07:00:00",
    "startTimeGMT": "2026-01-15 01:30:00",
    "locationName": "Example City",
    "distance": 5000.0,
    "duration": 1800.0,
    "movingDuration": 1750.0,
    "calories": 320,
    "averageHR": 145,
    "maxHR": 172,
    "averageSpeed": 2.78,
    "elevationGain": 40,
    "steps": 4500,
    "trainingEffectLabel": "Improving",
    "differenceBodyBattery": -8,
    "hrTimeInZone_1": 60,
    "hrTimeInZone_2": 600,
    "hrTimeInZone_3": 900,
    "hrTimeInZone_4": 200,
    "hrTimeInZone_5": 40,
    # Fields the server must strip from outbound payloads:
    "ownerFullName": "REDACTED PERSON",
    "ownerDisplayName": "redacted_user",
    "ownerId": 999999,
    "userProfilePK": 999999,
    "startLatitude": 12.3456,
    "startLongitude": 78.9012,
    "endLatitude": 12.3500,
    "endLongitude": 78.9100,
}

PROFILE = {
    "displayName": "example_user",
    "preferredLocale": "en",
    "measurementSystem": "metric",
    "firstDayOfWeek": "monday",
}

DAILY_SUMMARY = {
    "data": [
        {
            "calendarDate": "2026-01-15",
            "userProfilePk": 999999,
            "calories": {"totalKilocalories": 2100},
            "heartRate": {"restingHeartRate": 52, "maxHeartRate": 160},
            "stress": {"averageStressLevel": 25},
            "bodyBattery": {"highest": 90, "lowest": 30},
        }
    ]
}

SLEEP = {
    "calendarDate": "2026-01-15",
    "sleepTimeSeconds": 27_000,
    "deepSleepSeconds": 5_400,
    "lightSleepSeconds": 14_400,
    "remSleepSeconds": 5_400,
    "awakeSleepSeconds": 1_800,
    "userProfilePK": 999999,
}

HEART_RATE = {
    "calendarDate": "2026-01-15",
    "restingHeartRate": 52,
    "minHeartRate": 48,
    "maxHeartRate": 160,
    "lastSevenDaysAvgRestingHeartRate": 53,
    "userProfilePK": 999999,
    "heartRateValues": [[1, 60], [2, 61]] + [[i, 70] for i in range(3, 80)],
}

STEPS = [
    {"calendarDate": "2026-01-14", "values": {"totalSteps": 8000}},
    {"calendarDate": "2026-01-15", "values": {"totalSteps": 10234}},
]

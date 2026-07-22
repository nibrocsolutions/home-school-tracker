"""Sample lesson plan templates shown to teachers when the admin enables the feature."""

HISTORY_AUDIO_URL = (
    "https://tanbooks.com/account.php?action=download_item&data="
    "OTU5NDk5LDI4NzksMzA2OTAwLDFmYzRlYTFiYjAxYTYyOTk5ODAwYjYwMDQ0NDBlY2E2LDQ2OTMwOTgwNDIwNTIxODMwODE5NjI2OTQxMjg3MDk="
)

CLASSICAL_CONVERSATIONS_URL = "https://classicalconversations.com/programs/essentials/"

SAMPLE_LESSON_PLANS: list[dict] = [
    {
        "id": "math-science-day",
        "title": "Math & Science Day",
        "description": "Kick off the day with numbers, experiments, and curiosity!",
        "activities": [
            {
                "title": "Morning Math Warm-up",
                "description": "Complete 15 multiplication problems in your workbook.",
                "activity_type": "regular",
            },
            {
                "title": "Science Experiment",
                "description": "Build a baking soda volcano and record observations.",
                "activity_type": "regular",
            },
            {
                "title": "Reading Break",
                "description": "Read for 20 minutes from your current book.",
                "activity_type": "subject",
            },
        ],
    },
    {
        "id": "history-reflection",
        "title": "History & Reflection",
        "description": "Listen to today's history lesson and share what you learned.",
        "activities": [
            {
                "title": "History Audio Lesson",
                "description": "Listen to the history lesson audio, then tell your teacher what you learned.",
                "activity_type": "history",
                "teacher_notes": "History audio is available from the subject resource link.",
            },
            {
                "title": "Timeline Work",
                "description": "Add new events to your history timeline.",
                "activity_type": "subject",
            },
        ],
    },
    {
        "id": "co-op-day",
        "title": "Co-Op & Community Day",
        "description": "Community learning day with co-op friends.",
        "activities": [
            {
                "title": "Co-Op Morning Session",
                "description": "Attend co-op classes and participate in group activities.",
                "activity_type": "special",
            },
            {
                "title": "Classical Conversations Essentials",
                "description": "Review Essentials program materials and presentations.",
                "activity_type": "special",
                "external_link": CLASSICAL_CONVERSATIONS_URL,
            },
        ],
    },
    {
        "id": "wild-and-free",
        "title": "Wild and Free Outing",
        "description": "Explore nature and learn through outdoor adventure.",
        "activities": [
            {
                "title": "Nature Walk & Observation",
                "description": "Identify plants, insects, or wildlife on your outing.",
                "activity_type": "special",
            },
            {
                "title": "Outdoor Journal",
                "description": "Sketch or write about something interesting you discovered.",
                "activity_type": "regular",
            },
        ],
    },
]

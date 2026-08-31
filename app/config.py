# This file for control the data of each parts of project.



# How many times to check a screen once (second)
CHECK_INTERVAL = 1.5

# Shrink a picture to this size before giving to the Nudenet
THUMBNAIL_SIZE = 320

# The threshold value of each body parts(reach this will trigger block)
DETECTION_THRESHOLD = 0.5


# Detect the naked part
Block_LABELS = {
    "FEMALE_BREAST_EXPOSED",
    "MALE_BREAST_EXPOSED",
    "FEMALE_GENITALIA_EXPOSED",
    "MALE_GENITALIA_EXPOSED",
    "BUTTOCKS_EXPOSED",
    "ANUS_EXPOSED",
}


# Blocked apps and websites
BLOCKED_APPS = [

]

# Blocking interface color
OVERLAY_BG = "#1e1e2e"
OVERLAY_TITLE_COLOR = "#cba6f7"
OVERLAY_TEXT_COLOR = "#cdd6f4"
OVERLAY_BUTTON_BG = "#313244"
OVERLAY_BUTTON_TEXT = "#a6e3a1"


# Text of blocking interface
OVERLAY_TITLE_TEXT = "wait second mate!!!"
OVERLAY_BODY_TEXT = (
    "hands on!\n"
    "Take breath, you can do it"
)
OVERLAY_BUTTON_TEXT = "I've recovered"




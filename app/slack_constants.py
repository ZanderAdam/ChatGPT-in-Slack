from app.env import OPENAI_TIMEOUT_SECONDS
import random

TIMEOUT_ERROR_MESSAGE = (
    f":warning: Apologies! It seems that OpenAI didn't respond within the {OPENAI_TIMEOUT_SECONDS}-second timeframe. "
    "Please try your request again later. "
    "If you wish to extend the timeout limit, "
    "you may consider deploying this app with customized settings on your infrastructure. :bow:"
)

LOADING_MESSAGES = [
    ":hourglass_flowing_sand: Wait a second, please...",
    ":brain: Thinking deep thoughts...",
    ":rocket: Launching intelligence engines...",
    ":bulb: Having a bright idea...",
    ":robot_face: Activating neural networks...",
    ":crystal_ball: Gazing into the future...",
    ":sparkles: Sprinkling some AI magic...",
    ":gear: Cranking the idea machine...",
    ":coffee: Brewing up a response...",
    ":detective: Investigating the perfect answer..."
]

def get_random_loading_message():
    return random.choice(LOADING_MESSAGES)

MAX_MESSAGE_LENGTH = 3000
